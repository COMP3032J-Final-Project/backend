# 认证DAO
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from jose import jwt, JWTError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette import status

from app.core.config import settings
from app.core.security import verify_password
from app.models.token import TokenBlacklist, TokenPayload
from app.models.user import User


class AuthDAO:
    """
    认证服务
    """

    @staticmethod
    async def authenticate(
            email: str,
            password: str,
            db: AsyncSession
    ) -> Optional[User]:
        """
        验证并获取用户
        :param email: 没错是邮箱
        :param password: 密码
        :param db: 数据库会话

        :return: 用户
        """
        query = select(User).where(User.email == email)
        result = await db.execute(query)
        user = result.scalar_one_or_none()

        if not user:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user

    @staticmethod
    def create_access_token(
            subject: str | uuid.UUID,
            expires_delta: Optional[timedelta] = None
    ) -> str:
        """
        创建访问令牌
        :param subject: 用户ID
        :param expires_delta: 有效期
        """
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(
                minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
            )

        payload = {
            "sub": str(subject),
            "exp": expire,
            "iat": datetime.utcnow(),
            "jti": str(uuid.uuid4()),
            "typ": "access",
        }
        encoded_jwt = jwt.encode(
            payload,
            settings.SECRET_KEY,
            algorithm="HS256"
        )
        return encoded_jwt

    @staticmethod
    def create_refresh_token(
            subject: str | uuid.UUID,
            expires_delta: Optional[timedelta] = None
    ) -> str:
        """
        创建刷新令牌
        :param subject: 用户ID
        :param expires_delta: 有效期
        """
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(
                minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES
            )

        to_encode = {
            "sub": str(subject),
            "exp": expire,
            "iat": datetime.utcnow(),
            "jti": str(uuid.uuid4()),
            "typ": "refresh",
        }
        encoded_jwt = jwt.encode(
            to_encode,
            settings.SECRET_KEY,
            algorithm="HS256"
        )
        return encoded_jwt

    @staticmethod
    async def is_token_blacklisted(
            jti: str,
            db: AsyncSession
    ):
        """
        检查令牌是否在黑名单
        jti: JWT ID
        db:
        """
        query = select(TokenBlacklist).where(TokenBlacklist.jti == jti)
        result = await db.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def add_token_to_blacklist(
            jti: str,
            exp: datetime,
            typ: str,
            db: AsyncSession
    ):
        """
        添加令牌到黑名单
        jti: JWT ID
        exp: 过期时间
        typ: 令牌类型
        db:
        """
        token_blacklist = TokenBlacklist(
            jti=jti,
            exp=exp,
            typ=typ,
        )
        db.add(token_blacklist)
        await db.commit()

    @staticmethod
    async def get_token_payload(
            token: str,
            expected_type: str,
            db: AsyncSession
    ) -> TokenPayload:
        """
        解码并验证 token
        :param token: 令牌
        :param expected_type: "access" 或 "refresh"
        :param db: 数据库会话
        :return: TokenPayload 实例
        """
        try:
            payload = jwt.decode(
                token,
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

        # 检查令牌类型
        if token_data.typ != expected_type:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid {expected_type} token",
            )
        # 检查令牌是否在黑名单中
        if await AuthDAO.is_token_blacklisted(token_data.jti, db):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
            )
        return token_data
