# 用于配置FastAPI应用程序的设置
import logging
import os
import secrets
from typing import List

from dotenv import load_dotenv
from pydantic import AnyHttpUrl
from pydantic_settings import BaseSettings
from pathlib import Path

logger = logging.getLogger("uvicorn.error")

load_dotenv()


class Settings(BaseSettings):
    # 基础配置
    PROJECT_NAME: str = "Hivey Backend"
    PROJECT_DESCRIPTION: str = "Hivey Backend"
    VERSION: str = "0.0.1"
    API_STR: str = ""  # API路径
    DEBUG: bool = True  # 调试模式

    # FastAPI服务器配置
    SERVER_HOST: str = os.getenv("SERVER_HOST", "0.0.0.0")
    SERVER_PORT: int = int(os.getenv("SERVER_PORT", 8000))
    SERVER_WORKERS: int = int(os.getenv("SERVER_WORKERS", 4))

    # 安全配置
    SECRET_KEY: str = secrets.token_urlsafe(32)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 30  # 30 days

    # CORS配置
    CORS_ORIGINS: List[AnyHttpUrl] = []

    # 数据库配置
    USE_SQLITE: bool = os.getenv("HIVEY_B_USE_SQLITE", "false").lower() == "true"
    DB_NAME: str = os.getenv("HIVEY_B_DB_NAME", "hivey")
    DB_USERNAME: str = os.getenv("HIVEY_B_DB_USERNAME", "mysql")
    DB_PASSWORD: str = os.getenv("HIVEY_B_DB_PASSWORD", "password")
    DB_HOST: str = os.getenv("HIVEY_B_DB_HOST", "localhost")
    DB_PORT: str = os.getenv("HIVEY_B_DB_PORT", "3306")

    PUB_SUB_BACKEND_URL: str = os.getenv("HIVEY_B_PUB_SUB_BACKEND_URL", "memory://").strip()
    CRDT_HANDLER_BACKEND_URL: str = os.getenv("HIVEY_B_CRDT_HANDLER_BACKEND_URL", "memory://").strip()

    # 管理员
    ADMIN_EMAIL: str = os.getenv("HIVEY_B_ADMIN_EMAIL", "admin@example.com")
    ADMIN_USERNAME: str = os.getenv("HIVEY_B_ADMIN_EMAIL", "admin@example.com")
    ADMIN_PASSWORD: str = os.getenv("HIVEY_B_ADMIN_EMAIL", "password")

    # Cloudflare R2 文件服务
    R2_ENDPOINT_URL: str = os.getenv("HIVEY_B_R2_ENDPOINT_URL", "")
    R2_ACCESS_KEY: str = os.getenv("HIVEY_B_R2_ACCESS_KEY", "")
    R2_SECRET: str = os.getenv("HIVEY_B_R2_SECRET", "")
    R2_BUCKET: str = os.getenv("HIVEY_B_R2_BUCKET", "hivey-files")

    TEMP_PATH: Path = Path(os.path.normpath(os.getenv("HIVEY_B_TEMP_PATH", "./temp")))

    TEMP_PROJECTS_PATH: Path = TEMP_PATH / "projects"

    try:
        os.mkdir(TEMP_PATH)
        logger.info(f"Directory '{TEMP_PATH}' created successfully.")
    except FileExistsError:
        logger.error(f"Directory '{TEMP_PATH}' already exists.")
    except PermissionError:
        logger.error(f"Permission denied: Unable to create '{TEMP_PATH}'.")
    except Exception as e:
        logger.error(f"An error occurred: {e}")

    @property
    def sqlalchemy_database_uri(self) -> str:
        if self.USE_SQLITE:
            return f"sqlite+aiosqlite:///./hivey.db"
        return f"mysql+aiomysql://{self.DB_USERNAME}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    model_config = {"case_sensitive": True, "env_file": ".env", "env_prefix": "HIVEY_B_"}


# 创建设置实例
settings = Settings()
