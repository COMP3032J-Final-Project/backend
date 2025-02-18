# 用于定义依赖项，可以在路由处理函数中通过依赖注入的方式使用，例如获取数据库会话、获取当前用户等
from typing import AsyncGenerator, Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.db.session import async_session
from app.schemas.token import TokenPayload
from app.models.user import User

# FastAPI提供的OAuth2密码模式的认证类，用于获取token
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login"
)


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
        token: Annotated[str, Depends(oauth2_scheme)],
        db: Annotated[AsyncSession, Depends(get_db)]) -> User:
    """
    获取当前用户
    """
    # 创建一个HTTP异常，用于在验证失败时返回
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # JSON Web Token，一种基于JSON的开放标准（RFC 7519），用于在网络上传输声明。
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=["HS256"]
        )
        token_data = TokenPayload(**payload)  # **是解包操作符，将字典解包为关键字参数
    except JWTError:
        raise credentials_exception

    user = await db.get(User, token_data.sub)  # 获取指定主键的user, await用法是等待异步操作完成
    if user is None:
        raise credentials_exception
    return user
