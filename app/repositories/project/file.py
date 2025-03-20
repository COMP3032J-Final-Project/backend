import uuid
from typing import Any, List, Optional, Type

from app.core.config import settings
from app.models.project.file import File
from app.models.project.project import (Project, ProjectCreate,
                                        ProjectPermission, ProjectUpdate,
                                        ProjectUser)
from core.r2client import r2client
# from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

# from app.models.user import User
# from sqlalchemy.exc import IntegrityError


class FileDAO:
    @staticmethod
    async def get_file_by_id(file_id: uuid.UUID, db: AsyncSession) -> Optional[File]:
        return await db.get(File, file_id)

    # WIP
    # @staticmethod
    # async def pull_file_from_remote(file: File) -> file:
    #     r2client.get_object()
