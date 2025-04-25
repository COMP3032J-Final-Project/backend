# User 相关的 API 路由
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user, get_target_user_by_id, get_target_user_by_name
from app.core.security import verify_password, get_password_hash
from app.models.base import APIResponse
from app.models.user import User, UserVerifyPwd, UserUpdatePwd, UserUpdateAvatar
from app.models.user import UserInfo, UserRegister, UserUpdate
from app.repositories.project.file import FileDAO
from app.repositories.project.project import ProjectDAO
from app.repositories.user import UserDAO

router = APIRouter()


@router.post("/register", response_model=APIResponse[UserInfo])
async def register(user_register: UserRegister, db: Annotated[AsyncSession, Depends(get_db)]) -> APIResponse[UserInfo]:
    """
    注册新用户
    """
    # 检查邮箱是否已存在
    existing_user_by_email = await UserDAO.get_user_by_email(user_register.email, db)
    if existing_user_by_email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    # 检查用户名是否已存在
    existing_user_by_username = await UserDAO.get_user_by_username(user_register.username, db)
    if existing_user_by_username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already taken")

    # 创建新用户
    new_user = await UserDAO.create_user(
        db,
        user_register,
    )
    user_info = UserInfo.model_validate(new_user)
    return APIResponse[UserInfo](code=200, data=user_info, msg="success")


@router.get("/me", response_model=APIResponse[UserInfo])
async def get_me(current_user: Annotated[User, Depends(get_current_user)]) -> APIResponse[UserInfo]:
    """
    获取当前用户信息
    """
    user_info = UserInfo.model_validate(current_user)
    return APIResponse[UserInfo](code=200, data=user_info, msg="success")


@router.put("/me", response_model=APIResponse[UserInfo])
async def update_me(
    user_update_me: UserUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse:
    """
    更新当前用户信息
    """

    updated_user = await UserDAO.update_user(current_user, user_update_me, db)
    if updated_user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username or email already taken")
    user_info = UserInfo.model_validate(updated_user)
    return APIResponse(code=200, data=user_info, msg="User updated")


@router.delete("/me", response_model=APIResponse)
async def delete_user(
    current_user: Annotated[User, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db)]
) -> APIResponse:
    """
    删除当前用户
    """
    # await db.delete(current_user)
    # await db.commit()
    # 检查用户是否有项目
    projects = await ProjectDAO.get_projects(current_user, db)
    if projects:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User has projects, cannot be deleted")

    await UserDAO.delete_user(current_user, db)
    return APIResponse(code=200, msg="User deleted")


@router.post("/pwd/verify", response_model=APIResponse)
async def verify_pwd(
    user_verify_pwd: UserVerifyPwd, current_user: Annotated[User, Depends(get_current_user)]
) -> APIResponse:
    """
    验证密码
    """
    plain_password = user_verify_pwd.password
    if not verify_password(plain_password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect password")
    return APIResponse(code=200, msg="Password verified")


@router.put("/pwd/update", response_model=APIResponse)
async def update_pwd(
    user_update_pwd: UserUpdatePwd,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse:
    """
    更新密码(更新后暂无需重新登录)
    """
    new_password = user_update_pwd.new_password
    current_user.hashed_password = get_password_hash(new_password)
    await db.commit()
    return APIResponse(code=200, msg="Password updated")


@router.get("/{user_id:uuid}", response_model=APIResponse[UserInfo])
async def get_user_by_id(
    target_user: Annotated[User, Depends(get_target_user_by_id)],
) -> APIResponse[UserInfo]:
    """
    通过用户ID获取用户信息
    """
    user_info = UserInfo.model_validate(target_user)
    return APIResponse[UserInfo](code=200, data=user_info, msg="success")


@router.get("/avatar/", response_model=APIResponse)
async def get_avatar(
    current_user: Annotated[User, Depends(get_current_user)],
) -> APIResponse:
    """
    获取用户头像
    """
    avatar_url = await UserDAO.get_avatar_url(current_user)
    return APIResponse(code=200, data=avatar_url, msg="success")


@router.put("/avatar/", response_model=APIResponse)
async def update_avatar(
    user_update_avatar: UserUpdateAvatar,
    current_user: Annotated[User, Depends(get_current_user)],
) -> APIResponse:
    """
    更新用户头像
    """
    is_default = user_update_avatar.is_default

    avatar_url = await UserDAO.update_avatar(current_user, is_default)
    return APIResponse(code=200, data=avatar_url, msg="success")
