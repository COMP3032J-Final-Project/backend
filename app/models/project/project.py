import uuid
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import EmailStr
from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship

from app.models.base import Base, BaseDB

if TYPE_CHECKING:
    from app.models.user import User


class ProjectPermission(str, Enum):
    """
    项目权限模型
    """

    VIEWER = "viewer"
    WRITER = "writer"
    ADMIN = "admin"
    OWNER = "owner"


class Project(BaseDB, table=True):
    """
    项目模型
    """

    __tablename__ = "projects"

    name: str = Field(
        ...,
        max_length=255,
        sa_column_kwargs={"index": True, "nullable": False},
    )
    owner_id: uuid.UUID = Field(
        ...,
        foreign_key="users.id",
        sa_column_kwargs={
            "nullable": False,
            "index": True,
        },
    )
    description: str = Field(max_length=255)

    users: list["ProjectUser"] = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "lazy": "selectin"},
    )

    def __repr__(self) -> str:
        return f"<Project name={self.name} owner_id={self.owner_id}>"


class ProjectUser(BaseDB, table=True):
    """
    项目用户模型
    """

    __tablename__ = "project_users"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uix_project_user"),
    )

    project_id: uuid.UUID = Field(
        ...,
        foreign_key="projects.id",
        sa_column_kwargs={
            "nullable": False,
            "index": True,
        },
    )
    user_id: uuid.UUID = Field(
        ...,
        foreign_key="users.id",
        sa_column_kwargs={"nullable": False, "index": True},
    )
    permission: ProjectPermission = Field(
        default=ProjectPermission.VIEWER,
        sa_column_kwargs={"nullable": False},
    )

    project: "Project" = Relationship(back_populates="users")
    user: "User" = Relationship(back_populates="projects")


class ProjectCreate(Base):
    name: str = Field(..., max_length=255)
    description: str = Field(..., max_length=255)


class ProjectUpdate(Base):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=255)


class ProjectID(Base):
    project_id: uuid.UUID = Field(..., description="The ID of the project")


class MemberInfo(Base):
    username: str = Field(..., max_length=255)
    email: EmailStr = Field(..., max_length=255)
    permission: ProjectPermission = Field(...)


class MemberPermission(Base):
    permission: ProjectPermission = Field(..., description="The permission of the member")



