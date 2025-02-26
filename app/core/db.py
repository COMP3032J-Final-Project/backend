# 用于创建异步引擎和异步会话工厂
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker
)
from app.core.config import settings

# 创建异步数据库引擎
engine = create_async_engine(
    settings.sqlalchemy_database_uri,
    echo=settings.DEBUG,  # 是否输出SQL语句
    future=True,  # 使用异步查询
    pool_pre_ping=True,  # 检查连接是否有效
    pool_size=5,  # 连接池大小
    max_overflow=10,  # 连接池溢出大小
)

# 创建异步会话工厂
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession, # 使用异步会话
    expire_on_commit=False, # 提交后不过期
    autocommit=False, # 自动提交
    autoflush=False, # 自动刷新
)
