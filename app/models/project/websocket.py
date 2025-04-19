import logging
from enum import Enum
from typing import Any, Union, Optional, Literal, Dict, Type
from typing_extensions import Self
from pydantic import BaseModel, model_validator, ValidationError

# Configure logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


class EventScope(str, Enum):
    PROJECT = "project"
    MEMBER = "member"
    FILE = "file"
    CHAT = "chat"
    CRDT = "crdt"
    Error = "error"

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


class CRDTAction(str, Enum):
    BROADCAST = "broadcast"


# Union of all possible action types
EventAction = Union[
    ProjectAction,
    MemberAction,
    FileAction,
    ChatAction,
    CRDTAction,
]

# Mapping scopes to their valid action types
SCOPE_ACTION_MAP: Dict[EventScope, Type[Enum]] = {
    EventScope.PROJECT: ProjectAction,
    EventScope.MEMBER: MemberAction,
    EventScope.FILE: FileAction,
    EventScope.CHAT: ChatAction,
    EventScope.CRDT: CRDTAction,
}


class CrdtPayload(BaseModel):
    type: Union[Literal["update"], Literal["awareness"]]
    data: str  # base64
    client_id: str


class ErrorPayload(BaseModel):
    code: int
    message: str


class BaseMessage(BaseModel):
    scope: EventScope
    action: Optional[EventAction] = None
    payload: Any = None

    @model_validator(mode="after")
    def validate_scope_action_and_payload(self) -> Self:
        """
        NOTE in this method, it also trys to parse payload for specific event type/scope
        """
        if self.action is None:
            raise ValueError(f"Action is required for scope '{self.scope}'")

        expected_action_type = SCOPE_ACTION_MAP.get(self.scope)
        if not expected_action_type or not isinstance(self.action, expected_action_type):
            action_type_name = type(self.action).__name__
            expected_name = expected_action_type.__name__ if expected_action_type else "None"
            raise ValueError(
                f"Action '{self.action}' (type: {action_type_name}) "
                f"is invalid for scope '{self.scope}'. Expected type: {expected_name}."
            )

        if self.scope == EventScope.CRDT:
             if not isinstance(self.payload, CrdtPayload):
                try:
                    self.payload = CrdtPayload.model_validate(self.payload)
                except (ValidationError, TypeError) as e:
                    raise ValueError(f"Invalid payload for scope '{self.scope}': {e}") from e

        return self


class Message(BaseMessage):
    client_id: Optional[str] = None


class ClientMessage(BaseMessage):
    client_id: str


class ErrorMessage(BaseModel):
    scope: Literal[EventScope.Error] = EventScope.Error
    action: None = None
    payload: ErrorPayload


# Pre-defined error messages
WrongInputMessageFormatErrorStr = ErrorMessage(
    payload=ErrorPayload(code=1, message="Wrong input message format.")
).model_dump_json()

ScopeNotAllowedErrorStr = ErrorMessage(
    payload=ErrorPayload(code=2, message="Scope is not allowed.")
).model_dump_json()

ObjectNotFoundErrorStr = ErrorMessage(
    payload=ErrorPayload(code=3, message="Object not found.")
).model_dump_json()

CrdtApplyUpdateErrorStr = ErrorMessage(
    payload=ErrorPayload(code=4, message="Crdt apply update error.")
).model_dump_json()
