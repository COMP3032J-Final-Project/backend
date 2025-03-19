from typing import Annotated

from fastapi import APIRouter, Path, Depends, WebSocket, WebSocketDisconnect, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_current_project, get_db, get_current_user_ws
from app.core.websocket import dumb_broadcaster, cursor_tracking_broadcaster, chatroom_manager
from app.models.project.project import Project
from app.models.user import User
from app.repositories.project.chat import ChatDAO

router = APIRouter()


@router.websocket("/cursor")
async def cursor(websocket: WebSocket, project_id: str = Path(..., description="The ID of the project")):
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
        pass


@router.websocket("/crdt")
async def crdt(websocket: WebSocket, project_id: str = Path(..., description="The ID of the project")):
    await websocket.accept()
    fake_user_id = str(hash(websocket))
    await dumb_broadcaster.connect(fake_user_id, websocket)
    await dumb_broadcaster.subscribe_client_to_channel(fake_user_id, "doc1")

    try:
        while True:
            data = await websocket.receive_text()
            # await websocket.send_text(f"{fake_user_id}: {data}")
            await dumb_broadcaster.send_message("doc1", data, fake_user_id)
    except WebSocketDisconnect:
        await dumb_broadcaster.disconnect(fake_user_id)
        pass


@router.websocket("/chat")
async def chat(
    websocket: WebSocket,
    current_user: Annotated[User, Depends(get_current_user_ws)],
    current_project: Annotated[Project, Depends(get_current_project)],
    db: Annotated[AsyncSession, Depends(get_db)],
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

    # 加载历史记录 (暂时3条)
    history_messages, has_more = await ChatDAO.get_history_messages(current_chat_room, 3, db)
    for message in history_messages:
        await websocket.send_json(
            {
                "type": "history",
                "channel": current_channel,
                "from": str(message.sender_id),
                "message": message.content,
                "timestamp": message.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )

    try:
        while True:
            message = await websocket.receive_text()
            await chatroom_manager.send_message(current_channel, message, current_client_id)
    except WebSocketDisconnect:
        await chatroom_manager.disconnect(current_user.id)
        pass
