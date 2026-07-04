from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class LedState(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    ERROR = "error"
    APPROVAL = "approval"


@dataclass(frozen=True)
class HookEvent:
    source: str
    event: str
    state: LedState
    session_id: str
    cwd: str | None = None
    tool_name: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionState:
    session_id: str
    led: LedState
    last_event: str
    cwd: str | None
    updated_at: datetime
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GlobalState:
    led: LedState
    last_event: str | None
    session_count: int
    updated_at: datetime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def display_led(state: LedState) -> LedState:
    return LedState.ERROR if state == LedState.APPROVAL else state


def should_blink(state: LedState) -> bool:
    return state in {LedState.BUSY, LedState.APPROVAL}


def parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            normalized = value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return utc_now()
