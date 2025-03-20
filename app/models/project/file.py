import uuid
from typing import TYPE_CHECKING, List

from app.models.base import Base, BaseDB
from sqlmodel import Field, Relationship

if TYPE_CHECKING:
    from .project import Project


class File(BaseDB, table=True):
    """
    文件表单
    """

    __tablename__ = "file"
    project_id: uuid.UUID = Field(..., foreign_key="projects.id", sa_column_kwargs={"nullable": False, "index": True})
    project: "Project" = Relationship(back_populates="files")
    filename: str = Field(..., max_length=255, sa_column_kwargs={"nullable": False, "index": True})


class FileCreateUpdate(Base):
    """
    文件的创建与更新
    """

    filename: str = Field(..., max_length=255, sa_column_kwargs={"nullable": False, "index": True})
