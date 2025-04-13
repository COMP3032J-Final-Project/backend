from datetime import datetime
from typing import Annotated, Optional, List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_current_project, get_db
from app.models.base import APIResponse
from app.models.project.chat import ChatRoomUpdate, ChatMessageInfo
from app.models.project.project import Project
from app.models.user import User
from app.repositories.project.chat import ChatDAO
from app.repositories.project.project import ProjectDAO
from app.repositories.user import UserDAO

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
    is_owner = await ProjectDAO.is_project_owner(current_project, current_user, db)
    if not is_admin and not is_owner:
        return APIResponse(code=403, msg="No permission to update this project")

    updated_chat_room = await ChatDAO.update_chat_room(current_project.chat_room, chat_room_update, db)
    if updated_chat_room is None:
        return APIResponse(code=400, msg="Failed to update chat room")
    return APIResponse(code=200, data=updated_chat_room, msg="success")


@router.get("/history", response_model=APIResponse[List[ChatMessageInfo]])
async def get_chat_history(
    current_user: Annotated[User, Depends(get_current_user)],
    current_project: Annotated[Project, Depends(get_current_project)],
    db: Annotated[AsyncSession, Depends(get_db)],
    max_num: int,
    last_timestamp: Optional[str] = None,
) -> APIResponse[List[ChatMessageInfo]]:
    """获取聊天室历史消息"""
    is_member = await ProjectDAO.is_project_member(current_project, current_user, db)
    if not is_member:
        return APIResponse(code=403, msg="No permission to access this project")

    # 检查参数
    if max_num <= 0 or max_num > 100:
        return APIResponse(code=400, msg="max_num must be between 1 and 100")
    if last_timestamp:
        try:
            last_timestamp = datetime.fromisoformat(last_timestamp)
        except ValueError:
            return APIResponse(code=400, msg="Invalid timestamp format")

    # 包装消息
    current_chat_room = current_project.chat_room
    messages, has_more = await ChatDAO.get_history_messages(current_chat_room, max_num, db, last_timestamp)
    history_messages = []
    for message in messages:
        user = await UserDAO.get_user_by_id(message.sender_id, db)
        chat_message = ChatMessageInfo(
            message_type=message.message_type,
            content=message.content,
            timestamp=message.created_at,
            user={
                "id": str(message.sender_id),
                "username": user.username,
                "email": user.email,
            },
        )
        history_messages.append(chat_message)

    if has_more:
        return APIResponse(code=200, data=history_messages, msg="success")
    else:
        return APIResponse(code=201, data=history_messages, msg="no more messages")
