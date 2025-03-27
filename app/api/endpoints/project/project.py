from typing import Annotated, List
import uuid
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
    ProjectInfo,
    OwnerInfo,
    ProjectsDelete,
)
from app.models.user import User, UserInfo
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


@router.get("/", response_model=APIResponse[List[ProjectInfo]])
async def get_projects(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse[List[ProjectInfo]]:
    """获取当前用户的所有项目"""
    projects = await ProjectDAO.get_projects(current_user, db)

    # 补充其他信息
    projects_info = []
    for project in projects:
        project_info = ProjectInfo.model_validate(project)
        owner = await ProjectDAO.get_project_owner(project, db)
        owner_info = OwnerInfo.model_validate(owner)
        members_num = len(await ProjectDAO.get_members(project, db))
        project_info.owner = owner_info
        project_info.members_num = members_num
        projects_info.append(project_info)
    return APIResponse(code=200, data=projects_info, msg="success")


@router.get("/{project_id:uuid}", response_model=APIResponse[ProjectInfo])
async def get_project(
    current_user: Annotated[User, Depends(get_current_user)],
    current_project: Annotated[Project, Depends(get_current_project)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """获取项目详情"""
    is_member = await ProjectDAO.is_project_member(current_project, current_user, db)
    if not is_member:
        raise HTTPException(status_code=403, detail="No permission to access this project")

    # 补充其他信息
    owner = await ProjectDAO.get_project_owner(current_project, db)
    owner_info = OwnerInfo.model_validate(owner)
    members_num = len(await ProjectDAO.get_members(current_project, db))

    project_info = ProjectInfo.model_validate(current_project)
    project_info.owner = owner_info
    project_info.members_num = members_num

    return APIResponse(code=200, data=project_info, msg="success")


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
    is_owner = await ProjectDAO.is_project_owner(current_project, current_user, db)
    if not is_admin and not is_owner:
        raise HTTPException(status_code=403, detail="No permission to update this project")

    updated_project = await ProjectDAO.update_project(current_project, project_update, db)
    if updated_project is None:
        raise HTTPException(status_code=400, detail="Failed to update project")
    return APIResponse(code=200, data=updated_project, msg="Project updated")


@router.delete("/", response_model=APIResponse)
async def delete_projects(
    projects_delete: ProjectsDelete,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse:
    """删除当前用户某些项目"""
    project_ids = set(projects_delete.project_ids)
    invalid_projects = []
    unauthorized_projects = []

    # 验证项目
    for project_id in project_ids:
        project = await ProjectDAO.get_project_by_id(project_id, db)
        if not project:
            invalid_projects.append(str(project_id))
            continue
        is_owner = await ProjectDAO.is_project_owner(project, current_user, db)
        if not is_owner:
            unauthorized_projects.append(str(project_id))

    # 若无效或无权限
    if invalid_projects or unauthorized_projects:
        error_messages = []
        if invalid_projects:
            error_messages.append(f"Projects not found: {', '.join(invalid_projects)}")
        if unauthorized_projects:
            error_messages.append(f"No permission to delete projects: {', '.join(unauthorized_projects)}")
        raise HTTPException(status_code=400, detail=" | ".join(error_messages))

    # 删除项目
    for project_id in project_ids:
        project = await ProjectDAO.get_project_by_id(project_id, db)
        await ProjectDAO.delete_project(project, db)

    return APIResponse(code=200, msg="Projects deleted")


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
