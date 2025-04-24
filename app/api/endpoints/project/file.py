import uuid
from base64 import b64encode
from typing import Annotated

from app.api.deps import (get_current_project, get_current_project_file,
                          get_current_user, get_db)
from app.api.endpoints.project.websocket_handlers import (
    get_project_channel_name, project_general_manager)
from app.models.base import APIResponse
from app.models.project.file import (File, FileCreateUpdate, FilesDelete,
                                     FileUploadResponse, FileURL)
from app.models.project.websocket import EventScope, FileAction, Message
from app.models.user import User
from app.repositories.project.file import FileDAO
from app.repositories.project.project import ProjectDAO
from fastapi import APIRouter, Depends, HTTPException, Path
from lib.utils import decode_base64url
from loguru import logger
from loro import ExportMode, LoroDoc, VersionVector
from sqlmodel.ext.asyncio.session import AsyncSession

from .crdt_handler import crdt_handler

router = APIRouter()


@router.get("/", response_model=APIResponse[File])
async def list_files(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: uuid.UUID = Path(...),
):
    """
    获取项目文件列表
    """
    current_project = await get_current_project(current_user, project_id, db)

    files = await ProjectDAO.get_files(project=current_project)
    return APIResponse(code=200, data=files, msg="success")


@router.get("/{file_id:uuid}")
async def get_file_download_url(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: uuid.UUID = Path(...),
    file_id: uuid.UUID = Path(...),
    crdt_protected: bool = False,
) -> APIResponse[FileURL]:
    """
    获取文件下载URL
    """
    current_project, current_file = await get_current_project_file(current_user, project_id, file_id, db)

    # 检查文件是否存在于 R2
    is_exists = await FileDAO.check_file_exist_in_r2(current_file)
    if not is_exists:
        raise HTTPException(status_code=404, detail="File does not exist remotely (r2).")

    if crdt_protected:
        data = FileDAO.get_r2_file_data(file_id)
        doc = LoroDoc()
        try:
            doc.import_(data)
        except BaseException:
            try:
                new_file_content = doc.export(ExportMode.Snapshot())
            except:
                new_file_content = b""

            try:
                FileDAO.update_r2_file(new_file_content, file_id)
            except:
                raise HTTPException(status_code=400, detail="CRDT Protection Failed")

    url = await FileDAO.generate_get_obj_link_for_file(file=current_file, expiration=3600)
    return APIResponse(code=200, data=FileURL(url=url), msg="success")


@router.get("/{file_id:uuid}/crdt", response_model=APIResponse[str])
async def get_file_crdt_missing_ops(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    opLogVersion: str,  # base64 string
    project_id: uuid.UUID = Path(...),
    file_id: uuid.UUID = Path(...),
):
    # 检查文件是否存在于 R2
    current_project, current_file = await get_current_project_file(current_user, project_id, file_id, db)

    is_exists = await FileDAO.check_file_exist_in_r2(current_file)
    if not is_exists:
        raise HTTPException(status_code=404, detail="File does not exist remotely (r2).")

    doc = await crdt_handler.get_doc(str(current_file.id))
    try:
        vv = VersionVector.decode(decode_base64url(opLogVersion))
    except:
        raise HTTPException(status_code=400, detail="Version vector decode error.")

    raw_updates = doc.export(ExportMode.Updates(vv))
    updates = b64encode(raw_updates)
    return APIResponse(code=200, data=updates, msg="success")


@router.delete("/{file_id:uuid}", response_model=APIResponse)
async def delete_file(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: uuid.UUID = Path(...),
    file_id: uuid.UUID = Path(...),
) -> APIResponse:
    """
    删除文件
    """
    current_project, current_file = await get_current_project_file(current_user, project_id, file_id, db)

    # 检查用户权限
    is_member = await ProjectDAO.is_project_member(current_project, current_user, db)
    is_viewer = await ProjectDAO.is_project_viewer(current_project, current_user, db)
    if not is_member or is_viewer:
        raise HTTPException(status_code=403, detail="No permission to delete this file")

    # 检查文件是否存在于 R2
    is_exists = await FileDAO.check_file_exist_in_r2(current_file)
    if not is_exists:
        raise HTTPException(status_code=404, detail="File does not exist remotely (r2).")

    try:
        if await FileDAO.delete_file(file=current_file, db=db):
            # 广播
            channel = get_project_channel_name(current_project.id)
            await project_general_manager.publish(
                channel,
                Message(
                    client_id=str(current_user.id),
                    scope=EventScope.FILE,
                    action=FileAction.DELETED,
                    payload=[file_id],
                ).model_dump_json(),
            )
            return APIResponse(code=200, msg="success")

    except Exception as e:
        logger.error(f"Error deleting file: {e}")

    raise HTTPException(status_code=500, detail="Failed to delete file")


@router.delete("/", response_model=APIResponse)
async def delete_files(
    files_delete: FilesDelete,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: uuid.UUID = Path(...),
):
    """
    删除多个文件
    """
    current_project = await get_current_project(current_user, project_id, db)

    file_ids = set(files_delete.file_ids)
    files = []
    invalid_files = []
    unauthorized_files = []

    for file_id in file_ids:
        file = await FileDAO.get_file_by_id(file_id, db)
        if not file:
            invalid_files.append(str(file_id))
            continue

        is_member = await ProjectDAO.is_project_member(current_project, current_user, db)
        is_viewer = await ProjectDAO.is_project_viewer(current_project, current_user, db)
        if current_project.id != file.project_id or not is_member or is_viewer:
            unauthorized_files.append(str(file_id))
            continue

        files.append(file)

    if invalid_files or unauthorized_files:
        error_messages = []
        if invalid_files:
            error_messages.append(f"Files not found: {', '.join(invalid_files)}")
        if unauthorized_files:
            error_messages.append(f"No permission to delete files: {', '.join(unauthorized_files)}")
        raise HTTPException(status_code=400, detail=" | ".join(error_messages))

    for file in files:
        await FileDAO.delete_file(file, db)

    try:
        # 单次广播
        channel = get_project_channel_name(current_project.id)
        await project_general_manager.publish(
            channel,
            Message(
                client_id=str(current_user.id),
                scope=EventScope.FILE,
                action=FileAction.DELETED,
                payload=file_ids,
            ).model_dump_json(),
        )
    except Exception as e:
        logger.error(f"Failed to broadcast file deletion: {str(e)}")

    return APIResponse(code=200, msg="success")


@router.post("/create_update", response_model=APIResponse[FileUploadResponse])
async def create_update_file(
    file_create_update: FileCreateUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: uuid.UUID = Path(...),
) -> APIResponse[FileUploadResponse]:
    """
    创建File对象,并获取文件上传URL
    """
    current_project = await get_current_project(current_user, project_id, db)

    # 检查用户权限
    is_member = await ProjectDAO.is_project_member(current_project, current_user, db)
    is_viewer = await ProjectDAO.is_project_viewer(current_project, current_user, db)
    if not is_member or is_viewer:
        raise HTTPException(status_code=403, detail="No permission to upload files")

    file, url = await FileDAO.create_update_file(file_create_update=file_create_update, project=current_project, db=db)
    response_data = FileUploadResponse(file_id=file.id, url=url)
    return APIResponse(code=200, data=response_data, msg="success")


@router.post("/confirm")
async def confirm_file(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: uuid.UUID = Path(...),
    file_id: uuid.UUID = Path(...),
):
    """
    创建File对象,并获取文件上传URL
    """
    current_project = await get_current_project(current_user, project_id, db)

    # 检查用户权限
    is_member = await ProjectDAO.is_project_member(current_project, current_user, db)
    is_viewer = await ProjectDAO.is_project_viewer(current_project, current_user, db)
    if not is_member or is_viewer:
        raise HTTPException(status_code=403, detail="No permission to upload files")

    await FileDAO.confirm_file(file_id=file_id, db=db)
    return APIResponse(code=200, msg="success")


@router.get("/{file_id:uuid}/exist", response_model=APIResponse[File])
async def check_file_exist(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: uuid.UUID = Path(...),
    file_id: uuid.UUID = Path(...),
) -> APIResponse[File]:
    """
    确认文件已上传到R2
    """
    current_project, current_file = await get_current_project_file(current_user, project_id, file_id, db)

    # 检查用户权限
    is_member = await ProjectDAO.is_project_member(current_project, current_user, db)
    is_viewer = await ProjectDAO.is_project_viewer(current_project, current_user, db)
    if not is_member or is_viewer:
        raise HTTPException(status_code=403, detail="No permission to access this file")

    # 检查文件是否存在于R2
    is_exists = await FileDAO.check_file_exist_in_r2(current_file)
    if is_exists:

        # 广播
        try:
            channel = get_project_channel_name(current_project.id)
            await project_general_manager.publish(
                channel,
                Message(
                    client_id=str(current_user.id),
                    scope=EventScope.FILE,
                    action=FileAction.ADDED,
                    payload=current_file.model_dump(),
                ).model_dump_json(),
            )
        except Exception as e:
            logger.error(f"Failed to broadcast file added: {str(e)}")

        return APIResponse(code=200, data=current_file, msg="File uploaded successfully")

    raise HTTPException(status_code=404, detail="File does not exist remotely (r2).")


@router.put("/{file_id:uuid}/mv", response_model=APIResponse[File])
async def mv(
    file_create_update: FileCreateUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: uuid.UUID = Path(...),
    file_id: uuid.UUID = Path(...),
) -> APIResponse[File]:
    """
    移动/重命名文件
    """
    current_project, current_file = await get_current_project_file(current_user, project_id, file_id, db)

    # 检查用户权限
    is_member = await ProjectDAO.is_project_member(current_project, current_user, db)
    is_viewer = await ProjectDAO.is_project_viewer(current_project, current_user, db)
    if not is_member or is_viewer:
        raise HTTPException(status_code=403, detail="No permission to access this file")

    # 检查文件是否存在于 R2
    is_exists = await FileDAO.check_file_exist_in_r2(current_file)
    if not is_exists:
        raise HTTPException(status_code=404, detail="File does not exist remotely (r2).")

    try:
        file = await FileDAO.move_file(file=current_file, file_create_update=file_create_update, db=db)
    except Exception as error:
        return APIResponse(code=500, detail=f"{error}")

    # 广播
    try:
        file_action = FileAction.MOVED if file_create_update.filepath else FileAction.RENAMED
        channel = get_project_channel_name(current_project.id)
        await project_general_manager.publish(
            channel,
            Message(
                client_id=str(current_user.id),
                scope=EventScope.FILE,
                action=file_action,
                payload=file.model_dump(),
            ).model_dump_json(),
        )
    except Exception as e:
        logger.error(f"Failed to broadcast move file: {str(e)}")

    return APIResponse(code=200, data=file, msg="success")


@router.put("/{file_id:uuid}/cp", response_model=APIResponse[File])
async def cp(
    file_create_update: FileCreateUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: uuid.UUID = Path(...),
    file_id: uuid.UUID = Path(...),
) -> APIResponse[File]:
    """
    复制文件
    """
    current_project, current_file = await get_current_project_file(current_user, project_id, file_id, db)

    # 检查用户权限
    is_member = await ProjectDAO.is_project_member(current_project, current_user, db)
    is_viewer = await ProjectDAO.is_project_viewer(current_project, current_user, db)
    if not is_member or is_viewer:
        raise HTTPException(status_code=403, detail="No permission to access this file")

    # 检查文件是否存在于 R2
    is_exists = await FileDAO.check_file_exist_in_r2(current_file)
    if not is_exists:
        raise HTTPException(status_code=404, detail="File does not exist remotely (r2).")

    try:
        file = await FileDAO.copy_file(
            source_file=current_file,
            target_file_create_update=file_create_update,
            target_project=current_project,
            db=db,
        )
    except Exception as error:
        return APIResponse(code=500, detail=f"{error}")

    # 广播
    try:
        channel = get_project_channel_name(current_project.id)
        await project_general_manager.publish(
            channel,
            Message(
                client_id=str(current_user.id),
                scope=EventScope.FILE,
                action=FileAction.ADDED,
                payload=file.model_dump(),
            ).model_dump_json(),
        )
    except Exception as e:
        logger.error(f"Failed to broadcast copy file: {str(e)}")

    return APIResponse(code=200, data=file, msg="success")


@router.put("/{file_id:uuid}/test", response_model=APIResponse)
async def test_remote_file_path(
    file_id: Annotated[uuid.UUID, Path(...)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    file = await FileDAO.get_file_by_id(file_id=file_id, db=db)
    if file:
        filepath = FileDAO.get_remote_file_path(file.id)
        return APIResponse(code=200, data=filepath, msg="success")
    else:
        return APIResponse(code=404, msg="file does not exist in db.")
