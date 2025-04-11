from datetime import datetime
import uuid
from aspubsub import GeneralPurposePubSubManager
from loguru import logger

# from typing import override, Any, Union
from typing import Any, Union
import asyncio
import orjson
from app.core.config import settings
from app.core.db import async_session
from uuid import UUID

from pydantic import ValidationError
from app.models.project.chat import ChatMessageData, ChatMessageType
from app.models.project.websocket import (
    ChatAction,
    Message,
    EventScope,
    ObjectNotFoundErrorStr,
    WrongInputMessageFormatErrorStr,
)
from app.repositories.project.chat import ChatDAO
from app.repositories.project.project import ProjectDAO
from app.repositories.user import UserDAO


def get_project_channel_name(project_id: Union[str, UUID]):
    return f"project/{project_id}"


def get_project_id(channel_name: str) -> uuid.UUID:
    return uuid.UUID(channel_name.split("/")[-1])


class ProjectGeneralManager(GeneralPurposePubSubManager):
    """Project General Manager.
    NOTE Channel name should start with `project/`"""

    def __init__(self, url: str, **kwargs):
        super().__init__(url, **kwargs)

    # @override
    async def publish(self, channel: str, message: Any):
        if not channel.startswith("project/"):
            raise Exception("Cannot handle channel whose name doesn't start with `project/`")
        await self.psb.publish(channel, message)

    async def send_to_client(self, client_id: str, message: str):
        conn = self.client_connection.get(client_id)
        if conn:
            try:
                await conn.send_text(message)
            except Exception as e:
                logger.error(f"Failed to send message to client {client_id}: {e}")
        else:
            logger.warning(f"Attempted to send message to client {client_id}, but connection object was missing.")

    # @override
    async def dispatch_message(self, concrete_channel: str, message: str):
        recipient_client_ids = list(await self._get_client_ids_subscribed_to_channel(concrete_channel))

        if not recipient_client_ids:
            return

        message_json = orjson.loads(message)
        client_id = message_json["client_id"]
        try:
            parsed_message = Message(**message_json)
        except ValidationError:
            await self.send_to_client(client_id, WrongInputMessageFormatErrorStr)
            return

        send_tasks = []
        if parsed_message.scope != EventScope.CHAT:
            # just broadcast message
            for cid in recipient_client_ids:
                # client is possible disconnected in this short time period
                if cid in self.client_connection:
                    send_tasks.append(self.send_to_client(cid, message))
        else:
            payload = parsed_message.payload
            if not payload:
                await self.send_to_client(client_id, WrongInputMessageFormatErrorStr)
                return

            message_type = payload.get("message_type")
            content = payload.get("content")
            message_type = ChatMessageType(message_type)
            current_time = datetime.now()

            if not message_type or not content:
                await self.send_to_client(client_id, WrongInputMessageFormatErrorStr)
                return

            # 获取用户信息和项目信息
            async with async_session() as db:
                user = await UserDAO.get_user_by_id(uuid.UUID(client_id), db)
                project = await ProjectDAO.get_project_by_id(get_project_id(concrete_channel), db)
                if not user or not project:
                    await self.send_to_client(client_id, ObjectNotFoundErrorStr)
                    return

                # 创建聊天消息数据
                user_info = {"id": str(user.id), "username": user.username, "email": user.email}
                chat_message = ChatMessageData(
                    message_type=message_type, content=content, timestamp=current_time, user=user_info
                )

                # 将消息保存到数据库
                try:
                    await ChatDAO.create_chat_message(
                        message_type=message_type,
                        content=content,
                        room_id=project.chat_room.id,
                        sender_id=uuid.UUID(client_id),
                        created_at=current_time,
                        db=db,
                    )
                    logger.info(f"Chat message from {client_id} stored in database")
                except Exception as e:
                    logger.error(f"Failed to store chat message: {e}")
                    return

                sent_message = Message(
                    client_id=client_id,
                    scope=EventScope.CHAT,
                    action=ChatAction.SEND_MESSAGE,
                    payload=chat_message.model_dump(mode="json"),
                )

                # 广播消息给所有客户端
                # just broadcast message
                for cid in recipient_client_ids:
                    # client is possible disconnected in this short time period
                    if cid in self.client_connection:
                        send_tasks.append(self.send_to_client(cid, sent_message.model_dump_json()))

        if send_tasks:
            results = await asyncio.gather(*send_tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    failed_client_id = recipient_client_ids[i]
                    logger.error(
                        f"Error sending message to client {failed_client_id} for channel {concrete_channel}: {result}"
                    )


project_general_manager = ProjectGeneralManager(settings.PUB_SUB_BACKEND_URL)
