from typing import Annotated, List
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, HTTPException, Depends

from app.api.deps import get_current_project, get_current_user, get_db
from app.models.base import APIResponse
from app.models.project.project import (
    Project,
    ProjectCreate,
    ProjectUpdate,
    ProjectID,
    ProjectPermission,
)
from app.models.user import User
from app.repositories.project.chat import ChatDAO
from app.repositories.project.project import ProjectDAO

router = APIRouter()


@router.post("/create", response_model=APIResponse[ProjectID])
async def create_project(
    project_create: ProjectCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse:
    """创建新项目"""
    new_project = await ProjectDAO.create_project(project_create, db)
    await ProjectDAO.add_member(new_project, current_user, ProjectPermission.OWNER, db)
    # 创建聊天室
    await ChatDAO.create_chat_room(project_create.name, new_project.id, db)
    return APIResponse(code=200, data=ProjectID(project_id=new_project.id), msg="success")


@router.get("/", response_model=APIResponse[List[Project]])
async def get_projects(
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse[List[Project]]:
    """获取当前用户的所有项目"""
    projects = await ProjectDAO.get_projects(current_user, db)
    return APIResponse(code=200, data=projects, msg="success")


@router.get("/{project_id:uuid}", response_model=APIResponse[Project])
async def get_project(
    current_user: Annotated[User, Depends(get_current_user)],
    current_project: Annotated[Project, Depends(get_current_project)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """获取项目详情"""
    is_member = await ProjectDAO.is_project_member(current_project, current_user, db)
    if not is_member:
        raise HTTPException(status_code=403, detail="No permission to access this project")
    return APIResponse(code=200, data=current_project, msg="success")


@router.put("/{project_id:uuid}", response_model=APIResponse[Project])
async def update_project(
    project_update: ProjectUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    current_project: Annotated[Project, Depends(get_current_project)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse:
    """更新项目信息"""
    # 检查用户是否为项目管理员或创建者
    is_admin = await ProjectDAO.is_project_admin(current_project, current_user, db)
    is_owner = await ProjectDAO.is_project_owner(current_project, current_user ,db)
    if not is_admin and not is_owner:
        raise HTTPException(status_code=403, detail="No permission to update this project")

    updated_project = await ProjectDAO.update_project(current_project, project_update, db)
    return APIResponse(code=200, data=updated_project, msg="Project updated")


@router.delete("/{project_id:uuid}", response_model=APIResponse)
async def delete_project(
    current_user: Annotated[User, Depends(get_current_user)],
    current_project: Annotated[Project, Depends(get_current_project)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse:
    """删除项目"""
    # 检查用户是否为项目创建者
    is_owner = await ProjectDAO.is_project_owner(current_project, current_user, db)
    if not is_owner:
        raise HTTPException(status_code=403, detail="No permission to delete this project")
    # !ChatRoom和ChatMessage会被级联删除
    await ProjectDAO.delete_project(current_project, db)
    return APIResponse(msg="Project deleted")
