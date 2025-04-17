import uuid
from typing import Optional

from loguru import logger

from app.models.project.file import File, FileCreateUpdate
from app.models.project.project import (
    MemberCreateUpdate,
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
from sqlmodel import select, delete
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
    async def get_all_projects(user: User, db: AsyncSession, type: ProjectType | None = None) -> list[Project]:
        """
        获取当前用户的所有项目(模板)
        """
        if type is None:
            query = select(Project).join(ProjectUser).where(ProjectUser.user_id == user.id)
        else:
            query = select(Project).join(ProjectUser).where(ProjectUser.user_id == user.id, Project.type == type)
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_own_projects(user: User, db: AsyncSession) -> list[Project]:
        """
        获取当前用户为owner的所有项目
        """
        query = (
            select(Project)
            .join(ProjectUser)
            .where(
                Project.type == ProjectType.PROJECT,
                ProjectUser.user_id == user.id,
                ProjectUser.permission == ProjectPermission.OWNER,
            )
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_shared_projects(user: User, db: AsyncSession) -> list[Project]:
        """
        获取当前用户被邀请参与的所有项目
        """
        query = (
            select(Project)
            .join(ProjectUser)
            .where(
                Project.type == ProjectType.PROJECT,
                ProjectUser.user_id == user.id,
                ProjectUser.permission != ProjectPermission.NON_MEMBER,
                ProjectUser.permission != ProjectPermission.OWNER,
            )
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_public_templates(db: AsyncSession) -> list[Project]:
        """
        获取所有公开的模板
        """
        query = select(Project).where(Project.type == ProjectType.TEMPLATE, Project.is_public == True)
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_favorite_templates(user: User, db: AsyncSession) -> list[ProjectInfo]:
        query = (
            select(Project)
            .join(ProjectUser)
            .where(
                Project.type == ProjectType.TEMPLATE, ProjectUser.user_id == user.id, ProjectUser.is_favorite == True
            )
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_project_info(project: Project, db: AsyncSession, user: User | None = None) -> ProjectInfo:
        """
        包装项目信息(通过是否传入user来决定是否包装is_favorite)
        """
        owner = await ProjectDAO.get_project_owner(project, db)
        owner_info = OwnerInfo.model_validate(owner)
        members_num = len(await ProjectDAO.get_members(project, db))

        project_info = ProjectInfo.model_validate(project)
        project_info.owner = owner_info
        project_info.members_num = members_num

        # 模板信息
        if project.type == ProjectType.TEMPLATE:
            project_info.favorite_num = await ProjectDAO.get_favorite_num(project, db)
            if user is not None:
                project_info.is_favorite = await ProjectDAO.is_template_favorite(project, user, db)

        project_info = project_info.model_dump(exclude_unset=True, exclude_none=True)
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
        project_user = result.scalar_one_or_none()
        if project_user is None or project_user.permission == ProjectPermission.NON_MEMBER:
            return False
        return True

    @staticmethod
    async def is_non_member(project: Project, user: User, db: AsyncSession) -> bool:
        """
        判断用户是否为被数据库记录为非成员(并非所有非成员都会被记录)
        """
        return await ProjectDAO.get_project_permission(project, user, db) == ProjectPermission.NON_MEMBER

    @staticmethod
    async def get_members(
        project: Project,
        db: AsyncSession,
    ) -> list[User]:
        query = (
            select(User)
            .join(ProjectUser)
            .where(ProjectUser.project_id == project.id, ProjectUser.permission != ProjectPermission.NON_MEMBER)
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def add_member(
        member_create: MemberCreateUpdate,
        project: Project,
        user: User,
        db: AsyncSession,
    ) -> None:
        project_user = ProjectUser(project_id=project.id, user_id=user.id)

        create_data = member_create.model_dump(exclude_unset=True, exclude_none=True)
        for field in create_data:
            setattr(project_user, field, create_data[field])

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
        member_update: MemberCreateUpdate,
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

        update_data = member_update.model_dump(exclude_unset=True, exclude_none=True)
        for field in update_data:
            setattr(project_user, field, update_data[field])

        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            return None
        await db.refresh(project_user)
        return project_user

    @staticmethod
    async def remove_non_members(project: Project, db: AsyncSession) -> None:
        delete_query = delete(ProjectUser).where(
            ProjectUser.project_id == project.id,
            ProjectUser.permission == ProjectPermission.NON_MEMBER,
        )
        await db.execute(delete_query)
        await db.commit()

    @staticmethod
    async def is_template_favorite(project: Project, user: User, db: AsyncSession) -> bool:
        query = select(ProjectUser).where(
            ProjectUser.project_id == project.id,
            ProjectUser.user_id == user.id,
        )
        result = await db.execute(query)
        project_user = result.scalar_one_or_none()

        try:
            return project_user.is_favorite
        except AttributeError:
            return False

    @staticmethod
    async def get_favorite_num(project: Project, db: AsyncSession) -> int:
        query = select(ProjectUser).where(
            ProjectUser.project_id == project.id,
            ProjectUser.is_favorite == True,
        )
        result = await db.execute(query)
        return len(result.scalars().all())

    @staticmethod
    async def get_files(project: Project) -> list[File]:
        project_files = project.files
        return project_files

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
            # 这样其实应该就可以了
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
