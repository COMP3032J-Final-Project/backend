import os
import uuid
from typing import Any, BinaryIO, List, Optional, Type

from app.core.config import settings
from app.core.r2client import r2client
from app.models.project.file import File, FileCreate
from app.models.project.project import Project
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel.ext.asyncio.session import AsyncSession


def get_local_file_path(file: File) -> str:
    return os.path.normpath(os.path.join(settings.TEMP_PATH, file.filepath, file.filename))


def get_remote_file_path(file: File) -> str:
    return os.path.normpath(os.path.join(file.filepath, file.filename))


class FileDAO:

    @staticmethod
    async def get_file_by_id(file_id: uuid.UUID, db: AsyncSession) -> Optional[File]:
        return await db.get(File, file_id)

    @staticmethod
    async def create_file(file_create: FileCreate, project: Project, db: AsyncSession) -> File:
        file = File(
            filename=file_create.filename,
            type=file_create.type,
            filepath=os.path.normpath(file_create.filepath),
            project_id=project.id,
        )
        db.add(file)
        await db.commit()
        await db.refresh(file)
        return file

    @staticmethod
    async def pull_file_from_r2(file: File) -> BinaryIO:
        """
        将远程文件拉到本地，保留原本文件树结构
        """
        flp = get_local_file_path(file=file)
        fp = get_remote_file_path(file=file)
        with open(flp, "wb") as f:
            r2client.download_fileobj(settings.R2_BUCKET, fp, f)
        return f

    @staticmethod
    async def push_file_to_r2(file: File, bf: BinaryIO) -> None:
        """
        上传文件至云端
        # 使用样例：

        使用样例：
            push_file_to_r2(file: File)
        """
        flp = get_local_file_path(file=file)
        fp = get_remote_file_path(file=file)

        with open(flp, "rb") as f:
            r2client.upload_fileobj(f, settings.R2_BUCKET, fp)
        return
