from enum import Enum
from typing import Any, Dict, Optional
from uuid import UUID

from app.models.base import Base


class WSTarget(str, Enum):
    """WebSocket target"""

    PROJECT = "project"
    MEMBER = "member"
    FILE = "file"
    CHAT = "chat"
    ERROR = "error"


class WSAction(str, Enum):
    """WebSocket action"""

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


class WSErrorData(Base):
    """错误数据模型"""

    code: int
    message: str
    original_action: Optional[str] = None  # 原始action


class WSMessage(Base):
    """WebSocket消息基础模型"""

    ws_action: Optional[WSAction]
    ws_target: Optional[WSTarget]
    channel: Optional[str] = None
    data: Dict[str, Any]


class WSErrorMessage(WSMessage):
    """错误消息模型"""

    ws_target: WSTarget = WSTarget.ERROR
    data: WSErrorData
