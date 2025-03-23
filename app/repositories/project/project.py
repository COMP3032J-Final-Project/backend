import uuid
from typing import Any, List, Optional, Type

from app.models.project.file import File
from app.models.project.project import Project, ProjectCreate, ProjectPermission, ProjectUpdate, ProjectUser
from app.models.user import User
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession


class ProjectDAO:
    @staticmethod
    async def get_project_by_id(
        project_id: uuid.UUID,
        db: AsyncSession,
    ) -> Optional[Project]:
        return await db.get(Project, project_id)

    @staticmethod
    async def get_projects(
        user: User,
        db: AsyncSession,
    ) -> list[Optional[Project]]:
        """
        获取当前用户的所有项目
        """
        user_projects = user.projects
        projects = []
        for user_project in user_projects:
            project = await db.get(Project, user_project.project_id)
            projects.append(project)
        return projects

    @staticmethod
    async def create_project(
        project_create: ProjectCreate,
        db: AsyncSession,
    ) -> Project:
        project = Project(
            name=project_create.name,
            type=project_create.type,
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
    ) -> Optional[Project]:
        update_data = project_update.model_dump(exclude_unset=True, exclude_none=True)
        for field in update_data:
            setattr(project, field, update_data[field])
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            return None
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
    async def get_project_owner(
        project: Project,
        db: AsyncSession,
    ) -> Optional[User]:
        query = select(ProjectUser).where(
            ProjectUser.project_id == project.id,
            ProjectUser.permission == ProjectPermission.OWNER,
        )
        result = await db.execute(query)
        project_user = result.scalar_one()
        user = await db.get(User, project_user.user_id)
        return user

    @staticmethod
    async def get_project_permission(
        project: Project,
        user: User,
        db: AsyncSession,
    ) -> Optional[ProjectPermission]:
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
    async def is_project_owner(
        project: Project,
        user: User,
        db: AsyncSession,
    ) -> bool:
        return await ProjectDAO.get_project_permission(project, user, db) == ProjectPermission.OWNER

    @staticmethod
    async def is_project_admin(
        project: Project,
        user: User,
        db: AsyncSession,
    ) -> bool:
        """
        判断用户是否为项目管理员
        """
        return await ProjectDAO.get_project_permission(project, user, db) == ProjectPermission.ADMIN

    @staticmethod
    async def is_project_writer(
        project: Project,
        user: User,
        db: AsyncSession,
    ) -> bool:
        """
        判断用户是否为项目成员
        """
        return await ProjectDAO.get_project_permission(project, user, db) == ProjectPermission.WRITER

    @staticmethod
    async def is_project_viewer(
        project: Project,
        user: User,
        db: AsyncSession,
    ) -> bool:
        """
        判断用户是否为项目查看者
        """
        return await ProjectDAO.get_project_permission(project, user, db) == ProjectPermission.VIEWER

    @staticmethod
    async def is_project_member(
        project: Project,
        user: User,
        db: AsyncSession,
    ) -> bool:
        """
        判断用户是否为项目成员
        """
        query = select(ProjectUser).where(
            ProjectUser.project_id == project.id,
            ProjectUser.user_id == user.id,
        )
        result = await db.execute(query)
        return result.first() is not None

    @staticmethod
    async def get_members(
        project: Project,
        db: AsyncSession,
    ) -> list[Optional[User]]:
        project_users = project.users
        members = []
        for project_user in project_users:
            user = await db.get(User, project_user.user_id)
            members.append(user)
        return members

    @staticmethod
    async def add_member(
        project: Project,
        user: User,
        permission: ProjectPermission,
        db: AsyncSession,
    ) -> None:
        project_user = ProjectUser(project_id=project.id, user_id=user.id, permission=permission)
        db.add(project_user)
        await db.commit()

    @staticmethod
    async def remove_member(
        project: Project,
        user: User,
        db: AsyncSession,
    ) -> None:
        query = select(ProjectUser).where(
            ProjectUser.project_id == project.id,
            ProjectUser.user_id == user.id,
        )
        result = await db.execute(query)
        project_user = result.scalar_one_or_none()
        await db.delete(project_user)
        await db.commit()

    @staticmethod
    async def update_member(
        project: Project,
        user: User,
        permission: ProjectPermission,
        db: AsyncSession,
    ) -> None:
        query = select(ProjectUser).where(
            ProjectUser.project_id == project.id,
            ProjectUser.user_id == user.id,
        )
        result = await db.execute(query)
        project_user = result.scalar_one_or_none()
        assert project_user  # this should never be None.
        project_user.permission = permission
        await db.commit()
        await db.refresh(project_user)

    @staticmethod
    async def get_files(project: Project, db: AsyncSession) -> list[File]:
        project_files = project.files
        return project_files
