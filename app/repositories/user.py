# 用户DAO
import os
import uuid
from typing import Optional

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.r2client import r2client
from app.core.config import settings
from app.core.security import get_password_hash
from app.models.user import UserUpdate, User, UserRegister
from app.repositories.project.file import force_posix


class UserDAO:

    @staticmethod
    async def get_user_by_id(user_id: uuid.UUID, db: AsyncSession) -> Optional[User]:
        """
        通过用户ID获取用户
        """
        user = await db.get(User, user_id)
        if not user or not user.is_active:
            return None
        return user

    @staticmethod
    async def get_user_by_email(email: str, db: AsyncSession) -> Optional[User]:
        """
        通过邮箱获取用户
        """
        query = select(User).where(User.email == email)
        result = await db.execute(query)
        user = result.scalar_one_or_none()
        if not user or not user.is_active:
            return None
        return user

    @staticmethod
    async def get_user_by_username(username: str, db: AsyncSession) -> Optional[User]:
        """
        通过用户名获取用户
        """
        query = select(User).where(User.username == username)
        result = await db.execute(query)
        user = result.scalar_one_or_none()
        if not user or not user.is_active:
            return None
        return user

    @staticmethod
    async def create_user(db: AsyncSession, user_register: UserRegister, is_superuser: bool = False) -> User:
        """
        创建用户
        :param db: 数据库会话
        :param user_register: 用户注册信息
        :param is_superuser: 是否为管理员(默认为False)
        """
        user = User(
            email=user_register.email,
            username=user_register.username,
            hashed_password=get_password_hash(user_register.password),
            is_superuser=is_superuser,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def update_user(user: User, user_update: UserUpdate, db: AsyncSession) -> Optional[User]:
        """更新用户本人信息"""
        update_data = user_update.model_dump(exclude_unset=True, exclude_none=True)
        for field, value in update_data.items():
            setattr(user, field, value)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            return None
        await db.refresh(user)
        return user

    @staticmethod
    async def delete_user(
        user: User,
        db: AsyncSession,
    ) -> None:
        """假删除用户"""
        user.username = f"deleted_user_{user.id}"
        user.email = f"deleted_{user.id}@deleted.com"
        user.is_active = False
        await db.commit()

    @staticmethod
    def get_avatar_path(user_id: uuid.UUID) -> str:
        return force_posix(os.path.join("avatar", f"{user_id}"))

    @staticmethod
    async def get_avatar_url(user: User) -> str:
        """
        获取用户头像在R2中的URL
        """
        is_exist = await UserDAO.check_avatar_exist(user)
        if not is_exist:
            return ""

        try:
            return r2client.generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.R2_BUCKET, "Key": UserDAO.get_avatar_path(user.id)},
                ExpiresIn=3600,
            )
        except Exception as e:
            logger.error(e)
            raise

    @staticmethod
    async def update_avatar(user: User, is_default: bool) -> str:
        """
        更新用户头像
        """
        is_exist = await UserDAO.check_avatar_exist(user)
        # 若存在头像文件,删除
        if is_exist:
            try:
                r2client.delete_object(Bucket=settings.R2_BUCKET, Key=UserDAO.get_avatar_path(user.id))
            except Exception as e:
                logger.error(e)
                raise

        # 若选择默认头像,返回
        if is_default:
            return ""

        # 获取上传URL
        try:
            return r2client.generate_presigned_url(
                "put_object",
                Params={"Bucket": settings.R2_BUCKET, "Key": UserDAO.get_avatar_path(user.id)},
                ExpiresIn=3600,
            )
        except Exception as e:
            logger.error(e)
            raise

    @staticmethod
    async def check_avatar_exist(user: User) -> bool:
        """
        检查用户头像是否存在
        """
        try:
            r2client.head_object(Bucket=settings.R2_BUCKET, Key=UserDAO.get_avatar_path(user.id))
        except Exception:
            return False
        return True
