from typing import Annotated, List
import uuid

from fastapi import APIRouter, HTTPException, Depends, Path
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_project, get_current_user, get_db, get_target_user
from app.api.endpoints.project.websocket_handlers import get_project_channel_name
from app.models.base import APIResponse
from app.models.project.project import (
    MemberCreateUpdate,
    ProjectPermission,
    ProjectPermissionData,
    MemberInfo,
    ProjectType,
)
from app.models.project.websocket import EventScope, MemberAction, Message
from app.models.user import User
from app.repositories.project.project import ProjectDAO
from app.api.endpoints.project.websocket_handlers import project_general_manager, get_project_channel_name

router = APIRouter()


@router.get("/", response_model=APIResponse[List[MemberInfo]])
async def get_members(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: uuid.UUID = Path(...),
) -> APIResponse[List[MemberInfo]]:
    """获取项目所有成员信息"""
    current_project = await get_current_project(current_user, project_id, db)

    members = await ProjectDAO.get_members(current_project, db)
    members_info = []
    for member in members:
        if member.is_active:
            member_info = MemberInfo(
                user_id=member.id,
                username=member.username,
                email=member.email,
                permission=await ProjectDAO.get_project_permission(current_project, member, db),
            )
            members_info.append(member_info)
        else:
            raise HTTPException(status_code=400, detail=f"Member {member.username} is inactive")
    return APIResponse(code=200, data=members_info, msg="success")


@router.get("/{username:str}", response_model=APIResponse[MemberInfo])
async def get_member(
    target_user: Annotated[User, Depends(get_target_user)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: uuid.UUID = Path(...),
) -> APIResponse[MemberInfo]:
    """获取项目成员信息"""
    current_project = await get_current_project(current_user, project_id, db)

    # 检查目标用户
    is_target_member = await ProjectDAO.is_project_member(current_project, target_user, db)
    if not is_target_member:
        raise HTTPException(status_code=404, detail="Member not found")

    member_info = MemberInfo(
        user_id=target_user.id,
        username=target_user.username,
        email=target_user.email,
        permission=await ProjectDAO.get_project_permission(current_project, target_user, db),
    )
    return APIResponse(code=200, data=member_info, msg="success")


@router.post("/{username:str}", response_model=APIResponse)
async def add_member(
    target_user: Annotated[User, Depends(get_target_user)],
    current_user: Annotated[User, Depends(get_current_user)],
    member_permission: ProjectPermissionData,
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: uuid.UUID = Path(...),
) -> APIResponse:
    """
    添加项目成员
    # TODO 发送邮件邀请
    """
    current_project = await get_current_project(current_user, project_id, db)

    is_current_owner = await ProjectDAO.is_project_owner(current_project, current_user, db)
    is_current_admin = await ProjectDAO.is_project_admin(current_project, current_user, db)
    is_target_member = await ProjectDAO.is_project_member(current_project, target_user, db)

    # 检查当前用户
    if not is_current_admin and not is_current_owner:
        raise HTTPException(status_code=403, detail="No permission to add members")

    # 检查目标用户
    if is_target_member:
        raise HTTPException(status_code=400, detail="User is already a member of the project")

    # 检查权限
    permission = ProjectPermission(member_permission.permission)
    if permission == ProjectPermission.OWNER or permission == ProjectPermission.NON_MEMBER:
        raise HTTPException(status_code=400, detail="Invalid permission")
    elif is_current_admin and permission == ProjectPermission.ADMIN:
        raise HTTPException(status_code=403, detail="No permission to add admins")

    old_permission = await ProjectDAO.get_project_permission(current_project, target_user, db)
    if old_permission == ProjectPermission.NON_MEMBER:
        await ProjectDAO.update_member(current_project, target_user, MemberCreateUpdate(permission=permission), db)
    else:
        await ProjectDAO.add_member(MemberCreateUpdate(permission=permission), current_project, target_user, db)

    # 发送广播
    try:
        channel = get_project_channel_name(current_project.id)

        member_info = MemberInfo(
            user_id=target_user.id,
            username=target_user.username,
            email=target_user.email,
            permission=permission,
        )
        await project_general_manager.publish(
            channel,
            Message(
                client_id=str(current_user.id),
                scope=EventScope.MEMBER,
                action=MemberAction.ADD_MEMBER,
                payload=member_info.model_dump(),
            ).model_dump_json(),
        )
    except Exception as e:
        logger.error(f"Failed to broadcast add member: {str(e)}")

    return APIResponse(code=200, msg="Member added")


@router.delete("/{username:str}", response_model=APIResponse)
async def remove_member(
    target_user: Annotated[User, Depends(get_target_user)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: uuid.UUID = Path(...),
) -> APIResponse:
    """移除项目成员"""
    current_project = await get_current_project(current_user, project_id, db)

    is_current_owner = await ProjectDAO.is_project_owner(current_project, current_user, db)
    is_current_admin = await ProjectDAO.is_project_admin(current_project, current_user, db)
    is_target_owner = await ProjectDAO.is_project_owner(current_project, target_user, db)
    is_target_admin = await ProjectDAO.is_project_admin(current_project, target_user, db)
    is_target_member = await ProjectDAO.is_project_member(current_project, target_user, db)

    # 检查当前用户
    if not is_current_admin and not is_current_owner:
        raise HTTPException(status_code=403, detail="No permission to remove members")
    elif is_target_admin and is_current_admin:
        raise HTTPException(status_code=403, detail="No permission to remove admins")

    # 检查目标用户
    if is_target_owner:
        raise HTTPException(status_code=400, detail="Cannot remove the owner")
    elif not is_target_member:
        raise HTTPException(status_code=400, detail="User is not a member of the project")

    await ProjectDAO.remove_member(current_project, target_user, db)

    # 发送广播
    try:
        channel = get_project_channel_name(current_project.id)

        member_info = MemberInfo(
            user_id=target_user.id,
            username=target_user.username,
            email=target_user.email,
        )
        await project_general_manager.publish(
            channel,
            Message(
                client_id=str(current_user.id),
                scope=EventScope.MEMBER,
                action=MemberAction.REMOVE_MEMBER,
                payload=member_info.model_dump(),
            ).model_dump_json(),
        )
    except Exception as e:
        logger.error(f"Failed to broadcast remove member: {str(e)}")

    return APIResponse(code=200, msg="Member removed")


@router.put("/{username:str}", response_model=APIResponse)
async def update_member(
    target_user: Annotated[User, Depends(get_target_user)],
    current_user: Annotated[User, Depends(get_current_user)],
    new_permission: ProjectPermissionData,
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: uuid.UUID = Path(...),
) -> APIResponse:
    """更新成员权限"""
    current_project = await get_current_project(current_user, project_id, db)

    is_current_admin = await ProjectDAO.is_project_admin(current_project, current_user, db)
    is_current_owner = await ProjectDAO.is_project_owner(current_project, current_user, db)
    is_target_owner = await ProjectDAO.is_project_owner(current_project, target_user, db)
    is_target_admin = await ProjectDAO.is_project_admin(current_project, target_user, db)
    is_target_member = await ProjectDAO.is_project_member(current_project, target_user, db)

    # 检查当前用户
    if not is_current_admin and not is_current_owner:
        raise HTTPException(status_code=403, detail="No permission to update members")
    elif is_target_admin and not is_current_owner:
        raise HTTPException(status_code=403, detail="No permission to update admins")

    # 检查目标用户
    if is_target_owner:
        raise HTTPException(status_code=400, detail="Cannot update the owner's permission")
    elif not is_target_member:
        raise HTTPException(status_code=400, detail="User is not a member of the project")

    # 检查权限
    new_permission = ProjectPermission(new_permission.permission)
    if new_permission == ProjectPermission.OWNER or new_permission == ProjectPermission.NON_MEMBER:
        raise HTTPException(status_code=400, detail="Invalid permission")
    elif is_current_admin and new_permission == ProjectPermission.ADMIN:
        raise HTTPException(status_code=403, detail="No permission update to admin")

    updated_member = await ProjectDAO.update_member(
        current_project, target_user, MemberCreateUpdate(permission=new_permission), db
    )
    if updated_member is None:
        return APIResponse(code=400, msg="Failed to update member")

    # 发送广播
    try:
        channel = get_project_channel_name(current_project.id)

        member_info = MemberInfo(
            user_id=target_user.id,
            username=target_user.username,
            email=target_user.email,
            permission=updated_member.permission,
        )
        await project_general_manager.publish(
            channel,
            Message(
                client_id=str(current_user.id),
                scope=EventScope.MEMBER,
                action=MemberAction.UPDATE_MEMBER,
                payload=member_info.model_dump(),
            ).model_dump_json(),
        )
    except Exception as e:
        logger.error(f"Failed to broadcast update member: {str(e)}")

    return APIResponse(code=200, msg="Member updated")


@router.put("/owner/{username:str}", response_model=APIResponse)
async def transfer_ownership(
    target_user: Annotated[User, Depends(get_target_user)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: uuid.UUID = Path(...),
) -> APIResponse:
    """转移项目所有权"""
    current_project = await get_current_project(current_user, project_id, db)

    is_current_owner = await ProjectDAO.is_project_owner(current_project, current_user, db)
    is_target_member = await ProjectDAO.is_project_member(current_project, target_user, db)

    # 检查当前用户
    if not is_current_owner:
        raise HTTPException(status_code=403, detail="No permission to transfer ownership")
    elif target_user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot transfer ownership to yourself")

    # 检查目标用户
    if not is_target_member:
        raise HTTPException(status_code=400, detail="User is not a member of the project")

    # 将目标用户的权限设置为所有者
    updated_member = await ProjectDAO.update_member(
        current_project, target_user, MemberCreateUpdate(permission=ProjectPermission.OWNER), db
    )
    if updated_member is None:
        return APIResponse(code=400, msg="Failed to transfer ownership")
    await ProjectDAO.remove_member(current_project, current_user, db)

    # 发送广播
    try:
        channel = get_project_channel_name(current_project.id)

        old_owner_info = MemberInfo(
            user_id=current_user.id,
            username=current_user.username,
            email=current_user.email,
        )
        new_owner_info = MemberInfo(
            user_id=target_user.id,
            username=target_user.username,
            email=target_user.email,
            permission=ProjectPermission.OWNER,
        )

        await project_general_manager.publish(
            channel,
            Message(
                client_id=str(current_user.id),
                scope=EventScope.MEMBER,
                action=MemberAction.TRANSFER_OWNERSHIP,
                payload={
                    "old_owner": old_owner_info.model_dump(),
                    "new_owner": new_owner_info.model_dump(),
                },
            ).model_dump_json(),
        )
    except Exception as e:
        logger.error(f"Failed to broadcast transfer ownership: {str(e)}")
    return APIResponse(code=200, msg="Ownership transferred")


@router.put("/favorite_template/", response_model=APIResponse)
async def favorite_template(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: uuid.UUID = Path(...),
) -> APIResponse:
    """收藏或取消收藏模板"""
    current_template = await get_current_project(current_user, project_id, db)

    is_template = current_template.type == ProjectType.TEMPLATE
    if not is_template:
        raise HTTPException(status_code=400, detail="Template not found")

    # 检查权限
    is_public = current_template.is_public
    is_member = await ProjectDAO.is_project_member(current_template, current_user, db)
    is_non_member = await ProjectDAO.is_non_member(current_template, current_user, db)
    if not is_member and not is_public:
        # 非成员且非公开，无权限收藏
        raise HTTPException(status_code=403, detail="No permission to favorite this template")
    elif is_member or is_non_member:
        # 成员或非成员曾收藏过，更新收藏状态
        is_favorite = await ProjectDAO.is_template_favorite(current_template, current_user, db)
        favorite_user = await ProjectDAO.update_member(
            current_template,
            current_user,
            MemberCreateUpdate(is_favorite=not is_favorite),
            db,
        )
    else:
        # 非成员且未收藏，添加收藏
        favorite_user = MemberCreateUpdate(permission=ProjectPermission.NON_MEMBER, is_favorite=True)
        await ProjectDAO.add_member(favorite_user, current_template, current_user, db)

    return APIResponse(code=200, data=favorite_user.is_favorite, msg="success")
