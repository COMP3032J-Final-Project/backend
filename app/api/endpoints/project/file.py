import uuid
from typing import Annotated

from app.api.deps import get_current_project, get_current_user, get_db
from app.models.base import APIResponse
from app.models.project.file import File, FileCreate
from app.models.project.project import Project
from app.repositories.project.file import FileDAO
from app.repositories.project.project import ProjectDAO
from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.get("/", response_model=APIResponse[File])
async def list_files(
    current_project: Annotated[Project, Depends(get_current_project)], db: Annotated[AsyncSession, Depends(get_db)]
):
    files = await ProjectDAO.get_files(project=current_project, db=db)
    return APIResponse(code=200, data=files)


@router.get("/{file_id:uuid}")
async def get_file(
    file_id: uuid.UUID,
    current_project: Annotated[Project, Depends(get_current_project)],
    db: Annotated[AsyncSession, Depends(get_db)],
):

    file = await FileDAO.get_file_by_id(file_id=file_id, db=db)
    if file:
        binary_file = await FileDAO.pull_file_from_r2(file)
        if binary_file:
            return APIResponse(code=200, file=binary_file)


@router.post("/create", response_model=APIResponse[File])
async def create_file(
    file_create: FileCreate,
    current_project: Annotated[Project, Depends(get_current_project)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse[File]:
    new_file = await FileDAO.create_file(file_create=file_create, project=current_project, db=db)
    return APIResponse(code=200, data=new_file, msg="success")