import glob
import logging
import os

from app.core.config import settings
from app.models.project.file import FileCreate
from app.models.project.project import (ProjectCreate, ProjectPermission,
                                        ProjectType)
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

    admins_projects = await ProjectDAO.get_projects(user=admin_user, db=db)
    if admins_projects:
        for project in admins_projects:
            # remove all projects associated with the administrator.
            await ProjectDAO.delete_project(project=project, db=db)

    for folder in os.scandir(os.path.normpath("./templates")):
        # initialize projects based on existing file structure

        project_name = folder.name.replace("_", " ")
        filepaths = glob.glob(os.path.normpath(os.path.join(folder.path, "**.**")), recursive=True)
        relpaths = [
            os.path.normpath(os.path.relpath(filepath, os.path.normpath("./templates"))) for filepath in filepaths
        ]

        template_project = await ProjectDAO.create_project(
            project_create=ProjectCreate(name=project_name, type=ProjectType.TEMPLATE), db=db
        )
        await ProjectDAO.add_member(
            project=template_project, user=admin_user, permission=ProjectPermission.OWNER, db=db
        )

        for filepath, relpath in zip(filepaths, relpaths):
            head, tail = os.path.split(relpath)
            file = await FileDAO.create_file(
                file_create=FileCreate(filename=tail, filepath=head), project=template_project, db=db
            )
            await FileDAO.push_file_to_r2(file=file, localpath=filepath)
