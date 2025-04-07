import logging
import uuid
from typing import Annotated

from app.api.deps import (get_current_file, get_current_project,
                          get_current_user, get_db)
from app.models.base import APIResponse
from app.models.project.file import (File, FileCreate, FileType,
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
    # files = [file for file in files if file.status == FileStatus.UPLOADED]
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

    # if current_file.status != FileStatus.UPLOADED:
    #     raise HTTPException(status_code=404, detail="File not found")
    if current_file.filetype == FileType.FOLDER:
        raise HTTPException(status_code=400, detail="Folder cannot be downloaded")

    url = await FileDAO.generate_get_obj_link_for_file(file=current_file, expiration=3600)
    return APIResponse(code=200, data=FileURL(url=url), msg="success")


@router.post("/create", response_model=APIResponse[File])
async def create_file(
    file_create: FileCreate,
    current_project: Annotated[Project, Depends(get_current_project)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse[File]:
    new_file = await FileDAO.create_file_in_db(file_create=file_create, project=current_project, db=db)
    return APIResponse(code=200, data=new_file, msg="success")


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
        if current_file.filetype == FileType.FILE and not await FileDAO.delete_file_in_r2(current_file):
            raise HTTPException(status_code=500, detail="Failed to delete file in R2")

        await FileDAO.delete_file_in_db(current_file, db)
        return APIResponse(code=200, msg="success")
    except Exception as e:
        logger.error(f"Error deleting file: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete file")


@router.post("/upload-url", response_model=APIResponse[FileUploadResponse])
async def get_file_upload_url(
    file_create: FileCreate,
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

    # 检查文件是否已存在
    file = await FileDAO.get_file_by_path(current_project.id, file_create.filepath, file_create.filename, db)
    if file:
        raise HTTPException(status_code=400, detail="File already exists")

    # 仅文件类型上传URL
    url = None
    if file_create.filetype == FileType.FILE:
        new_file = await FileDAO.create_file_in_db(file_create, current_project, db)
        url = await FileDAO.generate_put_obj_link_for_file(file=new_file)
    elif file_create.filetype == FileType.FOLDER:
        new_file = await FileDAO.create_file_in_db(file_create, current_project, db)
        # new_file.status = FileStatus.UPLOADED

    response_data = FileUploadResponse(file_id=new_file.id, url=url)
    return APIResponse(code=200, data=response_data, msg="success")


@router.put("/{file_id}/confirm-upload", response_model=APIResponse[File])
async def confirm_file_upload(
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
    is_exists = await FileDAO.check_file_in_r2(current_file)
    if is_exists:
        # await FileDAO.update_file_in_db(current_file, FileUpdate(status=FileStatus.UPLOADED), db)
        return APIResponse(code=200, data=current_file, msg="File uploaded successfully")
    else:
        # TODO 处理文件未上传的情况
        # await FileDAO.update_file_in_db(current_file, FileUpdate(status=FileStatus.FAILED), db)
        pass

    raise HTTPException(status_code=404, detail="File not uploaded to R2")


@router.put("/{file_id}/test", response_model=APIResponse)
async def test_remote_file_path(
    file_id: Annotated[uuid.UUID, Path(...)],
):
    filepath = FileDAO.get_remote_file_path(file_id)
    return APIResponse(code=200, data=filepath, msg="success")
