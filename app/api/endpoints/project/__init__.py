from fastapi import APIRouter

# 导入子模块路由
from . import file, project, websocket, member, chat

router = APIRouter()

router.include_router(project.router, tags=["项目管理"])

router.include_router(
    file.router,
    prefix="/{project_id:uuid}/files",
    tags=["项目文件"],
)

router.include_router(
    websocket.router,
    prefix="/{project_id:uuid}/ws",
    tags=["websocket"],
)

router.include_router(
    member.router,
    prefix="/{project_id:uuid}/members",
    tags=["项目成员"],
)

router.include_router(
    chat.router,
    prefix="/{project_id:uuid}/chat",
    tags=["项目群聊"],
)

