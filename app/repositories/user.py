# 用户DAO
import uuid
from typing import Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import get_password_hash
from app.models.user import UserUpdate, User, UserRegister


class UserDAO:

    @staticmethod
    async def get_user_by_id(
            user_id: uuid.UUID,
            db: AsyncSession
    ) -> Optional[User]:
        """
        通过用户ID获取用户
        """
        return await db.get(User, user_id)

    @staticmethod
    async def get_user_by_email(
            email: str,
            db: AsyncSession
    ) -> Optional[User]:
        """
        通过邮箱获取用户
        """
        query = select(User).where(User.email == email)
        result = await db.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_user_by_username(
            username: str,
            db: AsyncSession
    ) -> Optional[User]:
        """
        通过用户名获取用户
        """
        query = select(User).where(User.username == username)
        result = await db.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def create_user(
            user_register: UserRegister,
            db: AsyncSession
    ) -> User:
        """
        创建用户
        """
        user = User(
            email=user_register.email,
            username=user_register.username,
            hashed_password=get_password_hash(user_register.password),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def update_user(
            user_id: uuid.UUID,
            user_update: UserUpdate,
            db: AsyncSession
    ) -> Optional[User]:
        """更新用户本人信息"""
        user = await UserDAO.get_user_by_id(user_id, db)
        if not user:
            return None

        update_data = user_update.model_dump(exclude_unset=True)  # 过滤掉未设置的字段
        for field, value in update_data.items():
            setattr(user, field, value)

        await db.commit()
        await db.refresh(user)
        return user
