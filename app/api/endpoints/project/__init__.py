import anyio
from fastapi import (
    APIRouter, WebSocket, WebSocketDisconnect, Depends, Path, Request
)
from fastapi.responses import HTMLResponse
from starlette.templating import Jinja2Templates
from . import file

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
