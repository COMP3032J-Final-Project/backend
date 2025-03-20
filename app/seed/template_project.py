from app.core.config import settings
from app.models.project.project import ProjectCreate, ProjectPermission
from app.repositories.project.project import ProjectDAO
from app.repositories.user import UserDAO
from sqlalchemy.ext.asyncio import AsyncSession


async def create_template_project(db: AsyncSession) -> None:
    admin_user = await UserDAO.get_user_by_email(email=settings.ADMIN_EMAIL, db=db)
    if admin_user:
        admins_projects = await ProjectDAO.get_projects(user=admin_user, db=db)
        if not admins_projects:
            template_project = await ProjectDAO.create_project(project_create=ProjectCreate(name="Templates"), db=db)
            await ProjectDAO.add_member(
                project=template_project, user=admin_user, permission=ProjectPermission.OWNER, db=db
            )
            # Template project should not need a chatroom
    else:
        raise ValueError("Admin user cannot be located to attach template project to")
