from typing import Annotated, List
from fastapi import APIRouter, Depends, HTTPException, Path
import uuid

from loguru import logger

from app.api.deps import get_current_project, get_current_user, get_db
from app.models.base import APIResponse
from app.models.project.project import (
    MemberCreateUpdate,
    Project,
    ProjectCreate,
    ProjectID,
    ProjectInfo,
    ProjectPermission,
    ProjectTypeData,
    ProjectsDelete,
    ProjectType,
    ProjectUpdate,
)
from app.models.user import User
from app.repositories.project.chat import ChatDAO
from app.repositories.project.project import ProjectDAO
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project.websocket import Message, EventScope, ProjectAction
from .websocket_handlers import project_general_manager, get_project_channel_name

router = APIRouter()


@router.post("/create", response_model=APIResponse[ProjectID])
async def create_project(
    project_create: ProjectCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse:
    """创建新项目"""
    new_project = await ProjectDAO.create_project(project_create, db)
    await ProjectDAO.add_member(MemberCreateUpdate(permission=ProjectPermission.OWNER), new_project, current_user, db)
    await ChatDAO.create_chat_room(project_create.name, new_project.id, db)

    return APIResponse(code=200, data=ProjectID(project_id=new_project.id), msg="success")


@router.post("/{project_id:uuid}/create_project", response_model=APIResponse)
async def create_project_from_template(
    project_create: ProjectCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: uuid.UUID = Path(...),
) -> APIResponse:
    """从模板创建项目"""
    current_template = await get_current_project(current_user, project_id, db)

    if current_template.type != ProjectType.TEMPLATE:
        raise HTTPException(status_code=404, detail="Template not found")

    project_create.type = ProjectType.PROJECT
    new_project = await ProjectDAO.create_project(project_create, db)
    await ProjectDAO.add_member(MemberCreateUpdate(permission=ProjectPermission.OWNER), new_project, current_user, db)
    await ChatDAO.create_chat_room(project_create.name, new_project.id, db)
    await ProjectDAO.copy_project(current_template, new_project, db)

    return APIResponse(code=200, data=ProjectID(project_id=new_project.id), msg="Project created")


@router.post("/{project_id:uuid}/create_template", response_model=APIResponse)
async def create_template_from_project(
    project_create: ProjectCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: uuid.UUID = Path(...),
) -> APIResponse:
    """从项目创建模板"""
    current_project = await get_current_project(current_user, project_id, db)

    if current_project.type != ProjectType.PROJECT:
        raise HTTPException(status_code=404, detail="Project not found")

    # only owner can do
    is_owner = await ProjectDAO.is_project_owner(current_project, current_user, db)
    if not is_owner:
        raise HTTPException(status_code=403, detail="No permission to create template from this project")

    project_create.type = ProjectType.TEMPLATE
    new_template = await ProjectDAO.create_project(project_create, db)
    await ProjectDAO.add_member(MemberCreateUpdate(permission=ProjectPermission.OWNER), new_template, current_user, db)
    await ChatDAO.create_chat_room(project_create.name, new_template.id, db)
    await ProjectDAO.copy_project(current_project, new_template, db)

    return APIResponse(code=200, data=ProjectID(project_id=new_template.id), msg="Template created")


@router.post("/{project_id:uuid}/copy_project", response_model=APIResponse)
async def copy_project(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: uuid.UUID = Path(...),
) -> APIResponse:
    """复制项目"""
    current_project = await get_current_project(current_user, project_id, db)

    if current_project.type != ProjectType.PROJECT:
        raise HTTPException(status_code=404, detail="Project not found")

    # only member can do
    is_member = await ProjectDAO.is_project_member(current_project, current_user, db)
    if not is_member:
        raise HTTPException(status_code=403, detail="No permission to copy this project")

    project_create = ProjectCreate(name=f"{current_project.name} Copy", type=ProjectType.PROJECT)
    new_project = await ProjectDAO.create_project(project_create, db)
    await ProjectDAO.add_member(MemberCreateUpdate(permission=ProjectPermission.OWNER), new_project, current_user, db)
    await ChatDAO.create_chat_room(current_project.name, new_project.id, db)
    await ProjectDAO.copy_project(current_project, new_project, db)

    return APIResponse(code=200, data=ProjectID(project_id=new_project.id), msg="Project copied")


@router.get("/", response_model=APIResponse[List[ProjectInfo]])
async def get_all_projects(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    type_data: ProjectTypeData | None = None,
) -> APIResponse[List[ProjectInfo]]:
    """获取当前用户参与的所有项目或模板"""
    if type_data is None:
        projects = await ProjectDAO.get_all_projects(current_user, db)
    else:
        projects = await ProjectDAO.get_all_projects(current_user, db, type=type_data.type)

    projects_info = []
    for project in projects:
        project_info = await ProjectDAO.get_project_info(project, db, user=current_user)
        projects_info.append(project_info)
    return APIResponse(code=200, data=projects_info, msg="success")


@router.get("/own/", response_model=APIResponse[List[ProjectInfo]])
async def get_own_projects(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse[List[ProjectInfo]]:
    """获取当前用户为owner的所有项目"""
    projects = await ProjectDAO.get_own_projects(current_user, db)

    projects_info = []
    for project in projects:
        project_info = await ProjectDAO.get_project_info(project, db, user=current_user)
        projects_info.append(project_info)
    return APIResponse(code=200, data=projects_info, msg="success")


@router.get("/shared/", response_model=APIResponse[List[ProjectInfo]])
async def get_shared_projects(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse[List[ProjectInfo]]:
    """获取当前用户被邀请参与的所有项目"""
    projects = await ProjectDAO.get_shared_projects(current_user, db)

    projects_info = []
    for project in projects:
        project_info = await ProjectDAO.get_project_info(project, db, user=current_user)
        projects_info.append(project_info)
    return APIResponse(code=200, data=projects_info, msg="success")


@router.get("/templates/", response_model=APIResponse[List[ProjectInfo]])
async def get_templates(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse[List[ProjectInfo]]:
    """获取所有公开的模板"""
    templates = await ProjectDAO.get_public_templates(db)

    templates_info = []
    for template in templates:
        template_info = await ProjectDAO.get_project_info(template, db, user=current_user)
        templates_info.append(template_info)
    return APIResponse(code=200, data=templates_info, msg="success")


@router.get("/favorite_templates/", response_model=APIResponse[List[ProjectInfo]])
async def get_favorite_templates(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse[List[ProjectInfo]]:
    """获取当前用户收藏的模板"""
    templates = await ProjectDAO.get_favorite_templates(current_user, db)

    templates_info = []
    for template in templates:
        template_info = await ProjectDAO.get_project_info(template, db, user=current_user)
        templates_info.append(template_info)
    return APIResponse(code=200, data=templates_info, msg="success")


@router.get("/{project_id:uuid}", response_model=APIResponse[ProjectInfo])
async def get_project(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: uuid.UUID = Path(...),
):
    """获取指定项目(模板)详情"""
    current_project = await get_current_project(current_user, project_id, db)

    project_info = await ProjectDAO.get_project_info(current_project, db, user=current_user)
    return APIResponse(code=200, data=project_info, msg="success")


@router.put("/{project_id:uuid}", response_model=APIResponse)
async def update_project(
    project_update: ProjectUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: uuid.UUID = Path(...),
) -> APIResponse:
    """更新项目信息"""
    current_project = await get_current_project(current_user, project_id, db)

    # only admin or owner can do
    is_admin = await ProjectDAO.is_project_admin(current_project, current_user, db)
    is_owner = await ProjectDAO.is_project_owner(current_project, current_user, db)
    if not is_admin and not is_owner:
        raise HTTPException(status_code=403, detail="No permission to update this project")

    updated_project = await ProjectDAO.update_project(current_project, project_update, db)
    if updated_project is None:
        raise HTTPException(status_code=400, detail="Failed to update project")

    # TODO 在Websocket中处理非用户成员访问公开模板
    # 若模板被设置为非公开，则删除所有NON_MEMBER成员
    is_template = current_project.type == ProjectType.TEMPLATE
    is_public = updated_project.is_public
    if is_template and not is_public:
        await ProjectDAO.remove_non_members(current_project, db)

    # 发送广播
    try:
        channel = get_project_channel_name(current_project.id)
        await project_general_manager.publish(
            channel,
            Message(
                client_id=str(current_user.id),
                scope=EventScope.PROJECT,
                action=ProjectAction.UPDATE_NAME,
                payload={"project_id": str(current_project.id), "name": updated_project.name},
            ).model_dump_json(),
        )
    except Exception as e:
        logger.error(f"Failed to broadcast project deletion: {str(e)}")

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

    # 向被删除的全部项目发送广播
    try:
        for project_id in project_ids:
            channel = get_project_channel_name(project_id)
            await project_general_manager.publish(
                channel,
                Message(
                    client_id=str(current_user.id),
                    scope=EventScope.PROJECT,
                    action=ProjectAction.DELETE_PROJECT,
                    payload={"project_id": str(project_id)},
                ).model_dump_json(),
            )
    except Exception as e:
        logger.error(f"Failed to broadcast project deletion: {str(e)}")

    return APIResponse(code=200, msg="Projects deleted")


@router.delete("/{project_id:uuid}", response_model=APIResponse)
async def delete_project(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: uuid.UUID = Path(...),
) -> APIResponse:
    """删除项目"""
    current_project = await get_current_project(current_user, project_id, db)

    # only owner can do
    is_owner = await ProjectDAO.is_project_owner(current_project, current_user, db)
    if not is_owner:
        raise HTTPException(status_code=403, detail="No permission to delete this project")

    await ProjectDAO.delete_project(current_project, db)

    # 发送广播
    try:
        channel = get_project_channel_name(current_project.id)
        await project_general_manager.publish(
            channel,
            Message(
                client_id=str(current_user.id),
                scope=EventScope.PROJECT,
                action=ProjectAction.DELETE_PROJECT,
                payload={"project_id": str(current_project.id)},
            ).model_dump_json(),
        )
    except Exception as e:
        logger.error(f"Failed to broadcast project deletion: {str(e)}")

    return APIResponse(code=200, msg="Project deleted")
