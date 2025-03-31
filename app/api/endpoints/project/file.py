import uuid
from typing import Annotated

from app.api.deps import get_current_project, get_current_user, get_db
from app.models.base import APIResponse
from app.models.project.file import File, FileCreate, FileUpdate, FileStatus, FileURL, FileUploadResponse
from app.models.project.project import Project
from app.models.user import User
from app.repositories.project.file import FileDAO
from app.repositories.project.project import ProjectDAO
from fastapi import APIRouter, Depends, HTTPException, Path
from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter()


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
    return APIResponse(code=200, data=files)


@router.get("/{file_id:uuid}")
async def get_file_download_url(
    file_id: Annotated[uuid.UUID, Path(...)],
    current_user: Annotated[User, Depends(get_current_user)],
    current_project: Annotated[Project, Depends(get_current_project)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    获取文件下载URL
    """
    is_member = await ProjectDAO.is_project_member(current_project, current_user, db)
    if not is_member:
        raise HTTPException(status_code=403, detail="No permission to access this project")

    file = await FileDAO.get_file_by_id(file_id=file_id, db=db)
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    url = await FileDAO.generate_get_obj_link_for_file(file=file, expiration=3600)

    return APIResponse(code=200, data=FileURL(url=url), msg="success")


@router.post("/create", response_model=APIResponse[File])
async def create_file(
    file_create: FileCreate,
    current_project: Annotated[Project, Depends(get_current_project)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse[File]:
    new_file = await FileDAO.create_file(file_create=file_create, project=current_project, db=db)
    return APIResponse(code=200, data=new_file, msg="success")


@router.post("/update", response_model=APIResponse[File])
async def update_file(
    file_update: FileUpdate,
    current_project: Annotated[Project, Depends(get_current_project)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse[File]:
    new_file = await FileDAO.update_file(file_update=file_update, project=current_project, db=db)
    return APIResponse(code=200, data=new_file, msg="success")


@router.post("/delete", response_model=APIResponse[File])
async def update_file(
    file_delete: FileUpdate,
    current_project: Annotated[Project, Depends(get_current_project)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse[File]:
    new_file = await FileDAO.delete_file(file=file_delete, project=current_project, db=db)
    return APIResponse(code=200, data=new_file, msg="success")


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
    file = await FileDAO.get_file_by_path(file_create.filename, file_create.filepath, db)
    if file:
        raise HTTPException(status_code=400, detail="File already exists")

    new_file = await FileDAO.create_file(file_create, current_project, db)
    url = await FileDAO.generate_put_obj_link_for_file(file=new_file)

    response_data = FileUploadResponse(
        file_id=new_file.id,
        url=url,
    )
    return APIResponse(code=200, data=response_data, msg="success")


@router.put("/{file_id}/confirm-upload", response_model=APIResponse)
async def confirm_file_upload(
    file_id: Annotated[uuid.UUID, Path(...)],
    current_project: Annotated[Project, Depends(get_current_project)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    确认文件已上传到R2
    """
    # 检查用户权限
    is_member = await ProjectDAO.is_project_member(current_project, current_user, db)
    is_viewer = await ProjectDAO.is_project_viewer(current_project, current_user, db)
    if not is_member or is_viewer:
        raise HTTPException(status_code=403, detail="No permission to access this file")

    # 检查文件
    file = await FileDAO.get_file_by_id(file_id, db)
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    if file.project_id != current_project.id:
        raise HTTPException(status_code=403, detail="No permission to access this file")

    # 检查文件是否存在于R2
    is_exists = await FileDAO.check_file_in_r2(file)
    if is_exists:
        file.status = FileStatus.UPLOADED
        await db.commit()
        return APIResponse(code=200, data=file, msg="File uploaded successfully")
    else:
        file.status = FileStatus.FAILED
        await db.commit()
        raise HTTPException(status_code=404, detail="File not uploaded to R2")
