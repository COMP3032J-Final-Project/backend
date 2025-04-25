import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional, Self

from loguru import logger
from pydantic import EmailStr, model_validator
from sqlalchemy import ForeignKey, UniqueConstraint
from sqlmodel import Field, Relationship

from app.models.base import Base, BaseDB

from app.models.project.websocket import FileAction, ProjectAction

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
    NON_MEMBER = "non_member"  # 仅favorite但不是成员


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
    is_public: bool = Field(
        default=False,
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
    histories: list["ProjectHistory"] = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "lazy": "selectin"},
    )

    # 若type为Project，则is_public必须为False
    @model_validator(mode="after")
    def validate_is_public(self) -> Self:
        if self.type == ProjectType.PROJECT and self.is_public:
            logger.warning("Project type cannot be public, forcing is_public to False in Project model")
            self.is_public = False
        return self

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
        default=ProjectPermission.NON_MEMBER,
        sa_column_kwargs={"nullable": False},
    )
    is_favorite: bool = Field(
        default=False,
        sa_column_kwargs={"nullable": False},
    )

    project: "Project" = Relationship(back_populates="users")
    user: "User" = Relationship(back_populates="projects")


class ProjectHistory(BaseDB, table=True):
    """
    项目历史记录模型
    """

    __tablename__ = "project_histories"

    action: str = Field(
        ...,
        sa_column_kwargs={"nullable": False},
    )
    project_id: uuid.UUID = Field(
        ...,
        foreign_key="projects.id",
        sa_column_kwargs={"nullable": False, "index": True},
    )
    user_id: uuid.UUID = Field(
        ...,
        foreign_key="users.id",
        sa_column_kwargs={"nullable": False, "index": True},
    )
    file_id: uuid.UUID | None = Field(
        default=None,
        sa_column=ForeignKey("file.id", ondelete="SET NULL", nullable=True, index=True),
    )
    state_before: str | None = Field(
        default=None,
        sa_column_kwargs={"nullable": True},
    )
    state_after: str | None = Field(
        default=None,
        sa_column_kwargs={"nullable": True},
    )

    project: "Project" = Relationship(back_populates="histories")

    @model_validator(mode="after")
    def validate_action(self) -> Self:
        if self.action not in FileAction.values and self.action not in ProjectAction.values:
            raise ValueError(f"Invalid action: {self.action}")
        return self


class ProjectCreate(Base):
    name: str = Field(..., max_length=255)
    type: ProjectType = Field(default=ProjectType.PROJECT)
    is_public: bool = Field(default=False)

    @model_validator(mode="after")
    def validate_type_and_is_public(self) -> Self:
        if self.type == ProjectType.PROJECT and self.is_public:
            logger.warning("Project type cannot be public, forcing is_public to False in ProjectCreate")
            self.is_public = False
        return self


class ProjectUpdate(Base):
    name: str | None = Field(default=None, max_length=255)
    is_public: bool | None = Field(default=None)


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
    is_favorite: Optional[bool] = Field(default=None)
    favorite_num: Optional[int] = Field(default=None)
    members_num: Optional[int] = Field(default=None)
    owner: Optional["OwnerInfo"] = Field(default=None)


class ProjectID(Base):
    project_id: uuid.UUID = Field(..., description="The ID of the project")


class ProjectTypeData(Base):
    type: Optional[ProjectType] = Field(default=None)


class MemberInfo(Base):
    user_id: uuid.UUID = Field(...)
    username: str = Field(..., max_length=255)
    email: EmailStr = Field(..., max_length=255)
    permission: Optional[ProjectPermission] = Field(default=None)
    avatar_url: Optional[str] = Field(default=None)


class MemberCreateUpdate(Base):
    permission: ProjectPermission | None = Field(default=None)
    is_favorite: bool | None = Field(default=None)


class ProjectPermissionData(Base):
    permission: ProjectPermission = Field(..., description="The permission of the member")


class ProjectHistoryInfo(Base):
    action: ProjectAction | FileAction = Field(...)
    project_id: uuid.UUID = Field(...)
    file_id: uuid.UUID | None = Field(default=None)
    state_before: dict | None = Field(default=None)
    state_after: dict | None = Field(default=None)
    timestamp: datetime = Field(default_factory=datetime.now)
    user: MemberInfo = Field(...)