# 用于用户认证
import uuid
from datetime import datetime, timedelta
from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from jose import jwt

from app.core.config import settings
from app.core.security import verify_password, get_password_hash
from app.models.token import TokenBlacklist
from app.models.user import User, UserRegister, UserUpdateMe


class AuthService:
    """认证服务"""

    @staticmethod
    async def authenticate(
            identifier: str,
            password: str,
            db: AsyncSession
    ) -> Optional[User]:
        """
        验证并获取用户
        :param identifier: 用户名或邮箱
        :param password: 密码
        :param db: 数据库会话

        :return: 用户
        """
        query = select(User).where((User.email == identifier) | (User.username == identifier))
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
        """
        token_blacklist = TokenBlacklist(
            jti=jti,
            exp=exp,
            typ=typ,
        )
        db.add(token_blacklist)
        await db.commit()

    @staticmethod
    async def get_user_by_email(
            email: str,
            db: AsyncSession
    ) -> Optional[User]:
        """通过邮箱获取用户"""
        query = select(User).where(User.email == email)
        result = await db.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_user_by_username(
            username: str,
            db: AsyncSession
    ) -> Optional[User]:
        """通过用户名获取用户"""
        query = select(User).where(User.username == username)
        result = await db.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def register_user(
            user_register: UserRegister,
            db: AsyncSession
    ) -> User:
        """注册用户"""
        # 检查邮箱是否已存在
        existing_user_by_email = await AuthService.get_user_by_email(
            user_register.email,
            db
        )
        if existing_user_by_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )

        # 检查用户名是否已存在
        existing_user_by_username = await AuthService.get_user_by_username(
            user_register.username,
            db
        )
        if existing_user_by_username:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already taken"
            )

        # 创建新用户
        db_user = User(
            email=user_register.email,
            username=user_register.username,
            hashed_password=get_password_hash(user_register.password),
        )
        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)
        return db_user

    @staticmethod
    async def update_user_me(
            user_id: uuid.UUID,
            user_update_me: UserUpdateMe,
            db: AsyncSession
    ) -> Optional[User]:
        """更新用户本人信息"""
        # 获取用户
        user = await db.get(User, user_id)
        if not user:
            return None

        # TODO 添加密码更新
        # if "password" in update_data:
        #     update_data["hashed_password"] = get_password_hash(
        #         update_data.pop("password")
        #     )
        update_data = user_update_me.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(user, field, value)

        await db.commit()
        await db.refresh(user)
        return user
