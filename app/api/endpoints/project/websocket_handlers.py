from aspubsub import GeneralPurposePubSubManager
from loguru import logger
from typing import override, Any, Union
import asyncio
import orjson
from app.core.config import settings
from app.core.db import async_session
from app.repositories.project.project import ProjectDAO
from uuid import UUID

from pydantic import ValidationError
from app.models.project.websocket import (
    Message, EventScope,
    WrongInputMessageFormatErrorStr
)

def get_project_channel_name(project_id: Union[str, UUID]):
    return f"project/{project_id}"

class ProjectGeneralManager(GeneralPurposePubSubManager):
    """Project General Manager.
    NOTE Channel name should start with `project/`"""
    def __init__(self, url: str, **kwargs):
       super().__init__(url, **kwargs)

    @override
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


    @override
    async def dispatch_message(self, concrete_channel: str, message: str):
        recipient_client_ids = list(await self._get_client_ids_subscribed_to_channel(concrete_channel))

        if not recipient_client_ids:
            return

        message_json = orjson.loads(message)
        client_id = message_json['client_id']
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
            # TODO chat message implementation
            pass
                 
        if send_tasks:
            results = await asyncio.gather(*send_tasks, return_exceptions=True)
            for i, result in enumerate(results):
                 if isinstance(result, Exception):
                      failed_client_id = recipient_client_ids[i]
                      logger.error(f"Error sending message to client {failed_client_id} for channel {concrete_channel}: {result}")

   
project_general_manager = ProjectGeneralManager(settings.PUB_SUB_BACKEND_URL)
