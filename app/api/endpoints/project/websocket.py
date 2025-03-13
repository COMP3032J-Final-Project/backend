from fastapi import APIRouter, Path, Depends, WebSocket, WebSocketDisconnect
from lib.pubsub import CRDTManager
from app.core.config import settings
from app.core.websocket import crdt_manager

router = APIRouter()

@router.websocket("/crdt")
async def crdt(
    websocket: WebSocket,
    project_id: str = Path(..., description="The ID of the project")
):
    await websocket.accept()
    fake_user_id = str(hash(websocket))
    await crdt_manager.connect(fake_user_id, websocket)
    await crdt_manager.subscribe_client_to_channel("user1", "doc1")

    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"Message text was: {data}")
    except WebSocketDisconnect:
        await crdt_manager.disconnect(fake_user_id)
        pass
