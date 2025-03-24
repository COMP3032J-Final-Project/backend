import os
import uuid
from typing import Any, BinaryIO, List, Optional, Type

from app.core.config import settings
from app.core.r2client import r2client
from app.models.project.file import File, FileCreate
from app.models.project.project import Project
from sqlmodel.ext.asyncio.session import AsyncSession


class FileDAO:
    @staticmethod
    async def get_file_by_id(file_id: uuid.UUID, db: AsyncSession) -> Optional[File]:
        return await db.get(File, file_id)
    
    @staticmethod
    async def create_file(file_create: FileCreate, project: Project, db: AsyncSession) -> File:
        File = File(
            filename=file_create.filename,
            type=file_create.type,
            filepath=file_create.filepath,
            project_id=project.id,
        )
        db.add(File)
        await db.commit()
        await db.refresh(File)
        return File

    @staticmethod
    async def pull_file_from_r2(file: File) -> BinaryIO:
        with open(settings.TEMP_DIR, "wb") as f:
            r2client.download_fileobj("hivey-files", file.filename, f)
        return f
    
    @staticmethod
    async def push_file_to_r2(file: File, f: BinaryIO) -> None:
        # TODO: 上传文件至云端
        return f

