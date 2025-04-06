import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, List, Dict

from sqlmodel import Field, Relationship

from app.models.base import BaseDB, Base

if TYPE_CHECKING:
    from app.models.project.project import Project
    from app.models.user import User


class ChatMessageType(str, Enum):
    """
    聊天消息类型枚举
    """

    TEXT = "text"
    JOIN = "join"
    LEAVE = "leave"
    IMAGE = "image"
    SYSTEM = "system"
    # FILE = "file"


class ChatRoom(BaseDB, table=True):
    """
    聊天室模型
    """

    __tablename__ = "chat_rooms"

    name: str = Field(
        ...,
        max_length=255,
        sa_column_kwargs={"index": True, "nullable": False},
    )
    project_id: uuid.UUID = Field(
        ...,
        foreign_key="projects.id",
        sa_column_kwargs={
            "nullable": False,
            "unique": True,  # one project one chat room
            "index": True,
        },
    )

    project: "Project" = Relationship(back_populates="chat_room")
    chat_messages: list["ChatMessage"] = Relationship(
        back_populates="chat_room",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "lazy": "selectin"},
    )

    def __repr__(self):
        return f"<ChatRoom name={self.name} project_id={self.project_id}>"


class ChatMessage(BaseDB, table=True):
    """
    聊天消息模型
    """

    __tablename__ = "chat_messages"

    message_type: ChatMessageType = Field(
        default=ChatMessageType.TEXT,
        sa_column_kwargs={"nullable": False},
    )
    content: str = Field(
        ...,
        max_length=1000,
        sa_column_kwargs={"nullable": False},
    )
    room_id: uuid.UUID = Field(
        ...,
        foreign_key="chat_rooms.id",
        sa_column_kwargs={
            "nullable": False,
            "index": True,
        },
    )
    sender_id: uuid.UUID = Field(
        ...,
        foreign_key="users.id",
        sa_column_kwargs={
            "nullable": False,
            "index": True,
        },
    )

    chat_room: "ChatRoom" = Relationship(back_populates="chat_messages")
    sender: "User" = Relationship()

    def __repr__(self):
        return (
            f"<ChatMessage message_type={self.message_type} content={self.content} "
            f"room_id={self.room_id} sender_id={self.sender_id}>"
        )


class ChatRoomUpdate(Base):
    name: str | None = Field(default=None, max_length=255)


class ChatMessageData(Base):
    """
    聊天消息数据模型
    """

    message_type: ChatMessageType = Field(
        default=ChatMessageType.TEXT,
        sa_column_kwargs={"nullable": False},
    )
    content: str = Field(
        ...,
        max_length=1000,
        sa_column_kwargs={"nullable": False},
    )
    timestamp: datetime = Field(
        ...,
        sa_column_kwargs={"nullable": False},
    )
    user: Dict[str, str] = Field(
        ...,
        sa_column_kwargs={"nullable": False},
    )
