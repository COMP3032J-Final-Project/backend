# 用于自定义 SQLModel 基础模型类
import uuid
from datetime import datetime

from sqlmodel import SQLModel, Field


class Base(SQLModel, table=False):
    """
    sqlmodel 基础模型类
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    class Config:
        json_encoders = {
            datetime: lambda v: v.strftime("%Y-%m-%d %H:%M:%S")
        }


class Message(Base):
    """
    消息模型
    """
    message: str
