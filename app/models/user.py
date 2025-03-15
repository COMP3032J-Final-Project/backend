# 用于实现 User 相关模型
from typing import TYPE_CHECKING, List
from pydantic import EmailStr, ConfigDict
from sqlmodel import Field, Relationship

from app.models.base import Base, BaseDB

# 避免循环导入
if TYPE_CHECKING:
    from app.models.project.project import ProjectUser


class User(BaseDB, table=True):
    """
    用户模型，用于创建用户表
    """

    __tablename__ = "users"

    username: str = Field(
        ...,
        min_length=3,
        max_length=50,
        sa_column_kwargs={"unique": True, "index": True, "nullable": False},
    )
    email: EmailStr = Field(
        ...,
        max_length=254,
        sa_column_kwargs={"unique": True, "index": True, "nullable": False},
    )
    hashed_password: str = Field(
        ..., max_length=100, sa_column_kwargs={"nullable": False}
    )
    is_active: bool = Field(
        default=True,
    )
    is_superuser: bool = Field(
        default=False,
    )

    # TODO 完善用户删除后的级联操作
    projects: List["ProjectUser"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )

    def __repr__(self) -> str:
        return (
            f"<User username={self.username} email={self.email} "
            f"is_active={self.is_active} is_superuser={self.is_superuser}>"
        )


class UserInfo(Base):
    """
    用户基本信息模型
    """

    username: str = Field(
        ...,  # 必填字段
        min_length=3,
        max_length=50,
        sa_column_kwargs={"unique": True, "index": True, "nullable": False},
        description="用户名",
    )
    email: EmailStr = Field(
        ...,
        max_length=254,
        sa_column_kwargs={"unique": True, "index": True, "nullable": False},
        description="电子邮件",
    )
    is_active: bool = Field(default=True, description="是否激活")
    is_superuser: bool = Field(default=False, description="是否为超级用户")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "username": "abc",
                "email": "abc@example.com",
                "is_active": True,
                "is_superuser": False,
            }
        }
    )


class UserRegister(Base):
    """
    创建用户模型，用于用户注册
    """

    username: str = Field(
        ...,
        min_length=3,
        max_length=50,
        sa_column_kwargs={"unique": True, "index": True, "nullable": False},
    )
    email: EmailStr = Field(
        ...,
        max_length=254,
        sa_column_kwargs={"unique": True, "index": True, "nullable": False},
    )
    password: str = Field(..., min_length=8, max_length=40)


# class UserUpdate(UserBase):
#     """
#     更新用户模型，用于管理员更新用户数据
#     """
#     username: str | None = Field(None, min_length=3, max_length=50)
#     email: EmailStr | None = Field(None, max_length=254)
#     is_active: bool | None = None
#     is_superuser: bool | None = None


class UserUpdate(Base):
    """
    更新当前用户模型，用于用户更新自己的数据
    """

    # TODO 添加其他用户信息字段
    username: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UserVerifyPwd(Base):
    """
    验证密码模型
    """

    password: str = Field(..., min_length=8, max_length=40)


class UserUpdatePwd(Base):
    """
    更新密码模型
    """

    new_password: str = Field(..., min_length=8, max_length=40)
