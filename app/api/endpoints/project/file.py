import logging
import uuid
from typing import Annotated

from app.api.deps import (get_current_file, get_current_project,
                          get_current_user, get_db)
from app.models.base import APIResponse
from app.models.project.file import (File, FileCreateUpdate,
                                     FileUploadResponse, FileURL)
from app.models.project.project import Project
from app.models.user import User
from app.repositories.project.file import FileDAO
from app.repositories.project.project import ProjectDAO
from fastapi import APIRouter, Depends, HTTPException, Path
from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter()

logger = logging.getLogger(__name__)


@router.get("/", response_model=APIResponse[File])
async def list_files(
    current_user: Annotated[User, Depends(get_current_user)],
    current_project: Annotated[Project, Depends(get_current_project)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    获取项目文件列表
    """
    is_member = await ProjectDAO.is_project_member(current_project, current_user, db)
    if not is_member:
        raise HTTPException(status_code=403, detail="No permission to access this project")

    files = await ProjectDAO.get_files(project=current_project, db=db)
    return APIResponse(code=200, data=files, msg="success")


@router.get("/{file_id:uuid}")
async def get_file_download_url(
    current_user: Annotated[User, Depends(get_current_user)],
    current_project: Annotated[Project, Depends(get_current_project)],
    current_file: Annotated[File, Depends(get_current_file)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse[FileURL]:
    """
    获取文件下载URL
    """
    is_member = await ProjectDAO.is_project_member(current_project, current_user, db)
    if not is_member:
        raise HTTPException(status_code=403, detail="No permission to access this file")

    url = await FileDAO.generate_get_obj_link_for_file(file=current_file, expiration=3600)
    return APIResponse(code=200, data=FileURL(url=url), msg="success")


@router.delete("/{file_id:uuid}", response_model=APIResponse[File])
async def delete_file(
    current_file: Annotated[File, Depends(get_current_file)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse[File]:
    """
    删除文件
    """
    # 检查用户权限
    is_member = await ProjectDAO.is_project_member(current_file.project, current_user, db)
    is_viewer = await ProjectDAO.is_project_viewer(current_file.project, current_user, db)
    if not is_member or is_viewer:
        raise HTTPException(status_code=403, detail="No permission to delete this file")

    try:
        if await FileDAO.delete_file(file=current_file, db=db):
            return APIResponse(code=200, msg="success")

    except Exception as e:
        logger.error(f"Error deleting file: {e}")

    raise HTTPException(status_code=500, detail="Failed to delete file")


@router.post("/create_update", response_model=APIResponse[FileUploadResponse])
async def create_update_file(
    file_create_update: FileCreateUpdate,
    current_project: Annotated[Project, Depends(get_current_project)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse[FileUploadResponse]:
    """
    创建File对象,并获取文件上传URL
    """
    # 检查用户权限
    is_member = await ProjectDAO.is_project_member(current_project, current_user, db)
    is_viewer = await ProjectDAO.is_project_viewer(current_project, current_user, db)
    if not is_member or is_viewer:
        raise HTTPException(status_code=403, detail="No permission to upload files")

    file, url = await FileDAO.create_update_file(file_create_update=file_create_update, project=current_project, db=db)
    response_data = FileUploadResponse(file_id=file.id, url=url)
    return APIResponse(code=200, data=response_data, msg="success")


@router.put("/{file_id}/exist", response_model=APIResponse[File])
async def check_file_exist(
    current_project: Annotated[Project, Depends(get_current_project)],
    current_file: Annotated[File, Depends(get_current_file)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse[File]:
    """
    确认文件已上传到R2
    """
    # 检查用户权限
    is_member = await ProjectDAO.is_project_member(current_project, current_user, db)
    is_viewer = await ProjectDAO.is_project_viewer(current_project, current_user, db)
    if not is_member or is_viewer:
        raise HTTPException(status_code=403, detail="No permission to access this file")

    # 检查文件是否存在于R2
    is_exists = await FileDAO.check_file_exist_in_r2(current_file)
    if is_exists:
        return APIResponse(code=200, data=current_file, msg="File uploaded successfully")

    raise HTTPException(status_code=404, detail="File does not exist remotely (r2).")


@router.put("/{file_id:uuid}/mv", response_model=APIResponse[File])
async def mv(
    file_create_update: FileCreateUpdate,
    current_project: Annotated[Project, Depends(get_current_project)],
    current_file: Annotated[File, Depends(get_current_file)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse[File]:

    # 检查用户权限
    is_member = await ProjectDAO.is_project_member(current_project, current_user, db)
    is_viewer = await ProjectDAO.is_project_viewer(current_project, current_user, db)
    if not is_member or is_viewer:
        raise HTTPException(status_code=403, detail="No permission to access this file")
    try:
        file = await FileDAO.move_file(file=current_file, file_create_update=file_create_update, db=db)
        return APIResponse(code=200, data=file, msg="success")
    except Exception as error:
        return APIResponse(code=500, detail=f"{error}")


@router.put("/{file_id:uuid}/cp", response_model=APIResponse[File])
async def cp(
    file_create_update: FileCreateUpdate,
    current_project: Annotated[Project, Depends(get_current_project)],
    current_file: Annotated[File, Depends(get_current_file)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse[File]:

    # 检查用户权限
    is_member = await ProjectDAO.is_project_member(current_project, current_user, db)
    is_viewer = await ProjectDAO.is_project_viewer(current_project, current_user, db)
    if not is_member or is_viewer:
        raise HTTPException(status_code=403, detail="No permission to access this file")
    try:
        file = await FileDAO.copy_file(source_file=current_file, target_file_create_update=file_create_update, db=db)
        return APIResponse(code=200, data=file, msg="success")
    except Exception as error:
        return APIResponse(code=500, detail=f"{error}")


@router.put("/{file_id:uuid}/test", response_model=APIResponse)
async def test_remote_file_path(
    file_id: Annotated[uuid.UUID, Path(...)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    file = await FileDAO.get_file_by_id(file_id=file_id, db=db)
    if file:
        filepath = FileDAO.get_remote_file_path(file=file)
        return APIResponse(code=200, data=filepath, msg="success")
    else:
        return APIResponse(code=404, msg="file does not exist in db.")
