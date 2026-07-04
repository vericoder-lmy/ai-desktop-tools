from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Thread
from typing import Callable

from .events import HookEvent, LedState
from .reducer import SessionStore


@dataclass(frozen=True)
class ClaudeProcessSnapshot:
    running: bool
    count: int


class HealthMonitor:
    """Small psutil-based fallback, not the primary state source."""

    def __init__(
        self,
        store: SessionStore,
        interval_seconds: float = 10.0,
        on_state_change: Callable[[], None] | None = None,
    ) -> None:
        self.store = store
        self.interval_seconds = interval_seconds
        self.on_state_change = on_state_change
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        self._thread = Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self.store.aggregate()
            if self.on_state_change:
                self.on_state_change()


def snapshot_claude_processes() -> ClaudeProcessSnapshot:
    try:
        import psutil
    except ImportError:
        return ClaudeProcessSnapshot(running=False, count=0)

    count = 0
    for process in psutil.process_iter(attrs=["name", "cmdline"]):
        try:
            info = process.info
            name = (info.get("name") or "").lower()
            cmdline = " ".join(info.get("cmdline") or []).lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if name == "claude.exe" or name == "claude" or "claude-code" in cmdline or "@anthropic-ai" in cmdline:
            count += 1
    return ClaudeProcessSnapshot(running=count > 0, count=count)


def make_health_event(snapshot: ClaudeProcessSnapshot) -> HookEvent:
    state = LedState.IDLE if not snapshot.running else LedState.IDLE
    return HookEvent(
        source="health",
        event="ProcessSnapshot",
        state=state,
        session_id="health",
        raw={"process_count": snapshot.count},
    )
