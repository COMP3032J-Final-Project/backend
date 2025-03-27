import logging
import os
import uuid
from pathlib import PureWindowsPath
from typing import Any, BinaryIO, List, Optional, Type

import botocore
from app.core.config import settings
from app.core.r2client import r2client
from app.models.project.file import File, FileCreate
from app.models.project.project import Project
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("uvicorn.error")


def force_posix(path: str) -> str:
    """
    https://stackoverflow.com/questions/75291812/how-do-i-normalize-a-path-format-to-unix-style-while-on-windows
    """
    return PureWindowsPath(os.path.normpath(PureWindowsPath(path).as_posix())).as_posix()


class FileDAO:
    @staticmethod
    def get_temp_file_path(file: File) -> str:
        """
        各自平台对应的本地暂存文件夹路径
        """
        return os.path.normpath(os.path.join(settings.TEMP_PATH, file.filepath, file.filename))

    @staticmethod
    def get_remote_file_path(file: File) -> str:
        """
        R2平台路径必须使用POSIX类路径
        """
        return force_posix(os.path.join(file.filepath, file.filename))

    @staticmethod
    async def get_file_by_id(file_id: uuid.UUID, db: AsyncSession) -> Optional[File]:
        return await db.get(File, file_id)

    @staticmethod
    async def create_file(file_create: FileCreate, project: Project, db: AsyncSession) -> File:
        file = File(filename=file_create.filename, filepath=force_posix(file_create.filepath), project_id=project.id)
        db.add(file)
        await db.commit()
        await db.refresh(file)
        return file

    @staticmethod
    async def pull_file_from_r2(file: File) -> BinaryIO:
        """
        将远程文件拉到本地，保留原本文件树结构
        """
        flp = FileDAO.get_temp_file_path(file=file)
        fp = FileDAO.get_remote_file_path(file=file)
        try:
            with open(flp, "wb") as f:
                r2client.download_fileobj(settings.R2_BUCKET, fp, f)
        except botocore.exceptions.ClientError as error:
            logger.error(error)
        return f

    @staticmethod
    async def push_file_to_r2(file: File, localpath: str = "") -> None:
        """
        上传文件至云端
        # 使用样例：

        使用样例：
            push_file_to_r2(file: File)
            push_file_to_r2(file: File, localpath: )
        """
        flp = localpath if localpath else FileDAO.get_temp_file_path(file=file)
        fp = FileDAO.get_remote_file_path(file=file)
        try:
            with open(flp, "rb") as f:
                r2client.upload_fileobj(f, settings.R2_BUCKET, fp)
        except botocore.exceptions.ClientError as error:
            logger.error(error)
