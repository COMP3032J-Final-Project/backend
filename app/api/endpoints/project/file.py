from typing import Annotated

from app.api.deps import get_current_project, get_current_user, get_db
from app.models.base import APIResponse
from app.models.project.file import File
from app.models.project.project import Project
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


@router.get("/{file_id}")
async def get_file(
    current_project: Annotated[Project, Depends(get_current_project)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file_id: str,
):
    return {"project_id": project_id, "file_id": file_id}
