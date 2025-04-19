import uuid
from typing import TYPE_CHECKING, Optional

from app.models.base import Base, BaseDB
from sqlmodel import Field, Relationship

if TYPE_CHECKING:
    from .project import Project


class FileCreateUpdate(Base):
    filename: Optional[str] = Field(default=None, max_length=255, sa_column_kwargs={"nullable": False, "index": True})
    filepath: Optional[str] = Field(default=None, max_length=1024, sa_column_kwargs={"nullable": False})


class FileURL(Base):
    url: str = Field(..., max_length=1024)


class FileUploadResponse(Base):
    file_id: uuid.UUID
    url: str | None = Field(default=None, max_length=1024)


class File(BaseDB, table=True):
    """
    文件表单
    """

    __tablename__ = "file"
    project_id: uuid.UUID = Field(..., foreign_key="projects.id", sa_column_kwargs={"nullable": False, "index": True})
    project: "Project" = Relationship(back_populates="files")
    filename: str = Field(..., max_length=255, sa_column_kwargs={"nullable": False, "index": True})
    filepath: str = Field(..., max_length=1024, sa_column_kwargs={"nullable": False})
