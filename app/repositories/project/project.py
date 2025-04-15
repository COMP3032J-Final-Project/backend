import uuid
from typing import Optional

from loguru import logger

from app.models.project.file import File, FileCreateUpdate
from app.models.project.project import (
    OwnerInfo,
    Project,
    ProjectCreate,
    ProjectInfo,
    ProjectPermission,
    ProjectUpdate,
    ProjectUser,
    ProjectType,
)
from app.models.user import User
from app.repositories.project.file import FileDAO
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession


class ProjectDAO:
    @staticmethod
    async def get_project_by_id(project_id: uuid.UUID, db: AsyncSession) -> Optional[Project]:
        return await db.get(Project, project_id)

    @staticmethod
    async def get_project_by_name(project_name: str, db: AsyncSession) -> Optional[Project]:
        """临时DAO demo用完即焚"""
        query = select(Project).where(Project.name == project_name)
        result = await db.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_projects(user: User, db: AsyncSession) -> list[Project]:
        """
        获取当前用户的所有项目
        """
        query = select(Project).join(ProjectUser).where(ProjectUser.user_id == user.id)
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_project_info(project: Project, db: AsyncSession) -> ProjectInfo:
        """
        包装项目信息
        """
        owner = await ProjectDAO.get_project_owner(project, db)
        owner_info = OwnerInfo.model_validate(owner)
        members_num = len(await ProjectDAO.get_members(project, db))

        project_info = ProjectInfo.model_validate(project)
        project_info.owner = owner_info
        project_info.members_num = members_num
        return project_info

    @staticmethod
    async def create_project(project_create: ProjectCreate, db: AsyncSession) -> Project:
        # ProjectCreate中的验证器已经保证了当type为Project时，is_public为False
        project = Project(
            name=project_create.name,
            type=project_create.type,
            is_public=project_create.is_public,
        )
        db.add(project)
        await db.commit()
        await db.refresh(project)
        return project

    @staticmethod
    async def update_project(project: Project, project_update: ProjectUpdate, db: AsyncSession) -> Optional[Project]:
        update_data = project_update.model_dump(exclude_unset=True, exclude_none=True)

        # 对于Project类型的项目，强制保持is_public为False
        if "is_public" in update_data and project.type == ProjectType.PROJECT and update_data["is_public"] is True:
            logger.warning("Project type cannot be public, forcing is_public to False in update_project")
            update_data["is_public"] = False

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
    async def delete_project(project: Project, db: AsyncSession) -> None:
        await db.delete(project)
        await db.commit()

    @staticmethod
    async def get_project_owner(project: Project, db: AsyncSession) -> Optional[User]:
        query = (
            select(User)
            .join(ProjectUser)
            .where(
                ProjectUser.project_id == project.id,
                ProjectUser.permission == ProjectPermission.OWNER,
            )
        )
        result = await db.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_project_permission(project: Project, user: User, db: AsyncSession) -> Optional[ProjectPermission]:
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
    async def is_project_owner(project: Project, user: User, db: AsyncSession) -> bool:
        return await ProjectDAO.get_project_permission(project, user, db) == ProjectPermission.OWNER

    @staticmethod
    async def is_project_admin(project: Project, user: User, db: AsyncSession) -> bool:
        """
        判断用户是否为项目管理员
        """
        return await ProjectDAO.get_project_permission(project, user, db) == ProjectPermission.ADMIN

    @staticmethod
    async def is_project_writer(project: Project, user: User, db: AsyncSession) -> bool:
        """
        判断用户是否为项目成员
        """
        return await ProjectDAO.get_project_permission(project, user, db) == ProjectPermission.WRITER

    @staticmethod
    async def is_project_viewer(project: Project, user: User, db: AsyncSession) -> bool:
        """
        判断用户是否为项目查看者
        """
        return await ProjectDAO.get_project_permission(project, user, db) == ProjectPermission.VIEWER

    @staticmethod
    async def is_project_member(project: Project, user: User, db: AsyncSession) -> bool:
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
    ) -> list[User]:
        query = select(User).join(ProjectUser).where(ProjectUser.project_id == project.id)
        result = await db.execute(query)
        return list(result.scalars().all())

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
    ) -> Optional[ProjectUser]:
        query = select(ProjectUser).where(
            ProjectUser.project_id == project.id,
            ProjectUser.user_id == user.id,
        )
        result = await db.execute(query)
        project_user = result.scalar_one_or_none()
        if project_user is None:
            return None
        project_user.permission = permission

        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            return None
        await db.refresh(project_user)
        return project_user

    @staticmethod
    async def get_files(project: Project) -> list[File]:
        project_files = project.files
        return project_files

    @staticmethod
    async def copy_project(
        old_project: Project,
        new_project: Project,
        db: AsyncSession,
    ) -> None:
        """
        复制项目(模板)项目的文件到新项目(模板)
        """
        old_files = await ProjectDAO.get_files(old_project)

        # 复制文件
        for old_file in old_files:
            new_file = await FileDAO.copy_file(
                source_file=old_file,
                target_project=new_project,
                target_file_create_update=FileCreateUpdate(
                    filename=old_file.filename,
                    filepath=old_file.filepath,
                ),
                db=db,
            )
            logger.info(f"Copied file {old_file.filename} to {new_file.filename}")
