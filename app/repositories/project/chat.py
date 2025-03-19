import uuid
from datetime import datetime
from typing import Optional, Tuple, Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

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
            name=name + " Chat Room",
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
        create_at: datetime,
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
            created_at=create_at,
            updated_at=create_at,
        )
        db.add(chat_message)
        await db.commit()
        await db.refresh(chat_message)
        return chat_message

    @staticmethod
    async def get_history_messages(
        chat_room: ChatRoom,
        max_num: int,
        db: AsyncSession,
        before: Optional[datetime] = None,
    ) -> tuple[Sequence[ChatMessage], bool]:
        """
        获取before时间之前的max_num条历史消息
        """
        query = select(ChatMessage).where(ChatMessage.room_id == chat_room.id)
        if before:
            query = query.where(ChatMessage.created_at < before)

        # 查询时多取一条记录
        query = query.order_by(ChatMessage.created_at.desc()).limit(max_num + 1)
        result = await db.execute(query)
        messages = result.scalars().all()
        # 判断是否还有更多消息
        has_more = len(messages) > max_num
        if has_more:
            messages = messages[:max_num]
        return messages, has_more
