import glob
import logging
import os

import requests
from app.core.config import settings
from app.models.project.file import FileCreateUpdate
from app.models.project.project import (ProjectCreate, ProjectPermission,
                                        ProjectType)
from app.repositories.project.chat import ChatDAO
from app.repositories.project.file import FileDAO
from app.repositories.project.project import ProjectDAO
from app.repositories.user import UserDAO
from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger("uvicorn.error")
from pathlib import Path


async def create_template_projects(db: AsyncSession) -> None:
    # with open("")
    admin_user = await UserDAO.get_user_by_email(email=settings.ADMIN_EMAIL, db=db)
    if not admin_user:
        raise ValueError("Admin user cannot be located to attach template project to")

    admin_projects = await ProjectDAO.get_projects(user=admin_user, db=db)

    for folder in os.scandir(os.path.normpath("./templates")):
        # initialize projects based on existing file structure

        project_name = folder.name.replace("_", " ")

        for project in admin_projects:
            if project.name == project_name:
                template_project = project
                break
        else:  # for...else 中 else 只在没有break后运行
            """this is only executed on empty db"""
            pc = ProjectCreate(name=project_name, type=ProjectType.TEMPLATE)
            template_project = await ProjectDAO.create_project(project_create=pc, db=db)
            await ProjectDAO.add_member(
                project=template_project, user=admin_user, permission=ProjectPermission.OWNER, db=db
            )
            await ChatDAO.create_chat_room(name=pc.name, project_id=template_project.id, db=db)

        """ below this is executed everytime on startup
            假设：服务不经常重启
        """
        # delete file currently associated with the Project instance in database.
        for file in await ProjectDAO.get_files(project=template_project, db=db):
            await FileDAO.delete_file(file=file, db=db)

        # this rests both local and remote to a "clean-slate"
        filepaths = glob.glob(os.path.normpath(os.path.join(folder.path, "**.**")), recursive=True)
        relpaths = [Path(filepath).relative_to(os.path.join("templates", folder.name, "")) for filepath in filepaths]

        for filepath, relpath in zip(filepaths, relpaths):
            head, tail = os.path.split(relpath)
            file, url = await FileDAO.create_update_file(
                file_create_update=FileCreateUpdate(filename=tail, filepath=head), project=template_project, db=db
            )
            with open(filepath, "rb") as f:
                logger.info(tail)
                requests.put(url, data=f)

            # file = await FileDAO.create_file_in_db(
            #     file_create_update=FileCreateUpdate(filename=tail, filepath=head), project=template_project, db=db
            # )
            # await FileDAO.push_file_to_r2(file=file, localpath=filepath)
