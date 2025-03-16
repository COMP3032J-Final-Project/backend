from fastapi import APIRouter, Depends

from app.api.deps import get_current_project

# 导入子模块路由
from . import file, project, websocket, member

router = APIRouter()

router.include_router(project.router, tags=["项目管理"])

router.include_router(
    file.router,
    prefix="/{project_id:uuid}/files",
    tags=["项目文件"],
    dependencies=[Depends(get_current_project)],
)

router.include_router(
    websocket.router,
    prefix="/{project_id:uuid}/ws",
    tags=["websocket"],
    dependencies=[Depends(get_current_project)],
)

# 注册成员管理相关路由
router.include_router(
    member.router,
    prefix="/{project_id:uuid}/members",
    tags=["项目成员"],
)
