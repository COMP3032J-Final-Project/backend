from typing import Annotated

from fastapi import APIRouter, Path, Depends, WebSocket, WebSocketDisconnect, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_current_project, get_db, get_current_user_ws
from app.core.websocket import dumb_broadcaster, cursor_tracking_broadcaster, chatroom_manager
from app.models.project.project import Project
from app.models.user import User
from app.repositories.project.chat import ChatDAO
import typing

router = APIRouter()


@router.websocket("/cursor")
async def cursor(
    websocket: WebSocket,
    project_id = Path(..., description="The ID of the project")
):
    await websocket.accept()
    channel = f"proj:{project_id}/cursor"
    fake_user_id = str(hash(websocket))
    await cursor_tracking_broadcaster.connect(fake_user_id, websocket)
    await cursor_tracking_broadcaster.subscribe_client_to_channel(fake_user_id, channel)

    try:
        while True:
            message = await websocket.receive_text()
            await cursor_tracking_broadcaster.send_message(channel, message, fake_user_id)
    except WebSocketDisconnect:
        await cursor_tracking_broadcaster.disconnect(fake_user_id)


@router.websocket("/crdt")
async def crdt(
    websocket: WebSocket,
    current_user: Annotated[User, Depends(get_current_user_ws)],
    current_project: Annotated[Project, Depends(get_current_project)],
):
    await websocket.accept()
    channel_name = f"{str(current_project.id)}/doc1"
    # TODO handle one user many connection situation (just like typst.app)
    client_id = str(current_user.username)
    await dumb_broadcaster.connect(client_id, websocket)
    await dumb_broadcaster.subscribe_client_to_channel(client_id, channel_name)

    try:
        while True:
            data = await websocket.receive()
            websocket._raise_on_disconnect(data)
            try:
                message = typing.cast(str, data["text"])
            except KeyError:
                message = typing.cast(str, data["bytes"])
            await dumb_broadcaster.send_message(channel_name, message, client_id)
    except WebSocketDisconnect:
        await dumb_broadcaster.disconnect(client_id)


@router.websocket("/chat")
async def chat(
    websocket: WebSocket,
    current_user: Annotated[User, Depends(get_current_user_ws)],
    current_project: Annotated[Project, Depends(get_current_project)],
):

    try:
        current_chat_room = current_project.chat_room
        current_channel = str(current_chat_room.id)
        current_client_id = str(current_user.id)
    except AttributeError:
        return

    # 接收连接
    await websocket.accept()
    await chatroom_manager.connect(current_client_id, websocket)
    await chatroom_manager.subscribe_client_to_channel(current_client_id, current_channel)

    try:
        while True:
            message = await websocket.receive_text()
            await chatroom_manager.send_message(current_channel, message, current_client_id)
    except WebSocketDisconnect:
        await chatroom_manager.disconnect(current_client_id)
