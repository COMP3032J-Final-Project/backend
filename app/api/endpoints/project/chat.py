from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_current_project, get_db
from app.models.base import APIResponse
from app.models.project.chat import ChatRoomUpdate
from app.models.project.project import Project
from app.models.user import User
from app.repositories.project.chat import ChatDAO
from app.repositories.project.project import ProjectDAO

router = APIRouter()


@router.put("/", response_model=APIResponse[ChatRoomUpdate])
async def update_chat_room(
    chat_room_update: ChatRoomUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    current_project: Annotated[Project, Depends(get_current_project)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIResponse[ChatRoomUpdate]:
    """更新聊天室信息"""
    is_admin = await ProjectDAO.is_project_admin(current_project, current_user, db)
    is_owner = await ProjectDAO.is_project_owner(current_project, current_user)
    if not is_admin and not is_owner:
        return APIResponse(code=403, msg="No permission to update this project")

    updated_chat_room = await ChatDAO.update_chat_room(current_project.chat_room, chat_room_update, db)
    return APIResponse(code=200, data=updated_chat_room, msg="success")
