# 用于实现 User 相关的 API 路由
import uuid
from datetime import timedelta
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user
from app.core.config import settings
from app.models.token import Token, TokenPayload
from app.models.user import UserBase, UserRegister, UserUpdateMe
from app.models.user import User
from app.services.auth import AuthService

router = APIRouter()


@router.post("/login", response_model=Token)
async def login(
        form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
        db: Annotated[AsyncSession, Depends(get_db)]
) -> Token:
    """
    OAuth2 compatible token login
    """
    user = await AuthService.authenticate(
        form_data.username,
        form_data.password,
        db
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    elif not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )

    return Token(
        access_token=AuthService.create_access_token(
            user.id,
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        ),
        refresh_token=AuthService.create_refresh_token(
            user.id,
            expires_delta=timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)
        ),
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )


@router.post("/register", response_model=UserBase)
async def register(
        user_in: UserRegister,
        db: Annotated[AsyncSession, Depends(get_db)]
) -> User:
    """
    注册新用户
    """
    return await AuthService.register_user(user_in, db)


@router.post("/refresh", response_model=Token)
async def refresh(
        refresh_token: str,
        db: Annotated[AsyncSession, Depends(get_db)]
) -> Token:
    """
    使用刷新令牌获取新的访问令牌(在访问令牌过期时使用)
    """
    try:
        # 解码刷新令牌
        payload = jwt.decode(
            refresh_token,
            settings.SECRET_KEY,
            algorithms=["HS256"]
        )
        token_data = TokenPayload(**payload)

        # 检查令牌
        if token_data.typ != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )
        if await AuthService.is_token_blacklisted(token_data.jti, db):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
            )

        # 获取用户
        user_id = uuid.UUID(str(token_data.sub))
        user = await db.get(User, user_id)
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )

        # 添加旧令牌到黑名单
        await AuthService.add_token_to_blacklist(
            token_data.jti,
            token_data.exp,
            token_data.typ,
            db
        )

        return Token(
            access_token=AuthService.create_access_token(
                user.id,
                expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
            ),
            refresh_token=AuthService.create_refresh_token(
                user.id,
                expires_delta=timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)
            ),
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )


@router.get("/me", response_model=UserBase)
async def read_users_me(
        current_user: Annotated[User, Depends(get_current_user)]
) -> User:
    """
    获取当前用户信息
    """
    return current_user


@router.put("/me", response_model=UserBase)
async def update_user_me(
        user_update_me: UserUpdateMe,
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[AsyncSession, Depends(get_db)]
) -> User:
    """
    更新当前用户信息
    """
    user = await AuthService.update_user_me(
        uuid.UUID(str(current_user.id)),
        user_update_me,
        db
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return user
