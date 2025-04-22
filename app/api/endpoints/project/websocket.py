from typing import Annotated
import uuid
import orjson

from fastapi import APIRouter, Depends, Path, WebSocket, WebSocketDisconnect
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_current_project, get_db, get_current_user_ws
from app.models.project.project import MemberInfo, Project, ProjectPermission
from app.models.user import User
from app.repositories.project.project import ProjectDAO
from app.repositories.user import UserDAO
from loguru import logger

from pydantic import ValidationError
from app.models.project.websocket import (
    ClientMessage,
    BaseMessage,
    Message,
    EventScope,
    MemberAction,
    WrongInputMessageFormatErrorStr,
    ScopeNotAllowedErrorStr,
)
from .websocket_handlers import project_general_manager, get_project_channel_name

router = APIRouter()


@router.websocket("/")
async def project(
    websocket: WebSocket,
    current_user: Annotated[User, Depends(get_current_user_ws)],
    db: AsyncSession = Depends(get_db),
    project_id: uuid.UUID = Path(...),
):
    """This endpoint handles all websocket stuffs related to a single project.
    The all in one manner greatly reduces the websocket connection number."""
    current_project = await get_current_project(current_user, project_id, db)

    await websocket.accept()

    member_info = MemberInfo(
        user_id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        permission=await ProjectDAO.get_project_permission(current_project, current_user, db),
    )

    # connect user to this project channel
    client_id = str(current_user.id)
    channel = get_project_channel_name(current_project.id)
    try:
        await project_general_manager.subscribe(client_id, channel, websocket)

        # get all connected client ids in this channel
        channel_client_ids = await project_general_manager._get_client_ids_subscribed_to_channel(channel)
        connected_members = []

        for cid in channel_client_ids:
            user = await UserDAO.get_user_by_id(uuid.UUID(cid), db)

            is_member = await ProjectDAO.is_project_member(current_project, user, db)
            if is_member:
                permission = await ProjectDAO.get_project_permission(current_project, user, db)
            else:
                permission = ProjectPermission.NON_MEMBER

            if user:
                member = MemberInfo(
                    user_id=user.id,
                    username=user.username,
                    email=user.email,
                    permission=permission,
                    avatar_url=await UserDAO.get_avatar_url(user),
                )
                connected_members.append(member.model_dump())

        await project_general_manager.publish(
            channel,
            ClientMessage(
                client_id=client_id,
                scope=EventScope.MEMBER,
                action=MemberAction.JOINED,
                payload=connected_members,
            ).model_dump_json(),
        )
    except Exception as e:
        logger.error(f"Error connecting to project: {e}")
        await project_general_manager.disconnect(client_id)
        await websocket.close(code=4000, reason=f"Failed to connect: {str(e)}")
        return

    try:
        while True:
            raw_message = await websocket.receive_text()

            try:
                message = BaseMessage(**orjson.loads(raw_message))
            except (orjson.JSONDecodeError, ValidationError) as e:
                await websocket.send_text(WrongInputMessageFormatErrorStr)
                continue

            if message.scope in (
                EventScope.CHAT,
                EventScope.CRDT,
            ):
                await project_general_manager.publish(
                    channel, Message(client_id=client_id, **message.model_dump()).model_dump_json()
                )
            else:
                await websocket.send_text(ScopeNotAllowedErrorStr)
    except WebSocketDisconnect:
        await project_general_manager.disconnect(client_id)
        await project_general_manager.publish(
            channel,
            ClientMessage(
                client_id=client_id,
                scope=EventScope.MEMBER,
                action=MemberAction.LEFT,
                payload=member_info.model_dump(),
            ).model_dump_json(),
        )

        logger.debug(f"Client {client_id} disconnected from project {current_project.id}")
