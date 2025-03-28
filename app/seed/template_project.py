import glob
import logging
import os

from app.core.config import settings
from app.models.project.file import FileCreate
from app.models.project.project import (ProjectCreate, ProjectPermission,
                                        ProjectType)
from app.repositories.project.chat import ChatDAO
from app.repositories.project.file import FileDAO
from app.repositories.project.project import ProjectDAO
from app.repositories.user import UserDAO
from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger("uvicorn.error")


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
        else:
            pc = ProjectCreate(name=project_name, type=ProjectType.TEMPLATE)
            template_project = await ProjectDAO.create_project(project_create=pc, db=db)
            await ProjectDAO.add_member(
                project=template_project, user=admin_user, permission=ProjectPermission.OWNER, db=db
            )
            await ChatDAO.create_chat_room(name=pc.name, project_id=template_project.id, db=db)

        # delete file currently associated with the Project instance.
        for file in await ProjectDAO.get_files(project=template_project, db=db):
            await FileDAO.delete_file(file=file, db=db)

        # delete any file from remote storage
        for key in await FileDAO.list_r2_keys(prefix=folder.name):
            await FileDAO.delete_key_from_r2(key=key)

        # this rests both local and remote to a "clean-slate"

        filepaths = glob.glob(os.path.normpath(os.path.join(folder.path, "**.**")), recursive=True)
        relpaths = [
            os.path.normpath(os.path.relpath(filepath, os.path.normpath("./templates"))) for filepath in filepaths
        ]

        for filepath, relpath in zip(filepaths, relpaths):
            head, tail = os.path.split(relpath)
            file = await FileDAO.create_file(
                file_create=FileCreate(filename=tail, filepath=head), project=template_project, db=db
            )

            # logger.info(await FileDAO.generate_get_obj_link_for_file(file=file))
            await FileDAO.push_file_to_r2(file=file, localpath=filepath)
