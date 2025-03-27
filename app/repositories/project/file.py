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
    async def delete_file(file: File, db: AsyncSession) -> None:
        await db.delete(file)
        await db.commit()

    @staticmethod
    async def pull_file_from_r2(file: File) -> BinaryIO:
        """
        将远程文件拉到本地，保留原本文件树结构
        """
        # TODO 暂时从本地 templates 文件夹读取文件
        try:
            file_path = os.path.join("./templates", file.filepath, file.filename)
            return open(file_path, "rb")
        except Exception as error:
            logger.error(f"Error reading file from local: {error}")
            return None

        # flp = FileDAO.get_temp_file_path(file=file)
        # fp = FileDAO.get_remote_file_path(file=file)
        # try:
        #     with open(flp, "wb") as f:
        #         r2client.download_fileobj(settings.R2_BUCKET, fp, f)
        # except botocore.exceptions.ClientError as error:
        #     logger.error(error)
        # return f

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
    async def push_file_to_r2(file: File, localpath: str = "") -> None:
        """
        上传文件至云端
        使用样例：
            push_file_to_r2(file: File)
            push_file_to_r2(file: File, localpath:)
        如果规定localpath则覆写本地路径的取值
        """
        flp = localpath if localpath else FileDAO.get_temp_file_path(file=file)
        fp = FileDAO.get_remote_file_path(file=file)
        try:
            with open(flp, "rb") as f:
                r2client.upload_fileobj(Fileobj=f, Bucket=settings.R2_BUCKET, Key=fp)
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
    async def list_r2_keys(prefix: str = os.path.normpath("./"), maxkeys=100) -> List[str]:
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
                    Bucket="hivey-files", Prefix="simple_article", MaxKeys=maxkeys, ContinuationToken=continuation_token
                )
                contents.extend(content["Key"] for content in response["Contents"])

        except (botocore.exceptions.ClientError, KeyError) as error:
            logger.error(error)

        return contents


"""
{'ResponseMetadata': {'HTTPStatusCode': 200, 'HTTPHeaders': {'date': 'Thu, 27 Mar 2025 16:09:15 GMT', 'content-type': 'application/xml', 'content-length': '284', 'connection': 'keep-alive', 'vary': 'Accept-Encoding', 'server': 'cloudflare', 'cf-ray': '927026b0af950e3d-AMS'}, 'RetryAttempts': 0}, 'IsTruncated': False, 'Name': 'hivey-files', 'Prefix': 'simple_article', 'MaxKeys': 1, 'EncodingType': 'url', 'KeyCount': 0}

"""
