import uuid
from typing import TYPE_CHECKING, List
from enum import Enum

from app.models.base import Base, BaseDB
from sqlmodel import Field, Relationship

if TYPE_CHECKING:
    from .project import Project


class FileType(str, Enum):
    IMAGE = "image"
    MARKDOWN = "markdown"
    LATEX = "latex"
    TYPST = "typst"


class File(BaseDB, table=True):
    """
    文件表单
    """
    __tablename__ = "file"
    project_id: uuid.UUID = Field(..., foreign_key="projects.id", sa_column_kwargs={"nullable": False, "index": True})
    project: "Project" = Relationship(back_populates="files")
    filename: str = Field(..., max_length=255, sa_column_kwargs={"nullable": False, "index": True})
    type: FileType = Field(default=FileType.MARKDOWN, sa_column_kwargs={"nullable": False},)
    filepath: str = Field(..., max_length=1024, sa_column_kwargs={"nullable": False})


class FileCreate(Base):
    filename: str = Field(..., max_length=255, sa_column_kwargs={"nullable": False, "index": True})
    type: FileType = Field(...)
    filepath: str = Field(..., max_length=1024, sa_column_kwargs={"nullable": False})


class FileUpdate(Base):
    filename: str = Field(..., max_length=255, sa_column_kwargs={"nullable": False, "index": True})
    type: FileType = Field(...)
    filepath: str = Field(..., max_length=1024, sa_column_kwargs={"nullable": False})
