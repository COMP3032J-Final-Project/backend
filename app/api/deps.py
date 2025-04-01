# 用于定义依赖项，可以在路由处理函数中通过依赖注入的方式使用，例如获取数据库会话、获取当前用户等
import uuid
from typing import AsyncGenerator, Annotated
from fastapi import Depends, HTTPException, status, Path
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.core.db import async_session
from app.models.project.file import File
from app.models.project.project import Project
from app.models.token import TokenPayload
from app.models.user import User
from app.repositories.project.file import FileDAO
from app.repositories.project.project import ProjectDAO
from app.repositories.user import UserDAO

# FastAPI提供的OAuth2密码模式的认证类，用于获取token
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_STR}/auth/login")


class TokenValidationException(Exception):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    数据库会话依赖
    """
    # 通过async_session()上下文管理器获取数据库会话
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def get_current_user(
    access_token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """
    获取当前用户
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # 解码token
    try:
        payload = jwt.decode(access_token, settings.SECRET_KEY, algorithms=["HS256"])
        token_data = TokenPayload(**payload)
    except JWTError:
        raise credentials_exception

    try:
        user_id = uuid.UUID(str(token_data.sub))
    except ValueError:
        raise credentials_exception

    user = await UserDAO.get_user_by_id(user_id, db)
    if not user or not user.is_active:
        raise credentials_exception
    return user


async def get_current_user_ws(websocket: WebSocket, db: Annotated[AsyncSession, Depends(get_db)]) -> User:
    """
    获取当前用户
    """
    try:
        token = websocket.query_params.get("access_token")
        if not token:
            raise TokenValidationException

        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        token_data = TokenPayload(**payload)
        user_id = uuid.UUID(str(token_data.sub))
        user = await UserDAO.get_user_by_id(user_id, db)
        if not user or not user.is_active:
            raise TokenValidationException
        return user
    except (
        TokenValidationException,
        JWTError,
        ValueError,
    ):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise WebSocketDisconnect(code=status.WS_1008_POLICY_VIOLATION, reason="Could not validate credentials")
    except WebSocketDisconnect:
        logger.info("WebSocket connection closed (expected on invalid token)")
        raise


async def get_target_user(
    username: Annotated[str, Path(...)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """通过用户名获取用户"""
    user = await UserDAO.get_user_by_username(username, db)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


async def get_current_project(
    project_id: Annotated[uuid.UUID, Path(..., description="The ID of the project")],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Project:
    # 验证项目ID
    project = await ProjectDAO.get_project_by_id(project_id, db)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    return project


async def get_current_file(
    file_id: Annotated[uuid.UUID, Path(...)],
    current_project: Annotated[Project, Depends(get_current_project)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> File:
    file = await FileDAO.get_file_by_id(file_id, db)
    if not file or file.project_id != current_project.id:
        raise HTTPException(status_code=404, detail="File not found")
    return file
