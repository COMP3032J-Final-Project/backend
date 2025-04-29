import logging
import os
import uuid
from io import BytesIO
from pathlib import Path, PureWindowsPath
from typing import Optional

import botocore
import orjson
from app.core.config import settings
from app.core.r2client import r2client
from app.models.project.file import File, FileCreateUpdate
from app.models.project.project import Project
from app.models.project.websocket import FileAction
from app.models.user import User
from app.repositories.project.project import ProjectDAO
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

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
        file_create_update: FileCreateUpdate, project: Project, db: AsyncSession, user: User, expiration=settings.EXPIRATION_TIME
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

        # 添加历史记录
        owner = await ProjectDAO.get_project_owner(file.project, db)
        state_before = {
            "filename": file.filename,
            "filepath": file.filepath,
        }
        await ProjectDAO.add_project_history(
            action=FileAction.DELETED,
            project=file.project,
            user=owner,
            db=db,
            file=file,
            state_before=orjson.dumps(state_before),
        )

        await db.delete(file)
        await db.commit()

        return True

    @staticmethod
    async def move_file(
        file_action: FileAction, file: File, file_create_update: FileCreateUpdate, db: AsyncSession, user: User
    ) -> File:
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
            state_before = {
                "filename": file.filename,
                "filepath": file.filepath,
            }

            new_filename = file_create_update.filename if file_create_update.filename else file.filename
            new_filepath = file_create_update.filepath if file_create_update.filepath else file.filepath

            file.filename = new_filename
            file.filepath = new_filepath
            db.add(file)

            state_after = {
                "filename": new_filename,
                "filepath": new_filepath,
            }
            await ProjectDAO.add_project_history(
                action=file_action,
                project=file.project,
                user=user,
                db=db,
                file=file,
                state_before=orjson.dumps(state_before),
                state_after=orjson.dumps(state_after),
                commit=False,
            )

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
        user: User,
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
            await FileDAO.check_file_exist_in_r2(target_file, db, user)
        except botocore.exceptions.ClientError as error:
            logger.error(error)
            raise

        return target_file

    @staticmethod
    async def copy_project(
        template_project: Project,
        new_project: Project,
        db: AsyncSession,
    ) -> None:
        """
        复制模板项目的文件到新项目
        """
        template_files = await ProjectDAO.get_files(template_project)

        # 复制文件
        for template_file in template_files:
            owner = await ProjectDAO.get_project_owner(new_project, db)
            is_exist = await FileDAO.check_file_exist_in_r2(template_file, db, owner)
            if not is_exist:
                logger.warning(f"File {template_file.filename} does not exist in R2, skipping copy.")
                continue

            new_file = await FileDAO.copy_file(
                source_file=template_file,
                target_project=new_project,
                target_file_create_update=FileCreateUpdate(
                    filename=template_file.filename,
                    filepath=template_file.filepath,
                ),
                db=db,
            )
            logger.info(f"Copied file {template_file.filename} to {new_file.filename}")

    @staticmethod
    def get_temp_file_path(file: File) -> Path:
        """
        各自平台对应的本地暂存文件夹路径
        """
        return settings.TEMP_PROJECTS_PATH / str(file.project_id) / file.filepath / file.filename

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

        TODO 目前是没有对本地编辑文件进行重命名操作的，之所编译有用，是因为 crdt_handler
        ，所以本地编译文件原来名字的文件还是会存在

        最好用类似 Django signals 之类的东西来实现
        https://docs.djangoproject.com/en/5.2/topics/signals/
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
    async def generate_get_obj_link_for_file(file: File, expiration=settings.EXPIRATION_TIME) -> str:
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
    async def check_file_exist_in_r2(file: File, db: AsyncSession, user: User | None = None) -> bool:
        """
        检查文件对应的远程资源是否在R2中存在
        """
        try:
            r2client.head_object(Bucket=settings.R2_BUCKET, Key=FileDAO.get_remote_file_path(file.id))
            logger.info(f"File {file.id} exists in R2")

            # 检查历史记录
            has_history = await ProjectDAO.has_file_history(file, db)
            if not has_history:
                logger.info(f"File {file.id} has no history, adding history")
                project = await ProjectDAO.get_project_by_id(file.project_id, db)
                state_after = {
                    "filename": file.filename,
                    "filepath": file.filepath,
                }
                await ProjectDAO.add_project_history(
                    action=FileAction.ADDED,
                    project=project,
                    user=user,
                    db=db,
                    file=file,
                    state_after=orjson.dumps(state_after),
                    commit=True,
                )
            return True
        except botocore.exceptions.ClientError as error:
            if error.response["Error"]["Code"] == "404":
                logger.info(f"File {file.id} not found in R2")
                await db.delete(file)
                await db.commit()
                return False
            logger.error("Check file exist in r2 error", error)
            raise

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
