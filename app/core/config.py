# 用于配置FastAPI应用程序的设置
import os
from typing import List

from dotenv import load_dotenv
from pydantic_settings import BaseSettings
from pydantic import AnyHttpUrl, field_validator
import secrets

load_dotenv()


class Settings(BaseSettings):
    # 基础配置
    PROJECT_NAME: str = "Hivey Backend"
    PROJECT_DESCRIPTION: str = "Hivey Backend"
    VERSION: str = "0.0.1"
    API_V1_STR: str = ""  # API路径
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
    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = []

    # 如果BACKEND_CORS_ORIGINS是字符串，将其转换为列表，以便在FastAPI中使用
    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    def assemble_cors_origins(cls, v: str | List[str]) -> List[str] | str:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, list | str):
            return v
        raise ValueError(v)

    # 数据库配置
    USE_SQLITE: bool = os.getenv("USE_SQLITE", "false").lower() == "true"
    DB_NAME: str = os.getenv("DB_NAME", "hivey")
    DB_USERNAME: str = os.getenv("DB_USERNAME", "mysql")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "password")
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: str = os.getenv("DB_PORT", "3306")

    # 默认管理员
    DEFAULT_ADMIN_EMAIL: str = "admin@example.com"
    DEFAULT_ADMIN_USERNAME: str = "admin"
    DEFAULT_ADMIN_PASSWORD: str = "password"

    @property
    def sqlalchemy_database_uri(self) -> str:
        if self.USE_SQLITE:
            return f"sqlite+aiosqlite:///./hivey.db"
        return f"mysql+aiomysql://{self.DB_USERNAME}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    # Redis配置 (用于缓存)
    # REDIS_HOST: str = "localhost"
    # REDIS_PORT: int = 6379
    # REDIS_PASSWORD: Optional[str] = None
    # REDIS_DB: int = 0

    class Config:
        case_sensitive = True
        env_file = ".env"


# 创建设置实例
settings = Settings()
