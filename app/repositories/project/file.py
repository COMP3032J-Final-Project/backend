import logging
import os
import uuid
from pathlib import PureWindowsPath
from typing import List, Optional

import botocore
from app.core.config import settings
from app.core.r2client import r2client
from app.models.project.file import File, FileCreateUpdate  # , FileStatus
from app.models.project.project import Project
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

logger = logging.getLogger("uvicorn.error")


def force_posix(path: str) -> str:
    """
    https://stackoverflow.com/questions/75291812/how-do-i-normalize-a-path-format-to-unix-style-while-on-windows
    """
    return PureWindowsPath(os.path.normpath(PureWindowsPath(path).as_posix())).as_posix()


class FileDAO:

    @staticmethod
    async def rename_file(file_id: uuid.UUID, file_create_update: FileCreateUpdate, db: AsyncSession) -> file:
        """
        注意！注意！注意！
        该操作（目前）有非常复杂的副作用，请务必谨慎考虑！！
        Notes
        -----
        该操作的实现基于数据库内部的重命名，对远程资源没有任何操作！
        对远程资源的更改，包括此前生成的临时URL，仍然指向远程资源！
        """
        file = await FileDAO.get_file_by_id(file_id=file_id)
        file.filename = file_create_update.filename
        file.filepath = file_create_update.filepath

        await db.add(current_file)
        await db.commit()
        await db.refresh(file)

        return file

    # @staticmethod
    # def copy_file_r2(file: File, new_file: File, db: AsyncSession) -> File:

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
        返回格式: project/{project_id}/{filepath}/{filename}
        """
        return force_posix(os.path.join("project", str(file.id)))

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
    async def create_file_in_db(file_create_update: FileCreateUpdate, project: Project, db: AsyncSession) -> File:
        """
        创建db文件
        """
        file = File(
            filename=file_create_update.filename,
            filepath=file_create_update.filepath,
            project_id=project.id,
        )
        db.add(file)
        await db.commit()
        await db.refresh(file)
        return file

    @staticmethod
    async def delete_file_in_db(file: File, db: AsyncSession) -> None:
        """
        从数据库中删除文件
        """
        await db.delete(file)
        await db.commit()

    @staticmethod
    async def delete_file_in_r2(file: File) -> bool:
        """
        从R2中删除文件
        """
        try:
            if not await FileDAO.check_file_in_r2(file):
                return False

            r2client.delete_object(Bucket=settings.R2_BUCKET, Key=FileDAO.get_remote_file_path(file))
            return True
        except botocore.exceptions.ClientError as error:
            logger.error(f"Error deleting file from R2: {error}")
            return False

    @staticmethod
    async def generate_get_obj_link_for_file(file: File, expiration=3600) -> str:
        """
        仅用于已经正常上传到远程的文件！
        """
        fp = FileDAO.get_remote_file_path(file=file)
        return await FileDAO.generate_get_obj_link_from_key(key=fp, expiration=expiration)

    @staticmethod
    async def generate_get_obj_link_from_key(key: str, expiration=3600) -> str:
        """
        使用r2 key生成临时链接
        默认过期时间单位为秒
        """
        response = ""
        try:
            response = r2client.generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.R2_BUCKET, "Key": key},
                ExpiresIn=expiration,
            )
        except botocore.exceptions.ClientError as error:
            logger.error(error)

        return response

    @staticmethod
    async def generate_put_obj_link_from_key(key: str, expiration=3600) -> str:
        """
        使用 R2 key 生成上传文件的临时 PUT 链接
        """
        try:
            response = r2client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": settings.R2_BUCKET,
                    "Key": key,
                },
                ExpiresIn=expiration,
            )
        except botocore.exceptions.ClientError as error:
            logger.error(error)
            raise

        return response

    @staticmethod
    async def generate_put_obj_link_for_file(file: File, expiration=3600) -> str:
        """
        为文件生成上传的临时链接
        """
        fp = FileDAO.get_remote_file_path(file=file)
        url = await FileDAO.generate_put_obj_link_from_key(key=fp, expiration=expiration)
        return url

    @staticmethod
    async def check_file_in_r2(file: File) -> bool:
        """
        检查文件是否在R2中存在
        """
        try:
            r2client.head_object(Bucket=settings.R2_BUCKET, Key=FileDAO.get_remote_file_path(file=file))
            return True
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise

    @staticmethod
    async def push_file_to_r2(file: File, localpath: str = "") -> None:
        """
        上传文件至云端
        使用样例：
            push_file_to_r2(file: File)
            push_file_to_r2(file: File, localpath:)
        如果规定localpath则覆写本地路径的取值
        """
        flp = localpath if localpath else FileDAO.get_temp_file_path(file=file)
        frp = FileDAO.get_remote_file_path(file=file)
        try:
            with open(flp, "rb") as f:
                r2client.upload_fileobj(Fileobj=f, Bucket=settings.R2_BUCKET, Key=frp)
        except botocore.exceptions.ClientError as error:
            logger.error(error)

    @staticmethod
    async def delete_file_from_r2(file: File) -> None:
        await FileDAO.delete_key_from_r2(key=FileDAO.get_remote_file_path(file=file))

    @staticmethod
    async def delete_key_from_r2(key: str = "") -> None:
        try:
            r2client.delete_object(Bucket=settings.R2_BUCKET, Key=key)
        except botocore.exceptions.ClientError as error:
            logger.error(error)

    @staticmethod
    async def list_r2_keys(prefix: str, maxkeys=100) -> List[str]:
        """
        R2 key = 远程文件夹+远程文件名
        """
        contents: List[str] = []
        try:
            # this handles the more generic batched case.
            response = r2client.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=prefix, MaxKeys=maxkeys)
            contents.extend(content["Key"] for content in response["Contents"])
            while "NextContinuationToken" in response:
                continuation_token = response["NextContinuationToken"]
                response = r2client.list_objects_v2(
                    Bucket="hivey-files", Prefix=prefix, MaxKeys=maxkeys, ContinuationToken=continuation_token
                )
                contents.extend(content["Key"] for content in response["Contents"])

        except (botocore.exceptions.ClientError, KeyError) as error:
            logger.error(error)

        return contents

    @staticmethod
    async def list_project_r2_keys(project_id: uuid.UUID) -> List[str]:
        """
        拉取某一特定project对应的文件
        """
        return await FileDAO.list_r2_keys(prefix=force_posix(os.path.join("project", str(project_id))))
