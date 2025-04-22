# 用于管理应用的生命周期事件，包括启动事件和关闭事件，以及配置中间件、路由和全局异常处理等
from app.api.deps import get_db
from app.api.endpoints.project.crdt_handler import crdt_handler
from app.api.endpoints.project.websocket_handlers import \
    project_general_manager
from app.api.router import router
from app.models.base import Base
from app.seed.default_admin import create_default_admin
from app.seed.template_project import create_template_projects
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .compile import MyHandler
from .config import settings
from .db import engine

observer: Observer | None = None


async def startup_handler() -> None:
    """
    应用启动时的处理函数
    """
    # 在应用启动时创建所有表格
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await project_general_manager.initialize()
    await crdt_handler.initialize()

    async for db in get_db():
        await create_default_admin(db)
        await create_template_projects(db)

    # Create observer and event handler
    observer = Observer()
    event_handler = MyHandler()
    # Set up observer to watch a specific directory
    directory_to_watch = settings.TEMP_PATH
    observer.schedule(event_handler, directory_to_watch, recursive=True)

    # Start the observer
    observer.start()


async def shutdown_handler() -> None:
    """
    应用关闭时的处理函数
    """
    await project_general_manager.cleanup()
    await crdt_handler.cleanup()

    if observer:
        observer.stop()
        observer.join()


def configure_middleware(app: FastAPI) -> None:
    """
    配置中间件
    """
    # CORS中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin).strip("/") for origin in settings.CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 可信主机中间件
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])  # 生产环境需要配置具体的允许域名


def configure_routers(app: FastAPI) -> None:
    """
    配置路由
    """
    # 注册API路由
    app.include_router(router, prefix=settings.API_STR)


def configure_exception_handlers(app: FastAPI) -> None:
    """
    配置全局异常处理
    """

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        # 全局异常处理
        return JSONResponse(
            status_code=500,
            content={
                "code": 500,
                "data": None,
                "msg": str(exc) if settings.DEBUG else "Internal Server Error",
            },
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        # HTTP异常处理
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.status_code,
                "data": None,
                "msg": exc.detail,
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def starlette_http_exception_handler(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.status_code,
                "data": None,
                "msg": exc.detail,
            },
        )
