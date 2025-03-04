# 用于实现 User 相关模型
import uuid
from datetime import datetime
from pydantic import EmailStr, ConfigDict
from sqlmodel import Field

from app.models.base import Base


class UserBase(Base):
    """
    用户基础模型，定义用户公共字段
    """
    username: str = Field(
        ...,  # 必填字段
        min_length=3,
        max_length=50,
        sa_column_kwargs={"unique": True, "index": True, "nullable": False},
        description="用户名"
    )
    email: EmailStr = Field(
        ...,
        max_length=254,
        sa_column_kwargs={"unique": True, "index": True, "nullable": False},
        description="电子邮件"
    )
    is_active: bool = Field(
        default=True,
        description="是否激活"
    )
    is_superuser: bool = Field(
        default=False,
        description="是否为超级用户"
    )

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "username": "abc",
                "email": "abc@example.com",
                "is_active": True,
                "is_superuser": False
            }
        }
    )


class UserCreate(UserBase):
    """
    创建用户模型，用于管理员创建用户
    """
    password: str = Field(..., min_length=8, max_length=40)


class UserRegister(Base):
    """
    创建用户模型，用于用户注册
    """
    username: str = Field(..., min_length=3, max_length=50,
                          sa_column_kwargs={"unique": True, "index": True, "nullable": False})
    email: EmailStr = Field(..., max_length=254, sa_column_kwargs={"unique": True, "index": True, "nullable": False})
    password: str = Field(..., min_length=8, max_length=40)


class UserUpdate(UserBase):
    """
    更新用户模型，用于管理员更新用户数据
    """
    username: str | None = Field(None, min_length=3, max_length=50)
    email: EmailStr | None = Field(None, max_length=254)
    is_active: bool | None = None
    is_superuser: bool | None = None


class UserUpdateMe(Base):
    """
    更新当前用户模型，用于用户更新自己的数据
    """
    username: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(Base):
    """
    更新密码模型
    """
    current_password: str = Field(..., min_length=8, max_length=40)
    new_password: str = Field(min_length=8, max_length=40)


class User(UserBase, table=True):
    """
    用户模型，用于创建用户表
    """
    __tablename__ = "users"

    hashed_password: str = Field(
        ...,
        max_length=100,
        sa_column_kwargs={"nullable": False}
    )

    def __repr__(self) -> str:
        return f"<User {self.username}>"
