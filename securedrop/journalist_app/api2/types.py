from dataclasses import dataclass, field
from enum import IntEnum, StrEnum, auto
from typing import (
    Any,
    List,
    NewType,
    Optional,
    Set,
    Tuple,
    Union,
)

Record = NewType("Record", dict[str, Any])
Version = NewType("Version", str)


# TODO: generic UUID[T] in Python 3.12
SourceUUID = NewType("SourceUUID", str)
ItemUUID = NewType("ItemUUID", str)
JournalistUUID = NewType("JournalistUUID", str)


EventID = NewType("EventID", str)  # int, but opaque on the wire


class EventType(StrEnum):
    REPLY_SENT = auto()
    ITEM_DELETED = auto()
    SOURCE_DELETED = auto()
    SOURCE_CONVERSATION_DELETED = auto()
    STARRED = auto()
    UNSTARRED = auto()
    SEEN = auto()


class EventStatusCode(IntEnum):
    Processing = 102
    OK = 200
    AlreadyReported = 208
    BadRequest = 400
    NotFound = 404
    NotImplemented = 501


EventStatus = Tuple[EventStatusCode, Optional[str]]


@dataclass
class Index:
    # Source metadata, optionally filtered by `source_prefix`:
    sources: dict[SourceUUID, Version] = field(default_factory=dict)
    items: dict[ItemUUID, Version] = field(default_factory=dict)

    # Non-source metadata (always returned):
    journalists: dict[JournalistUUID, Version] = field(default_factory=dict)


@dataclass
class SourceTarget:
    source_uuid: SourceUUID
    version: Version


@dataclass
class ItemTarget:
    item_uuid: ItemUUID
    version: Version


@dataclass
class Event:
    id: EventID
    target: Union[SourceTarget, ItemTarget]
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.type, EventType):
            self.type = EventType(self.type)  # strict enum

        if isinstance(self.target, dict):
            if "source_uuid" in self.target:
                self.target = SourceTarget(**self.target)
            elif "item_uuid" in self.target:
                self.target = ItemTarget(**self.target)
            else:
                raise TypeError(f"invalid event target: {self.target}")


@dataclass
class EventResult:
    event_id: EventID
    status: EventStatus

    # Changed sources/items, return {<uuid>: None} to indicate deletion:
    sources: dict[SourceUUID, Optional[Record]] = field(default_factory=dict)
    items: dict[ItemUUID, Optional[Record]] = field(default_factory=dict)


@dataclass
class BatchRequest:
    # Source metadata:
    sources: Set[SourceUUID] = field(default_factory=set)
    items: Set[ItemUUID] = field(default_factory=set)

    # Non-source metadata:
    journalists: Set[JournalistUUID] = field(default_factory=set)

    # Events submitted by the client:
    events: List[Event] = field(default_factory=list)


@dataclass
class BatchResponse:
    """
    In dictionaries keyed by UUID, an entry {<uuid>: None} indicates deletion.
    """

    # Source metadata:
    sources: dict[SourceUUID, Optional[Record]] = field(default_factory=dict)
    items: dict[ItemUUID, Optional[Record]] = field(default_factory=dict)

    # Non-source metadata:
    journalists: dict[JournalistUUID, Optional[Record]] = field(default_factory=dict)

    # Events processed by the server:
    events: dict[EventID, EventStatus] = field(default_factory=dict)
