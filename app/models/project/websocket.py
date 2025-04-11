from enum import Enum
from typing import Any, Union, Optional
from typing_extensions import Self
from pydantic import BaseModel, model_validator


class EventScope(str, Enum):
    PROJECT = "project"
    MEMBER = "member"
    FILE = "file"
    CHAT = "chat"
    CRDT = "crdt"


class ProjectAction(str, Enum):
    DELETE_PROJECT = "delete_project"
    UPDATE_NAME = "update_name"


class MemberAction(str, Enum):
    JOINED = "joined"
    LEFT = "left"
    ADD_MEMBER = "add_member"
    UPDATE_MEMBER = "update_member"
    REMOVE_MEMBER = "remove_member"
    TRANSFER_OWNERSHIP = "transfer_ownership"


class FileAction(str, Enum):
    ADDED = "added"
    RENAMED = "renamed"
    MOVED = "moved"
    DELETED = "deleted"


class ChatAction(str, Enum):
    SEND_MESSAGE = "send_message"
    # MESSAGE_EDITED = "message_edited"
    # MESSAGE_WITHDRAWN = "message_withdrawn"


class CRDTAction(str, Enum):
    BROADCAST = "broadcast"


EventAction = Union[
    ProjectAction,
    MemberAction,
    FileAction,
    ChatAction,
    CRDTAction,
]


class BaseMessage(BaseModel):
    """Base model containing common fields and validation logic."""

    scope: EventScope
    action: EventAction
    payload: Any = None  # TODO add validation later

    @model_validator(mode="after")
    def action_must_match_scope(self) -> Self:
        """Ensures the action is valid for the given scope."""
        is_valid = False
        scope_action_error = False
        if self.scope == EventScope.PROJECT and isinstance(self.action, ProjectAction):
            is_valid = True
            scope_action_error = True
        elif self.scope == EventScope.MEMBER and isinstance(self.action, MemberAction):
            is_valid = True
            scope_action_error = True
        elif self.scope == EventScope.FILE and isinstance(self.action, FileAction):
            is_valid = True
            scope_action_error = True
        elif self.scope == EventScope.CHAT and isinstance(self.action, ChatAction):
            is_valid = True
            scope_action_error = True
        elif self.scope == EventScope.CRDT and isinstance(self.action, CRDTAction):
            is_valid = True
            scope_action_error = True

        if not is_valid:
            if scope_action_error:
                raise ValueError(
                    f"Action '{self.action}' (type: {type(self.action).__name__}) "
                    f"is invalid for scope '{self.scope}'"
                )
            else:
                raise ValueError("Validation Failed.")
        return self


class Message(BaseMessage):
    """Basic Message. Optionally associated with client_id."""

    client_id: Optional[str] = None


class ClientMessage(BaseMessage):
    """Message with client_id."""

    client_id: str


class ErrorMessage(BaseModel):
    code: int
    message: str


WrongInputMessageFormatErrorStr = ErrorMessage(code=1, message="Wrong input message format.").model_dump_json()

ScopeNotAllowedErrorStr = ErrorMessage(code=2, message="Scope is not allowed.").model_dump_json()

ObjectNotFoundErrorStr = ErrorMessage(code=3, message="Object not found.").model_dump_json()
