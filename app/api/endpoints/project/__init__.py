from fastapi import (
    APIRouter, WebSocket, Depends, Path
)
from . import file
from lib.pubsub import CRDTManager
from app.core.config import settings

router = APIRouter()

async def validate_project_id(
    project_id: str = Path(..., description="The ID of the project")
):
    return project_id

router.include_router(
    file.router,
    prefix="/{project_id}/files", 
    tags=["项目文件"],
    dependencies=[Depends(validate_project_id)]
)


@router.get("/{project_id}", tags=["项目信息"])
async def get_project(project_id: str = Depends(validate_project_id)):
    return {"project_id": project_id}


@router.websocket("/{project_id}/crdt_ws")
async def crdt(
    websocket: WebSocket,
    project_id: str = Depends(validate_project_id)
):
    # NOTE place initialize and clean_up inside fastapi setup/shutdown hook
    manager = CRDTManager(settings.PUB_SUB_BACKEND_URL)
    await websocket.accept()
        
    while True:
        data = await websocket.receive_text()
        await websocket.send_text(f"Message text was: {data}")

