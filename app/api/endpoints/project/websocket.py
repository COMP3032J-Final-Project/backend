from fastapi import APIRouter, Path, Depends, WebSocket, WebSocketDisconnect
from app.core.config import settings
from app.core.websocket import dumb_broadcaster
import json

router = APIRouter()

@router.websocket("/cursor")
async def cursor(
    websocket: WebSocket,
    project_id: str = Path(..., description="The ID of the project")
):
    await websocket.accept()
    channel = f"proj:{project_id}/cursor"
    fake_user_id = str(hash(websocket))
    await dumb_broadcaster.connect(fake_user_id, websocket)
    await dumb_broadcaster.subscribe_client_to_channel(
        fake_user_id, channel
    )

    try:
        while True:
            message = await websocket.receive_text()
            await dumb_broadcaster.send_message(channel, message, fake_user_id)
    except WebSocketDisconnect:
        await dumb_broadcaster.disconnect(fake_user_id)
        pass


@router.websocket("/crdt")
async def crdt(
    websocket: WebSocket,
    project_id: str = Path(..., description="The ID of the project")
):
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
