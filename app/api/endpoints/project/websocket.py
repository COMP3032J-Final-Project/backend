from typing import Annotated
import logging

from fastapi import APIRouter, Path, Depends, WebSocket, WebSocketDisconnect
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_current_project, get_db, get_current_user_ws
from app.core.websocket import (
    dumb_broadcaster,
    cursor_tracking_broadcaster,
    project_general_manager,
)
from app.models.project.project import Project
from app.models.user import User
from app.repositories.project.project import ProjectDAO

router = APIRouter()
logger = logging.getLogger(__name__)


@router.websocket("/")
async def project_websocket(
    websocket: WebSocket,
    current_user: Annotated[User, Depends(get_current_user_ws)],
    current_project: Annotated[Project, Depends(get_current_project)],
    db: AsyncSession = Depends(get_db),
):
    """
    项目统一WebSocket接口 - 处理所有与项目相关的实时通信
    """
    await websocket.accept()

    # 检查用户权限
    try:
        is_member = await ProjectDAO.is_project_member(current_project, current_user, db)
        if not is_member:
            await websocket.close(code=4003, reason="No permission to access the project")
            return
    except Exception as e:
        logger.error(f"Error while checking permissions: {e}")
        await websocket.close(code=4500, reason="Server error")
        return

    # 连接项目频道
    current_client_id = str(current_user.id)
    current_channel = str(current_project.id)
    try:
        await project_general_manager.connect(current_client_id, websocket)
        await project_general_manager.subscribe_client_to_channel(current_client_id, current_channel)
        logger.info(f"User {current_client_id} connected to project {current_channel}")
    except Exception as e:
        logger.error(f"Error connecting to project: {e}")
        await project_general_manager.disconnect(current_client_id)
        await websocket.close(code=4500, reason=f"Failed to connect: {str(e)}")
        return

    try:
        while True:
            message = await websocket.receive_text()
            await project_general_manager.send_message(current_channel, message, current_client_id)
    except WebSocketDisconnect:
        await project_general_manager.disconnect(current_client_id)
        logger.info(f"Client {current_client_id} disconnected from project {current_project.id}")


@router.websocket("/cursor")
async def cursor(websocket: WebSocket, project_id=Path(..., description="The ID of the project")):
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
            data = await websocket.receive_text()
            await dumb_broadcaster.send_message(channel_name, data, client_id)
    except WebSocketDisconnect:
        await dumb_broadcaster.disconnect(client_id)


