import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

from pydantic import EmailStr
from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship

from app.models.base import Base, BaseDB

if TYPE_CHECKING:
    from app.models.project.file import File
    from app.models.project.chat import ChatRoom
    from app.models.user import User


class ProjectPermission(str, Enum):
    """
    项目权限枚举
    """

    VIEWER = "viewer"
    WRITER = "writer"
    ADMIN = "admin"
    OWNER = "owner"


class ProjectType(str, Enum):
    """
    项目类型枚举
    """

    PROJECT = "project"
    TEMPLATE = "template"


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
    type: ProjectType = Field(
        default=ProjectType.PROJECT,
        sa_column_kwargs={"nullable": False},
    )
    users: list["ProjectUser"] = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "lazy": "selectin"},
    )
    chat_room: "ChatRoom" = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "lazy": "selectin"},
    )

    files: list["File"] = Relationship(
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
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uix_project_user"),)

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
    type: ProjectType = Field(...)


class ProjectUpdate(Base):
    name: str | None = Field(default=None, max_length=255)


class ProjectsDelete(Base):
    project_ids: list[uuid.UUID] = Field(...)


class OwnerInfo(Base):
    username: str = Field(...)
    email: EmailStr = Field(...)


class ProjectInfo(Base):
    id: uuid.UUID = Field(..., sa_column_kwargs={"index": True})
    name: str = Field(
        ...,
        max_length=255,
    )
    type: ProjectType = Field(default=ProjectType.PROJECT)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    members_num: Optional[int] = Field(default=None)
    owner: Optional["OwnerInfo"] = Field(default=None)


class ProjectID(Base):
    project_id: uuid.UUID = Field(..., description="The ID of the project")


class MemberInfo(Base):
    username: str = Field(..., max_length=255)
    email: EmailStr = Field(..., max_length=255)
    permission: ProjectPermission = Field(...)


class MemberPermission(Base):
    permission: ProjectPermission = Field(..., description="The permission of the member")
