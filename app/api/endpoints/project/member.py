from typing import Annotated, List

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_project, get_current_user, get_db, get_target_user
from app.models.base import APIResponse
from app.models.project.project import (
    Project,
    ProjectPermission,
    MemberPermission,
    MemberInfo,
)
from app.models.user import User
from app.repositories.project.project import ProjectDAO

router = APIRouter()


@router.get("/", response_model=APIResponse[List[MemberInfo]])
async def get_members(
    current_user: Annotated[User, Depends(get_current_user)],
    current_project: Annotated[Project, Depends(get_current_project)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse[List[MemberInfo]]:
    """获取项目所有成员信息"""
    is_member = await ProjectDAO.is_project_member(current_project, current_user, db)
    if not is_member:
        raise HTTPException(status_code=403, detail="No permission to access this project")

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
    current_project: Annotated[Project, Depends(get_current_project)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse[MemberInfo]:
    """获取项目成员信息"""
    # 检查当前用户
    is_current_member = await ProjectDAO.is_project_member(current_project, current_user, db)
    if not is_current_member:
        raise HTTPException(status_code=403, detail="No permission to get member")

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
    current_project: Annotated[Project, Depends(get_current_project)],
    member_permission: MemberPermission,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse:
    """
    添加项目成员
    # TODO 发送邮件邀请
    """
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
    if permission == ProjectPermission.OWNER:
        raise HTTPException(status_code=400, detail="Cannot add owner")
    elif is_current_admin and permission == ProjectPermission.ADMIN:
        raise HTTPException(status_code=403, detail="No permission to add admins")

    await ProjectDAO.add_member(current_project, target_user, permission, db)
    return APIResponse(code=200, msg="Member added")


@router.delete("/{username:str}", response_model=APIResponse)
async def remove_member(
    target_user: Annotated[User, Depends(get_target_user)],
    current_user: Annotated[User, Depends(get_current_user)],
    current_project: Annotated[Project, Depends(get_current_project)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse:
    """移除项目成员"""
    is_current_owner = await ProjectDAO.is_project_owner(current_project, current_user, db)
    is_current_admin = await ProjectDAO.is_project_admin(current_project, current_user, db)
    is_current_member = await ProjectDAO.is_project_member(current_project, current_user, db)
    is_target_owner = await ProjectDAO.is_project_owner(current_project, target_user, db)
    is_target_admin = await ProjectDAO.is_project_admin(current_project, target_user, db)
    is_target_member = await ProjectDAO.is_project_member(current_project, target_user, db)

    # 检查当前用户
    if not is_current_member or target_user.id != current_user.id:
        if not is_current_admin and not is_current_owner:
            raise HTTPException(status_code=403, detail="No permission to remove members")
        elif is_target_admin and not is_current_owner:
            raise HTTPException(status_code=403, detail="No permission to remove admins")

    # 检查目标用户
    if is_target_owner:
        raise HTTPException(status_code=400, detail="Cannot remove the owner")
    elif not is_target_member:
        raise HTTPException(status_code=400, detail="User is not a member of the project")

    await ProjectDAO.remove_member(current_project, target_user, db)
    return APIResponse(code=200, msg="Member removed")


@router.put("/{username:str}", response_model=APIResponse)
async def update_member(
    target_user: Annotated[User, Depends(get_target_user)],
    current_user: Annotated[User, Depends(get_current_user)],
    current_project: Annotated[Project, Depends(get_current_project)],
    new_permission: MemberPermission,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse:
    """更新成员权限"""
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
    if new_permission == ProjectPermission.OWNER:
        raise HTTPException(status_code=400, detail="Cannot update to owner")
    elif is_current_admin and new_permission == ProjectPermission.ADMIN:
        raise HTTPException(status_code=403, detail="No permission update to admin")

    updated_member = await ProjectDAO.update_member(current_project, target_user, new_permission, db)
    if updated_member is None:
        return APIResponse(code=400, msg="Failed to update member")
    return APIResponse(code=200, msg="Member updated")


# 转移当前项目所有人
@router.put("/owner/{username:str}", response_model=APIResponse)
async def transfer_ownership(
    target_user: Annotated[User, Depends(get_target_user)],
    current_user: Annotated[User, Depends(get_current_user)],
    current_project: Annotated[Project, Depends(get_current_project)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse:
    """转移项目所有权"""
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
    updated_member = await ProjectDAO.update_member(current_project, target_user, ProjectPermission.OWNER, db)
    if updated_member is None:
        return APIResponse(code=400, msg="Failed to transfer ownership")
    await ProjectDAO.remove_member(current_project, current_user, db)
    return APIResponse(code=200, msg="Ownership transferred")
