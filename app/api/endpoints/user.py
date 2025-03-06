# User 相关的 API 路由
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user
from app.core.security import verify_password, get_password_hash
from app.models.base import Message
from app.models.user import User, UserVerifyPwd, UserUpdatePwd
from app.models.user import UserBase, UserRegister, UserUpdate
from app.repositories.user import UserDAO

router = APIRouter()


@router.post("/register", response_model=UserBase)
async def register(
        user_register: UserRegister,
        db: Annotated[AsyncSession, Depends(get_db)]
) -> User:
    """
    注册新用户
    """
    # 检查邮箱是否已存在
    existing_user_by_email = await UserDAO.get_user_by_email(
        user_register.email,
        db
    )
    if existing_user_by_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # 检查用户名是否已存在
    existing_user_by_username = await UserDAO.get_user_by_username(
        user_register.username,
        db
    )
    if existing_user_by_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken"
        )

    # 创建新用户
    new_user = await UserDAO.create_user(
        user_register,
        db
    )
    return new_user


@router.get("/me", response_model=UserBase)
async def read_me(
        current_user: Annotated[User, Depends(get_current_user)]
) -> User:
    """
    获取当前用户信息
    """
    return current_user


@router.put("/me", response_model=Message)
async def update_user(
        user_update_me: UserUpdate,
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[AsyncSession, Depends(get_db)]
) -> Message:
    """
    更新当前用户信息
    """
    user = await UserDAO.update_user(
        uuid.UUID(str(current_user.id)),
        user_update_me,
        db
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return Message(message="User updated")


@router.post("/pwd/verify", response_model=Message)
async def verify_pwd(
        user_verify_pwd: UserVerifyPwd,
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[AsyncSession, Depends(get_db)]
) -> Message:
    """
    验证密码
    """
    user = await UserDAO.get_user_by_id(
        uuid.UUID(str(current_user.id)),
        db
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    plain_password = user_verify_pwd.password
    if not verify_password(plain_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect password"
        )
    return Message(message="Password verified")


@router.put("/pwd/update", response_model=Message)
async def update_pwd(
        user_update_pwd: UserUpdatePwd,
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[AsyncSession, Depends(get_db)]
) -> Message:
    """
    更新密码(更新后暂无需重新登录)
    """
    user_id = uuid.UUID(str(current_user.id))
    user = await UserDAO.get_user_by_id(user_id, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    new_password = user_update_pwd.new_password
    user.hashed_password = get_password_hash(new_password)
    await db.commit()
    return Message(message="Password updated")
