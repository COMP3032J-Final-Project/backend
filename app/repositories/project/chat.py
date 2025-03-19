import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project.chat import ChatMessage, ChatRoom, ChatMessageType, ChatRoomUpdate
from app.models.user import User


class ChatDAO:
    @staticmethod
    async def create_chat_room(
        name: str,
        project_id: uuid.UUID,
        db: AsyncSession,
    ) -> ChatRoom:
        """
        创建聊天室
        """
        chat_room = ChatRoom(
            name=name+" Chat Room",
            project_id=project_id,
        )
        db.add(chat_room)
        await db.commit()
        await db.refresh(chat_room)
        return chat_room

    @staticmethod
    async def update_chat_room(
        chat_room: ChatRoom,
        chat_room_update: ChatRoomUpdate,
        db: AsyncSession,
    ):
        update_data = chat_room_update.model_dump(exclude_unset=True, exclude_none=True)
        for field in update_data:
            setattr(chat_room, field, update_data[field])
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            return None
        await db.refresh(chat_room)
        return chat_room

    @staticmethod
    async def create_chat_message(
        message_type: ChatMessageType,
        content: str,
        room_id: uuid.UUID,
        sender_id: uuid.UUID,
        db: AsyncSession,
    ) -> ChatMessage:
        """
        创建消息
        """
        chat_message = ChatMessage(
            message_type=message_type,
            content=content,
            room_id=room_id,
            sender_id=sender_id,
        )
        db.add(chat_message)
        await db.commit()
        await db.refresh(chat_message)
        return chat_message
