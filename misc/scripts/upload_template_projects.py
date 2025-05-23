import glob
from loguru import logger
import os

import asyncio
import requests
from app.core.config import settings
from app.core.constants import LOROCRDT_TEXT_CONTAINER_ID
from app.models.project.file import FileCreateUpdate
from app.models.project.project import (MemberCreateUpdate, ProjectCreate,
                                        ProjectPermission, ProjectType)
from app.repositories.project.chat import ChatDAO
from app.repositories.project.file import FileDAO
from app.repositories.project.project import ProjectDAO
from app.repositories.user import UserDAO
from app.models.project.file import File
from sqlmodel.ext.asyncio.session import AsyncSession
from pathlib import Path
from app.core.db import async_session, engine
from loro import ExportMode, LoroDoc
from app.core.r2client import r2client
from lib.utils import is_likely_binary
from io import BytesIO

async def create_template_projects(db: AsyncSession) -> None:
    # with open("")
    admin_user = await UserDAO.get_user_by_email(email=settings.ADMIN_EMAIL, db=db)
    if not admin_user:
        raise ValueError("Admin user cannot be located to attach template project to")

    admin_projects = await ProjectDAO.get_all_projects(user=admin_user, db=db)

    for folder in os.scandir(os.path.normpath("./templates")):
        logger.info(f"Uploading template {folder}")
        # initialize projects based on existing file structure

        project_name = folder.name.replace("_", " ")

        for project in admin_projects:
            if project.name == project_name:
                template_project = project
                break
        else:  # for...else 中 else 只在没有break后运行
            """this is only executed on empty db"""
            pc = ProjectCreate(name=project_name, type=ProjectType.TEMPLATE, is_public=True)
            template_project = await ProjectDAO.create_project(project_create=pc, db=db)
            await ProjectDAO.add_member(
                MemberCreateUpdate(permission=ProjectPermission.OWNER), project=template_project, user=admin_user, db=db
            )
            await ChatDAO.create_chat_room(name=pc.name, project_id=template_project.id, db=db)

        """ below this is executed everytime on startup
            假设：服务不经常重启
        """
        for file in await ProjectDAO.get_files(project=template_project):
            await FileDAO.delete_file(file=file, user=admin_user, db=db)

        # this rests both local and remote to a "clean-slate"
        filepaths = glob.glob(os.path.normpath(os.path.join(folder.path, "**.**")), recursive=True)
        relpaths = [Path(filepath).relative_to(os.path.join("templates", folder.name, "")) for filepath in filepaths]

        for filepath, relpath in zip(filepaths, relpaths):
            head, tail = os.path.split(relpath)
            file = File(
                filename=tail, filepath=head, project_id=template_project.id
            )
            db.add(file)
            await db.commit()
            await db.refresh(file)
            
            with open(filepath, "rb") as f:
                # requests.put(url, data=f)
                data = f.read()
                isBinary = is_likely_binary(data)
                upload_content = None
                if isBinary:
                    upload_content = data
                else:
                    try:
                        doc = LoroDoc()
                        text = doc.get_text(LOROCRDT_TEXT_CONTAINER_ID)
                        text.insert(0, data.decode())
                        doc.commit()
                        upload_content = doc.export(ExportMode.Snapshot())
                    except:
                        upload_content = data

            frp = FileDAO.get_remote_file_path(file.id)
            r2client.upload_fileobj(BytesIO(upload_content), Bucket=settings.R2_BUCKET, Key=frp)
            
            if not await ProjectDAO.has_file_history(file=file, db=db):
                await FileDAO.check_file_exist_in_r2(file=file, db=db, user=admin_user)


        logger.info(f"Finished uploading template {folder}")


async def main():
    async with async_session() as db:
        await create_template_projects(db)

    if engine:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
