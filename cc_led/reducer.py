from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import RLock

from .config import ATTENTION_HOLD_SECONDS, BUSY_TTL_SECONDS, IDLE_TTL_SECONDS, PERMISSION_TIMEOUT_SECONDS
from .events import GlobalState, HookEvent, LedState, SessionState, utc_now


class SessionStore:
    def __init__(
        self,
        busy_ttl_seconds: int = BUSY_TTL_SECONDS,
        idle_ttl_seconds: int = IDLE_TTL_SECONDS,
    ) -> None:
        self.busy_ttl_seconds = busy_ttl_seconds
        self.idle_ttl_seconds = idle_ttl_seconds
        self._sessions: dict[str, SessionState] = {}
        self._approval_until: dict[str, datetime] = {}
        self._approval_latch_until: datetime | None = None
        self._approval_latch_event: str | None = None
        self._lock = RLock()

    def apply(self, event: HookEvent) -> GlobalState:
        details = {
            "source": event.source,
            "tool_name": event.tool_name,
        }
        if event.raw.get("api_error_type"):
            details["api_error_type"] = event.raw.get("api_error_type")
        with self._lock:
            if event.source not in {"manual", "health"}:
                self._sessions.pop("manual", None)
                self._sessions.pop("manual-test", None)
            if event.state == LedState.APPROVAL:
                approval_until = event.timestamp + timedelta(seconds=self._approval_timeout_seconds(event))
                self._approval_until[event.session_id] = approval_until
                self._approval_latch_until = approval_until
                self._approval_latch_event = event.event
            elif self._event_resolves_approval(event):
                self._approval_latch_until = None
                self._approval_latch_event = None
                self._clear_approval_sessions_locked()
            self._sessions[event.session_id] = SessionState(
                session_id=event.session_id,
                led=event.state,
                last_event=event.event,
                cwd=event.cwd,
                updated_at=event.timestamp,
                details={key: value for key, value in details.items() if value},
            )
            return self.aggregate(now=event.timestamp)

    def aggregate(self, now: datetime | None = None) -> GlobalState:
        now = now or utc_now()
        with self._lock:
            self._expire_locked(now)
            sessions = list(self._sessions.values())
            approval_latched = self._approval_latch_until is not None and self._approval_latch_until > now
            approval_hold_sessions = [
                session
                for session in sessions
                if self._approval_until.get(session.session_id) and self._approval_until[session.session_id] > now
            ]

        if not sessions:
            return GlobalState(LedState.IDLE, None, 0, now)

        latest = max(sessions, key=lambda session: session.updated_at)
        if approval_latched:
            return GlobalState(
                LedState.APPROVAL,
                self._approval_latch_event or latest.last_event,
                len(sessions),
                latest.updated_at,
            )
        if approval_hold_sessions:
            held_latest = max(approval_hold_sessions, key=lambda session: self._approval_until[session.session_id])
            return GlobalState(LedState.APPROVAL, held_latest.last_event, len(sessions), latest.updated_at)
        if any(session.led == LedState.APPROVAL for session in sessions):
            return GlobalState(LedState.APPROVAL, latest.last_event, len(sessions), latest.updated_at)
        if any(session.led == LedState.ERROR for session in sessions):
            return GlobalState(LedState.ERROR, latest.last_event, len(sessions), latest.updated_at)
        if any(session.led == LedState.BUSY for session in sessions):
            return GlobalState(LedState.BUSY, latest.last_event, len(sessions), latest.updated_at)
        return GlobalState(LedState.IDLE, latest.last_event, len(sessions), latest.updated_at)

    def clear_errors(self) -> GlobalState:
        now = utc_now()
        with self._lock:
            for session in self._sessions.values():
                if session.led in {LedState.ERROR, LedState.APPROVAL}:
                    session.led = LedState.IDLE
                    session.last_event = "ClearError"
                    session.updated_at = now
            self._approval_latch_until = None
            self._approval_latch_event = None
            return self.aggregate(now=now)

    def sessions(self) -> list[SessionState]:
        with self._lock:
            return list(self._sessions.values())

    def _expire_locked(self, now: datetime) -> None:
        remove_ids: list[str] = []
        for session_id, session in self._sessions.items():
            elapsed = (now - session.updated_at).total_seconds()
            if session.led == LedState.BUSY and elapsed > self.busy_ttl_seconds:
                session.led = LedState.IDLE
                session.last_event = "BusyExpired"
                session.updated_at = now
            elif session.led == LedState.IDLE and elapsed > self.idle_ttl_seconds:
                remove_ids.append(session_id)

        for session_id in remove_ids:
            self._sessions.pop(session_id, None)
            self._approval_until.pop(session_id, None)

        expired_approval_ids = [session_id for session_id, until in self._approval_until.items() if until <= now]
        for session_id in expired_approval_ids:
            self._approval_until.pop(session_id, None)
            session = self._sessions.get(session_id)
            if session and session.led == LedState.APPROVAL:
                session.led = LedState.IDLE
                session.last_event = "ApprovalExpired"
                session.updated_at = now

        if self._approval_latch_until is not None and self._approval_latch_until <= now:
            self._approval_latch_until = None
            self._approval_latch_event = None

    def _approval_timeout_seconds(self, event: HookEvent) -> int:
        if event.event in {"Notification", "UserAttention"}:
            return ATTENTION_HOLD_SECONDS
        return PERMISSION_TIMEOUT_SECONDS

    def _event_resolves_approval(self, event: HookEvent) -> bool:
        if event.source in {"manual", "health"}:
            return False
        return event.event in {
            "UserPromptSubmit",
            "PostToolUse",
            "PostToolUseFailure",
            "Stop",
            "StopFailure",
            "ApiError",
        }

    def _clear_approval_sessions_locked(self) -> None:
        self._approval_until.clear()
        for session in self._sessions.values():
            if session.led == LedState.APPROVAL:
                session.led = LedState.IDLE
                session.last_event = "ApprovalResolved"


def ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
