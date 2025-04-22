import logging
import os
import uuid
from pathlib import PureWindowsPath
from typing import List, Optional

import botocore
from app.core.config import settings
from app.core.r2client import r2client
from app.models.project.file import File, FileCreateUpdate
from app.models.project.project import Project
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from io import BytesIO

logger = logging.getLogger("uvicorn.error")


def force_posix(path: str) -> str:
    """
    https://stackoverflow.com/questions/75291812/how-do-i-normalize-a-path-format-to-unix-style-while-on-windows
    """
    return PureWindowsPath(os.path.normpath(PureWindowsPath(path).as_posix())).as_posix()


def get_copy_filename(filename: str) -> str:
    """
    拆分文件名和后缀，并在后缀前添加"Copy"
    """
    name_parts = filename.rsplit(".", 1)
    if len(name_parts) > 1:
        return f"{name_parts[0]} Copy.{name_parts[1]}"
    return f"{filename} Copy"


class FileDAO:
    """
    Notes
    -----
    This layer is used to abstract away the local and remote file systems, and present it
    as a unified layer to the frontend.

    """

    @staticmethod
    async def create_update_file(
        file_create_update: FileCreateUpdate, project: Project, db: AsyncSession, expiration=3600
    ) -> tuple[File, str]:
        """
        增/改

        Return
        ------
        File, str:
            文件（新建或查找到的，对应上传/覆写URL）
        """
        try:
            file = await FileDAO.get_file_by_path(
                project_id=project.id, filepath=file_create_update.filepath, filename=file_create_update.filename, db=db
            )
        except Exception as e:
            logger.error(f"Error getting file by path: {e}")
            raise

        if not file:
            """
            文件不存在->增
            """
            file = File(
                filename=file_create_update.filename, filepath=file_create_update.filepath, project_id=project.id
            )
            db.add(file)
            await db.commit()
            await db.refresh(file)

        """
        文件存在->改
        """

        response = ""
        try:
            response = r2client.generate_presigned_url(
                "put_object",
                Params={"Bucket": settings.R2_BUCKET, "Key": FileDAO.get_remote_file_path(file.id)},
                ExpiresIn=expiration,
            )
        except botocore.exceptions.ClientError as error:
            logger.error(error)
            raise

        return file, response

    @staticmethod
    async def delete_file(file: File, db: AsyncSession) -> bool:
        """
        删除
        """
        try:
            r2client.delete_object(Bucket=settings.R2_BUCKET, Key=FileDAO.get_remote_file_path(file))
        except botocore.exceptions.ClientError as error:
            logger.error(f"{error}")
            raise

        await db.delete(file)
        await db.commit()
        return True

    @staticmethod
    async def move_file(file: File, file_create_update: FileCreateUpdate, db: AsyncSession) -> File:
        """
        移动/重命名现有文件（参考Linux mv）

        Parameters
        ----------
        file: File
            源文件
        file_create_update: FileCreateUpdate
            目标定义
        db:
            数据库
        """
        try:
            file.filename = file_create_update.filename if file_create_update.filename else file.filename
            file.filepath = file_create_update.filepath if file_create_update.filepath else file.filepath

            db.add(file)
            await db.commit()
            await db.refresh(file)
            return file
        except Exception as e:
            await db.rollback()
            logger.error(f"Error moving file: {e}")
            raise

    @staticmethod
    async def copy_file(
        source_file: File,
        target_file_create_update: FileCreateUpdate,
        db: AsyncSession,
        target_project: Optional[Project] = None,
    ) -> File:
        """
        复制文件
        """
        
        if not target_project:
            target_project = source_file.project
            filename = get_copy_filename(source_file.filename)
        else:
            filename = source_file.filename

        target_file = File(
            filename=filename,
            filepath=target_file_create_update.filepath if target_file_create_update.filepath else source_file.filepath,
            project_id=target_project.id,
        )
        db.add(target_file)
        await db.commit()
        await db.refresh(target_file)
        try:
            r2client.copy(
                {"Bucket": settings.R2_BUCKET, "Key": FileDAO.get_remote_file_path(source_file.id)},
                Bucket=settings.R2_BUCKET,
                Key=FileDAO.get_remote_file_path(target_file.id),
            )
        except botocore.exceptions.ClientError as error:
            logger.error(error)
            raise

        return target_file

    @staticmethod
    def get_temp_file_path(file: File) -> str:
        """
        各自平台对应的本地暂存文件夹路径
        """
        return os.path.normpath(os.path.join(settings.TEMP_PATH, file.filepath, file.filename))

    @staticmethod
    def get_remote_file_path(file_id: str | uuid.UUID) -> str:
        """
        R2平台路径必须使用POSIX类路径
        返回格式: project/{project_id}/{filepath}/{filename}
        """
        return force_posix(os.path.join("project", str(file_id)))

    @staticmethod
    async def rename_file(file: File, file_create_update: FileCreateUpdate, db: AsyncSession) -> File:
        """
        改
        Notes
        -----
        该操作的实现基于数据库内部的重命名，对远程资源没有任何操作！
        该操作有比较复杂的副作用，请务必注意！
        """
        file.filename = file_create_update.filename
        file.filepath = file_create_update.filepath

        await db.add(file)
        await db.commit()
        await db.refresh(file)

        return file

    @staticmethod
    async def get_file_by_id(file_id: uuid.UUID, db: AsyncSession) -> Optional[File]:
        return await db.get(File, file_id)

    @staticmethod
    async def get_file_by_path(project_id: uuid.UUID, filepath: str, filename: str, db: AsyncSession) -> Optional[File]:
        """
        通过文件名、路径和项目ID查找数据库file
        """
        query = select(File).where(File.project_id == project_id, File.filepath == filepath, File.filename == filename)
        result = await db.execute(query)
        return result.scalars().first()

    @staticmethod
    async def generate_get_obj_link_for_file(file: File, expiration=3600) -> str:
        fp = FileDAO.get_remote_file_path(file.id)
        response = ""
        try:
            response = r2client.generate_presigned_url(
                "get_object", Params={"Bucket": settings.R2_BUCKET, "Key": fp}, ExpiresIn=expiration
            )
        except botocore.exceptions.ClientError as error:
            logger.error(error)
            raise

        return response

    @staticmethod
    async def check_file_exist_in_r2(file: File) -> bool:
        """
        检查文件对应的远程资源是否在R2中存在
        """
        try:
            r2client.head_object(Bucket=settings.R2_BUCKET, Key=FileDAO.get_remote_file_path(file.id))
        except botocore.exceptions.ClientError as error:
            if error.response["Error"]["Code"] == "404":
                return False
            logger.error(error)
            raise
        else:
            return True

    @staticmethod
    def update_r2_file(content: bytes, file_id: str | uuid.UUID) -> None:
        """
        File id is 
        """
        frp = FileDAO.get_remote_file_path(file_id)
        try:
            r2client.upload_fileobj(BytesIO(content), Bucket=settings.R2_BUCKET, Key=frp)
        except botocore.exceptions.ClientError as error:
            logger.error(error)

    @staticmethod
    def get_r2_file_data(file_id: str | uuid.UUID) -> bytes:
        buffer = BytesIO()
        frp = FileDAO.get_remote_file_path(file_id)
        
        try:
            r2client.download_fileobj(settings.R2_BUCKET, frp, buffer)
            buffer.seek(0)
            data = buffer.read()
        finally:
            buffer.close()

        return data

    # @staticmethod
    # async def push_file_to_r2(file: File, localpath: str = "") -> None:
    #     """
    #     上传文件至云端
    #     使用样例：
    #         push_file_to_r2(file: File)
    #         push_file_to_r2(file: File, localpath:)
    #     如果规定localpath则覆写本地路径的取值
    #     """
    #     flp = localpath if localpath else FileDAO.get_temp_file_path(file=file)
    #     frp = FileDAO.get_remote_file_path(file=file)
    #     try:
    #         with open(flp, "rb") as f:
    #             r2client.upload_fileobj(Fileobj=f, Bucket=settings.R2_BUCKET, Key=frp)
    #     except botocore.exceptions.ClientError as error:
    #         logger.error(error)

    # @staticmethod
    # def list_r2_keys(prefix: str, maxkeys=100) -> List[str]:
    #     """
    #     R2 key = 远程文件夹+远程文件名
    #     """
    #     contents: List[str] = []
    #     try:
    #         # this handles the more generic batched case.
    #         response = r2client.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=prefix, MaxKeys=maxkeys)
    #         contents.extend(content["Key"] for content in response["Contents"])
    #         while "NextContinuationToken" in response:
    #             continuation_token = response["NextContinuationToken"]
    #             response = r2client.list_objects_v2(
    #                 Bucket="hivey-files", Prefix=prefix, MaxKeys=maxkeys, ContinuationToken=continuation_token
    #             )
    #             contents.extend(content["Key"] for content in response["Contents"])

    #     except (botocore.exceptions.ClientError, KeyError) as error:
    #         logger.error(error)

    #     return contents

    # @staticmethod
    # def list_project_r2_keys(project_id: uuid.UUID) -> List[str]:
    #     """
    #     拉取某一特定project对应的文件
    #     """
    #     return FileDAO.list_r2_keys(prefix=force_posix(os.path.join("project", str(project_id))))
