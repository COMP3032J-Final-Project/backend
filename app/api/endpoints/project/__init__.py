from fastapi import (
    APIRouter, WebSocket, Depends, Path
)

from .lib import validate_project_id
from . import file, websocket

router = APIRouter()


router.include_router(
    file.router,
    prefix="/{project_id}/files", 
    tags=["项目文件"],
    dependencies=[Depends(validate_project_id)]
)

router.include_router(
    websocket.router,
    prefix="/{project_id}/ws", 
    tags=["websocket"],
    dependencies=[Depends(validate_project_id)]
)


@router.get("/{project_id}", tags=["项目信息"])
async def get_project(project_id: str = Depends(validate_project_id)):
    return {"project_id": project_id}


