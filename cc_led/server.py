from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Callable

from .config import DEFAULT_HOST, DEFAULT_PORT, HEALTH_PATH, PERMISSION_PATH, SOURCE_CLAUDE_CODE, SOURCE_CODEX, STATE_PATH
from .events import GlobalState, HookEvent, LedState, utc_now
from .hook_adapter import event_from_state_request
from .reducer import SessionStore


class StateServer:
    def __init__(
        self,
        store: SessionStore,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        on_state_change: Callable[[GlobalState], None] | None = None,
    ) -> None:
        self.store = store
        self.host = host
        self.port = port
        self.on_state_change = on_state_change
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None

    def start(self) -> None:
        handler = self._make_handler()
        self._httpd = ThreadingHTTPServer((self.host, self.port), handler)
        self._thread = Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path != HEALTH_PATH:
                    self._send_json(404, {"ok": False, "error": "not_found"})
                    return
                global_state = parent.store.aggregate()
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "state": global_state.led.value,
                        "session_count": global_state.session_count,
                    },
                )

            def do_POST(self) -> None:
                if self.path == PERMISSION_PATH:
                    self._handle_permission()
                    return
                if self.path != STATE_PATH:
                    self._send_json(404, {"ok": False, "error": "not_found"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    raw_body = self.rfile.read(min(length, 1024 * 1024))
                    data = json.loads(raw_body.decode("utf-8")) if raw_body else {}
                    if not isinstance(data, dict):
                        raise ValueError("JSON body must be an object")
                    event = event_from_state_request(data)
                    global_state = parent.store.apply(event)
                    if parent.on_state_change:
                        parent.on_state_change(global_state)
                    self._send_json(200, {"ok": True, "state": global_state.led.value})
                except Exception as exc:
                    self._send_json(400, {"ok": False, "error": str(exc)})

            def _handle_permission(self) -> None:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    raw_body = self.rfile.read(min(length, 1024 * 1024))
                    data = json.loads(raw_body.decode("utf-8")) if raw_body else {}
                    if not isinstance(data, dict):
                        data = {}
                    session_id = str(data.get("session_id") or data.get("sessionId") or "permission")
                    event = HookEvent(
                        source=_permission_source(data),
                        event="PermissionRequest",
                        state=LedState.APPROVAL,
                        session_id=session_id,
                        cwd=data.get("cwd") if isinstance(data.get("cwd"), str) else None,
                        tool_name=data.get("tool_name") if isinstance(data.get("tool_name"), str) else None,
                        raw={"payload": _redact_permission_payload(data)},
                    )
                    global_state = parent.store.apply(event)
                    if parent.on_state_change:
                        parent.on_state_change(global_state)
                    self.send_response(204)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                except Exception as exc:
                    self._send_json(400, {"ok": False, "error": str(exc)})

            def log_message(self, format: str, *args: object) -> None:
                return

            def _send_json(self, status: int, body: dict[str, object]) -> None:
                payload = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        return Handler


def default_global_state() -> GlobalState:
    return GlobalState(LedState.IDLE, None, 0, utc_now())


def _redact_permission_payload(data: dict[str, object]) -> dict[str, object]:
    safe_keys = (
        "session_id",
        "sessionId",
        "cwd",
        "tool_name",
        "toolName",
        "tool_use_id",
        "toolUseId",
        "hook_source",
        "agent_id",
    )
    return {key: data[key] for key in safe_keys if key in data}


def _permission_source(data: dict[str, object]) -> str:
    source = data.get("source")
    hook_source = data.get("hook_source")
    agent_id = data.get("agent_id")
    values = [source, hook_source, agent_id]
    if any(isinstance(value, str) and "codex" in value.lower() for value in values):
        return SOURCE_CODEX
    return SOURCE_CLAUDE_CODE
