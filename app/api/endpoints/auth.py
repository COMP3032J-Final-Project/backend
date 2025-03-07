# 认证相关的 API 路由
import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from app.api.deps import get_db, oauth2_scheme
from app.core.config import settings
from app.models.base import Message
from app.models.token import Token, RefreshToken, TokenPayload
from app.models.user import User
from app.repositories.auth import AuthDAO

router = APIRouter()


# OAuth2密码流登录
@router.post("/login", response_model=Token)
async def login(
        form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
        db: Annotated[AsyncSession, Depends(get_db)]
) -> Token:
    """
    OAuth2 compatible token login
    """
    user = await AuthDAO.authenticate(
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
        access_token=AuthDAO.create_access_token(
            user.id,
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        ),
        refresh_token=AuthDAO.create_refresh_token(
            user.id,
            expires_delta=timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)
        ),
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )


@router.post("/refresh", response_model=Token)
async def refresh(
        refresh_token: RefreshToken,
        db: Annotated[AsyncSession, Depends(get_db)]
) -> Token:
    """
    使用刷新令牌获取新的访问令牌(在访问令牌过期时使用)
    """
    token_data = await AuthDAO.get_token_payload(
        refresh_token.refresh_token,
        "refresh",
        db
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
    await AuthDAO.add_token_to_blacklist(
        token_data.jti,
        token_data.exp,
        token_data.typ,
        db
    )

    return Token(
        access_token=AuthDAO.create_access_token(
            user.id,
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        ),
        refresh_token=AuthDAO.create_refresh_token(
            user.id,
            expires_delta=timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)
        ),
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )


@router.post("/logout", response_model=Message)
async def logout(
        access_token: Annotated[str, Depends(oauth2_scheme)],
        refresh_token: RefreshToken,
        db: Annotated[AsyncSession, Depends(get_db)]
) -> Message:
    """
    登出(将访问令牌加入黑名单)
    """
    # 获取access_token
    access_token_data = await AuthDAO.get_token_payload(
        access_token,
        "access",
        db
    )

    # 获取refresh_token
    refresh_token_data = await AuthDAO.get_token_payload(
        refresh_token.refresh_token,
        "refresh",
        db
    )

    # 验证access_token和refresh_token是否匹配
    if access_token_data.sub != refresh_token_data.sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token and refresh token do not match"
        )

    await AuthDAO.add_token_to_blacklist(
        access_token_data.jti,
        access_token_data.exp,
        access_token_data.typ,
        db
    )

    await AuthDAO.add_token_to_blacklist(
        refresh_token_data.jti,
        refresh_token_data.exp,
        refresh_token_data.typ,
        db
    )

    return Message(message="Logged out")
