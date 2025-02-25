import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
# pydantic 是 FastAPI 的依赖，是一个数据验证库, 用于数据验证, 也可以用于数据转换
from pydantic import BaseModel
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import DeclarativeMeta, declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

from app.core.config import settings
from app.core.events import (
    startup_handler,
    shutdown_handler,
    configure_middleware,
    configure_routers,
    configure_exception_handlers,
)

load_dotenv()


@asynccontextmanager  # 异步上下文管理器, 用于管理异步上下文
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """
    应用生命周期管理
    """
    # 启动事件
    await startup_handler()
    yield
    # 关闭事件
    await shutdown_handler()


def create_app() -> FastAPI:
    """
    工厂函数: 创建FastAPI应用实例
    """
    app = FastAPI(
        title=settings.PROJECT_NAME,
        description=settings.PROJECT_DESCRIPTION,
        version=settings.VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # 配置中间件
    configure_middleware(app)
    # 配置路由
    configure_routers(app)
    # 配置异常处理
    configure_exception_handlers(app)

    return app


app = create_app()
