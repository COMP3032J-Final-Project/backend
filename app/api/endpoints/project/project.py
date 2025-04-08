from typing import Annotated, List

from loguru import logger

from app.api.deps import get_current_project, get_current_user, get_db
from app.models.base import APIResponse
from app.models.project.project import (
    Project,
    ProjectCreate,
    ProjectID,
    ProjectInfo,
    ProjectPermission,
    ProjectsDelete,
    ProjectType,
    ProjectUpdate,
)
from app.models.user import User
from app.repositories.project.chat import ChatDAO
from app.repositories.project.project import ProjectDAO
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.project.websocket import EventType, EventScope
from app.core.websocket import project_general_manager

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

    # 若type为template，复制模板(未完成)
    if project_create.type == ProjectType.TEMPLATE:
        template_project = await ProjectDAO.get_project_by_name("simple article", db)
        await ProjectDAO.copy_template(template_project, new_project, db)

    return APIResponse(code=200, data=ProjectID(project_id=new_project.id), msg="success")


@router.get("/", response_model=APIResponse[List[ProjectInfo]])
async def get_projects(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse[List[ProjectInfo]]:
    """获取当前用户的所有项目"""
    projects = await ProjectDAO.get_projects(current_user, db)

    # 包装项目信息
    projects_info = []
    for project in projects:
        project_info = await ProjectDAO.get_project_info(project, db)
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

    project_info = await ProjectDAO.get_project_info(current_project, db)
    return APIResponse(code=200, data=project_info, msg="success")


@router.put("/{project_id:uuid}", response_model=APIResponse)
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

    # # 发送广播
    # try:
    #     channel = str(updated_project.id)
    #     project_info = await ProjectDAO.get_project_info(updated_project, db)
    #     project_info_dict = project_info.model_dump(mode="json")

    #     updated_message = {
    #         "event_type": EventType.PROJECT_UPDATED,
    #         "event_scope": EventScope.PROJECT,
    #         "data": project_info_dict,
    #     }

    #     await project_general_manager.send_message(channel, updated_message, "system")
    # except Exception as e:
    #     logger.error(f"Failed to broadcast project update: {str(e)}")

    return APIResponse(code=200, msg="Project updated")


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

    # 删除项目
    await ProjectDAO.delete_project(current_project, db)

    # 发送广播
    try:
        channel = str(current_project.id)
        deleted_message = {
            "event_scope": EventScope.PROJECT,
            "event_type": EventType.PROJECT_DELETED,
            "data": {
                "project_id": str(current_project.id),
            },
        }
        await project_general_manager.publish_message(channel, deleted_message)
    except Exception as e:
        logger.error(f"Failed to broadcast project deletion: {str(e)}")

    return APIResponse(msg="Project deleted")
