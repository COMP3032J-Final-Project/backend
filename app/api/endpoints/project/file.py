import mimetypes
import uuid
from typing import Annotated

from app.api.deps import get_current_project, get_current_user, get_db
from app.models.base import APIResponse
from app.models.project.file import File, FileCreate
from app.models.project.project import Project
from app.models.user import User
from app.repositories.project.file import FileDAO
from app.repositories.project.project import ProjectDAO
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter()


def get_mime_type(filename: str) -> str:
    """
    根据文件名获取 MIME 类型
    """
    mime_type, _ = mimetypes.guess_type(filename)
    if not mime_type:
        return "application/octet-stream"
    return mime_type


@router.get("/", response_model=APIResponse[File])
async def list_files(
    current_user: Annotated[User, Depends(get_current_user)],
    current_project: Annotated[Project, Depends(get_current_project)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # 检查用户权限
    is_member = await ProjectDAO.is_project_member(current_project, current_user, db)
    if not is_member:
        raise HTTPException(status_code=403, detail="No permission to access this project")

    files = await ProjectDAO.get_files(project=current_project, db=db)
    return APIResponse(code=200, data=files)


@router.get("/{file_id:uuid}")
async def get_file_url(
    file_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    current_project: Annotated[Project, Depends(get_current_project)],
    db: Annotated[AsyncSession, Depends(get_db)],
):

    is_member = await ProjectDAO.is_project_member(current_project, current_user, db)
    if not is_member:
        raise HTTPException(status_code=403, detail="No permission to access this project")

    file = await FileDAO.get_file_by_id(file_id=file_id, db=db)
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    url = await FileDAO.generate_get_obj_link_for_file(file=file, expiration=3600)
    return APIResponse(status_code=200, data=url, msg="success")


# @router.get("/{file_id:uuid}")
# async def get_file(
#     file_id: uuid.UUID,
#     current_user: Annotated[User, Depends(get_current_user)],
#     current_project: Annotated[Project, Depends(get_current_project)],
#     db: Annotated[AsyncSession, Depends(get_db)],
# ):
#     """
#     获取文件内容
#     """
#     # 检查用户权限
#     is_member = await ProjectDAO.is_project_member(current_project, current_user, db)
#     if not is_member:
#         raise HTTPException(status_code=403, detail="No permission to access this project")

#     file = await FileDAO.get_file_by_id(file_id=file_id, db=db)
#     if not file:
#         raise HTTPException(status_code=404, detail="File not found")

#     try:
#         binary_file = await FileDAO.pull_file_from_r2(file)

#         if not binary_file:
#             raise HTTPException(status_code=500, detail="Failed to retrieve file from storage")

#         # 获取 MIME 类型
#         mime_type = get_mime_type(file.filename)

#         return StreamingResponse(binary_file, media_type=mime_type)
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Error retrieving file: {str(e)}")


@router.post("/create", response_model=APIResponse[File])
async def create_file(
    file_create: FileCreate,
    current_project: Annotated[Project, Depends(get_current_project)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse[File]:
    new_file = await FileDAO.create_file(file_create=file_create, project=current_project, db=db)
    return APIResponse(code=200, data=new_file, msg="success")
