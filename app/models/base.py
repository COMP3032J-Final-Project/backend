# 用于自定义 SQLModel 基础模型类
import uuid
from datetime import datetime
from typing import Optional, Generic, TypeVar

from pydantic import ConfigDict
from sqlmodel import SQLModel, Field

DataT = TypeVar("DataT")  # 泛型类型变量


class Base(SQLModel, table=False):
    """
    基础模型类
    """

    model_config = ConfigDict(
        extra='forbid',  # 禁止额外字段
        from_attributes=True,
        json_encoders={
            datetime: lambda v: v.strftime("%Y-%m-%d %H:%M:%S")
        },
    )


class BaseDB(Base, table=False):
    """
    基础数据库模型类
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime = Field(
        default_factory=datetime.now,
        sa_column_kwargs={"index": True}
    )
    updated_at: datetime = Field(
        default_factory=datetime.now,
        sa_column_kwargs={"onupdate": datetime.now}  # 自动更新
    )


class APIResponse(Base, Generic[DataT]):
    """
    API 响应模型
    """
    code: int = 200
    data: Optional[DataT] = None
    msg: str = "success"
