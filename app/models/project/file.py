import uuid
from typing import TYPE_CHECKING
from enum import Enum

from app.models.base import Base, BaseDB
from sqlmodel import Field, Relationship

if TYPE_CHECKING:
    from .project import Project


class FileType(str, Enum):
    FILE = "file"
    FOLDER = "folder"


class FileStatus(str, Enum):
    PENDING = "pending"  # 待上传
    UPLOADED = "uploaded"  # 已上传
    FAILED = "failed"  # 上传失败


class FileCreate(Base):
    filename: str = Field(..., max_length=255, sa_column_kwargs={"nullable": False, "index": True})
    filepath: str = Field(..., max_length=1024, sa_column_kwargs={"nullable": False})
    filetype: FileType = Field(...)


class FileUpdate(Base):
    filename: str = Field(..., max_length=255, sa_column_kwargs={"nullable": False, "index": True})
    filepath: str = Field(..., max_length=1024, sa_column_kwargs={"nullable": False})


class FileURL(Base):
    url: str = Field(..., max_length=1024)


class FileUploadResponse(Base):
    file_id: uuid.UUID
    url: str = Field(..., max_length=1024)


class File(BaseDB, table=True):
    """
    文件表单
    """

    __tablename__ = "file"
    project_id: uuid.UUID = Field(..., foreign_key="projects.id", sa_column_kwargs={"nullable": False, "index": True})
    project: "Project" = Relationship(back_populates="files")
    filename: str = Field(..., max_length=255, sa_column_kwargs={"nullable": False, "index": True})
    filepath: str = Field(..., max_length=1024, sa_column_kwargs={"nullable": False})
    filetype: FileType = Field(
        default=FileType.FILE,
        sa_column_kwargs={"nullable": False},
    )
    status: FileStatus = Field(default=FileStatus.PENDING)  # 文件状态
