from enum import Enum
from typing import Any, Dict, Optional

from app.models.base import Base


class EventScope(str, Enum):
    """
    事件范围
    - project: 项目
    - member: 成员
    - file: 文件
    - chat: 聊天
    - error: 错误
    """

    PROJECT = "project"
    MEMBER = "member"
    FILE = "file"
    CHAT = "chat"
    ERROR = "error"


class EventType(str, Enum):
    """事件类型"""

    # 项目相关
    PROJECT_UPDATED = "project_updated"
    PROJECT_DELETED = "project_deleted"

    # 成员相关
    MEMBER_ADDED = "member_added"
    MEMBER_UPDATED = "member_updated"
    MEMBER_REMOVED = "member_removed"
    OWNERSHIP_TRANSFERRED = "ownership_transferred"
    MEMBER_STATUS_CHANGED = "member_status_changed"

    # 文件相关
    FILE_ADDED = "file_added"
    FILE_RENAMED = "file_renamed"
    FILE_MOVED = "file_moved"
    FILE_DELETED = "file_deleted"

    # 聊天相关
    MESSAGE_SENT = "message_sent"
    MESSAGE_EDITED = "message_edited"
    MESSAGE_WITHDRAWN = "message_withdrawn"


class BroadcastErrorData(Base):
    """错误数据模型"""

    code: int
    message: str
    original_action: Optional[str] = None  # 原始action


class BroadcastMessage(Base):
    """广播消息模型"""

    event_type: Optional[EventType]
    event_scope: Optional[EventScope]
    channel: Optional[str] = None
    client_id: Optional[str] = None
    data: Dict[str, Any]


class BroadcastErrorMessage(BroadcastMessage):
    """错误消息模型"""

    event_scope: EventScope = EventScope.ERROR
    event_type: None = None
    data: BroadcastErrorData
