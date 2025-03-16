from typing import Annotated, List

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_project, get_current_user, get_db, get_target_user
from app.models.base import APIResponse
from app.models.project.project import Project, ProjectPermission, MemberPermission, MemberInfo
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
        raise HTTPException(
            status_code=403, detail="No permission to access this project"
        )

    members = await ProjectDAO.get_members(current_project, db)
    members_info = []
    for member in members:
        member_info = MemberInfo(
            username=member.username,
            email=member.email,
            permission=await ProjectDAO.get_project_permission(current_project, member, db)
        )
        members_info.append(member_info)
    return APIResponse(code=200, data=members_info, msg="success")


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
    # 检查目标用户
    is_target_member = await ProjectDAO.is_project_member(current_project, target_user, db)
    if is_target_member:
        raise HTTPException(status_code=400, detail="User is already a member of the project")

    # 检查当前用户
    is_current_admin = await ProjectDAO.is_project_admin(current_project, current_user, db)
    is_current_owner = await ProjectDAO.is_project_owner(current_project, current_user)
    if not is_current_admin and not is_current_owner:
        raise HTTPException(status_code=403, detail="No permission to add members")

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
    # 检查目标用户
    is_target_owner = await ProjectDAO.is_project_owner(current_project, target_user)
    is_target_admin = await ProjectDAO.is_project_admin(current_project, target_user, db)
    is_target_member = await ProjectDAO.is_project_member(current_project, target_user, db)
    if is_target_owner:
        raise HTTPException(status_code=400, detail="Cannot remove the owner")
    elif not is_target_member:
        raise HTTPException(status_code=400, detail="User is not a member of the project")

    # 若不是移除自己，检查当前用户权限
    if target_user.id != current_user.id:
        is_current_admin = await ProjectDAO.is_project_admin(current_project, current_user, db)
        is_current_owner = await ProjectDAO.is_project_owner(current_project, current_user)
        if not is_current_admin and not is_current_owner:
            raise HTTPException(status_code=403, detail="No permission to remove members")
        elif is_target_admin and not is_current_owner:
            raise HTTPException(status_code=403, detail="No permission to remove admins")

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
    # 检查目标用户
    is_target_owner = await ProjectDAO.is_project_owner(current_project, target_user)
    is_target_admin = await ProjectDAO.is_project_admin(current_project, target_user, db)
    is_target_member = await ProjectDAO.is_project_member(current_project, target_user, db)
    if is_target_owner:
        raise HTTPException(status_code=400, detail="Cannot update the owner's permission")
    elif not is_target_member:
        raise HTTPException(status_code=400, detail="User is not a member of the project")

    # 检查当前用户
    is_current_admin = await ProjectDAO.is_project_admin(current_project, current_user, db)
    is_current_owner = await ProjectDAO.is_project_owner(current_project, current_user)
    if not is_current_admin and not is_current_owner:
        raise HTTPException(status_code=403, detail="No permission to update members")
    elif is_target_admin and not is_current_owner:
        raise HTTPException(status_code=403, detail="No permission to update admins")

    new_permission = ProjectPermission(new_permission.permission)
    await ProjectDAO.update_member(current_project, target_user, new_permission, db)
    return APIResponse(code=200, msg="Member updated")
