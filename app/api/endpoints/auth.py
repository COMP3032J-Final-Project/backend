# 认证相关的 API 路由
import uuid

from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import OAuth2PasswordRequestForm
from jose import jwt, JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from app.api.deps import get_db
from app.models.token import Token, RefreshToken, TokenPayload
from app.models.user import User
from app.repositories.auth import AuthDAO
from app.core.config import settings
from typing import Annotated
from datetime import timedelta

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
        token_data: RefreshToken,
        db: Annotated[AsyncSession, Depends(get_db)]
) -> Token:
    """
    使用刷新令牌获取新的访问令牌(在访问令牌过期时使用)
    """
    token_data = token_data.refresh_token
    # 解码刷新令牌
    try:
        payload = jwt.decode(
            token_data,
            settings.SECRET_KEY,
            algorithms=["HS256"]
        )
        token_data = TokenPayload(**payload)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 检查令牌
    if token_data.typ != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )
    if await AuthDAO.is_token_blacklisted(token_data.jti, db):
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
