import uuid
from typing import Optional, Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.project.project import (
    Project,
    ProjectCreate,
    ProjectPermission,
    ProjectUpdate,
    ProjectUser,
)
from app.models.user import User


class ProjectDAO:
    @staticmethod
    async def get_project_by_id(
        project_id: uuid.UUID,
        db: AsyncSession,
    ) -> Optional[Project]:
        return await db.get(Project, project_id)

    @staticmethod
    async def create_project(
        user_id: uuid.UUID,
        project_create: ProjectCreate,
        db: AsyncSession,
    ) -> Project:
        project = Project(
            name=project_create.name,
            description=project_create.description,
            founder_id=user_id,
        )
        db.add(project)
        await db.commit()
        await db.refresh(project)
        return project

    @staticmethod
    async def update_project(
        project: Project,
        project_update: ProjectUpdate,
        db: AsyncSession,
    ) -> Project:
        project.name = project_update.name
        project.description = project_update.description
        db.add(project)
        await db.commit()
        await db.refresh(project)
        return project

    @staticmethod
    async def delete_project(
        project: Project,
        db: AsyncSession,
    ) -> None:
        await db.delete(project)
        await db.commit()

    @staticmethod
    async def is_project_founder(
        project: Project,
        user: User,
    ) -> bool:
        return project.founder_id == user.id

    @staticmethod
    async def add_member(
        project: Project,
        user: User,
        db: AsyncSession,
        permission: ProjectPermission = ProjectPermission.READ,
    ) -> None:
        project_user = ProjectUser(project_id=project.id, user_id=user.id, permission=permission)
        db.add(project_user)
        await db.commit()

    @staticmethod
    async def is_project_member(
        project: Project,
        user: User,
        db: AsyncSession,
    ) -> bool:
        query = select(ProjectUser).where(
            ProjectUser.project_id == project.id,
            ProjectUser.user_id == user.id,
        )
        result = await db.execute(query)
        return result.first() is not None

    async def get_member_list(
        project: Project,
        db: AsyncSession,
    ) -> list[User]:
        query = (
            select(User)
            .join(ProjectUser, User.id == ProjectUser.user_id)
            .where(ProjectUser.project_id == project.id)
        )
        result = await db.execute(query)
        return result.scalars().all()

    @staticmethod
    async def get_project_permission(
            project: Project,
            user: User,
            db: AsyncSession,
    ) -> Any | None:
        query = select(ProjectUser).where(
            ProjectUser.project_id == project.id,
            ProjectUser.user_id == user.id,
        )
        result = await db.execute(query)
        project_user = result.scalar_one_or_none()
        if project_user is None:
            return None
        return project_user.permission

    @staticmethod
    async def is_project_admin(
        project: Project,
        user: User,
        db: AsyncSession,
    ) -> bool:
        """
        判断用户是否具有项目管理权限
        """
        return (
            await ProjectDAO.get_project_permission(project, user, db)
            == ProjectPermission.ADMIN
        )

    @staticmethod
    async def is_project_write(
        project: Project,
        user: User,
        db: AsyncSession,
    ) -> bool:
        """
        判断用户是否具有项目写入权限
        """
        return (
            await ProjectDAO.get_project_permission(project, user, db)
            == ProjectPermission.WRITE
        )

    @staticmethod
    async def is_project_read(
        project: Project,
        user: User,
        db: AsyncSession,
    ) -> bool:
        """
        判断用户是否具有项目读取权限
        """
        return (
            await ProjectDAO.get_project_permission(project, user, db)
            == ProjectPermission.READ
        )
