from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from datetime import timezone
from pathlib import Path
from typing import Any

from .config import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    HOOK_TIMEOUT_SECONDS,
    SOURCE_CLAUDE_CODE,
    SOURCE_CODEX,
    STATE_PATH,
    SUPPORTED_HOOK_EVENTS,
    log_path,
)
from .events import HookEvent, LedState, parse_timestamp, utc_now

TRANSCRIPT_TAIL_BYTES = 256 * 1024
QUESTION_TEXT_MAX = 1600
API_ERROR_TYPES = {
    "authentication_failed",
    "oauth_org_not_allowed",
    "billing_error",
    "rate_limit",
    "invalid_request",
    "model_not_found",
    "server_error",
    "unknown",
    "max_output_tokens",
}

BUSY_EVENTS = {
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "SubagentStart",
    "SubagentStop",
    "PreCompact",
}

ERROR_EVENTS = {
    "PostToolUseFailure",
    "StopFailure",
}

APPROVAL_EVENTS = {
    "PermissionRequest",
    "Notification",
    "Elicitation",
}


def read_stdin_json(stdin: Any = None) -> dict[str, Any]:
    stdin = stdin or sys.stdin
    try:
        data = stdin.read()
    except Exception:
        return {}
    if not data or not data.strip():
        return {}
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def build_hook_event(
    event_name: str,
    payload: dict[str, Any] | None = None,
    source: str = SOURCE_CLAUDE_CODE,
) -> HookEvent | None:
    if not event_name:
        event_name = str((payload or {}).get("hook_event_name") or "")
    if event_name not in SUPPORTED_HOOK_EVENTS:
        return None

    payload = payload or {}
    session_id = str(payload.get("session_id") or payload.get("sessionId") or "default")
    cwd = _string_or_none(payload.get("cwd"))
    tool_name = _string_or_none(payload.get("tool_name") or payload.get("toolName"))
    timestamp = parse_timestamp(payload.get("timestamp"))

    state = map_event_to_state(event_name, payload)
    raw = {
        "payload": _redacted_payload(payload),
    }

    if event_name == "Stop":
        transcript_entries = read_transcript_tail_entries(payload.get("transcript_path"))
        api_error = extract_api_error_from_entries(transcript_entries, session_id)
        if api_error:
            state = LedState.ERROR
            raw["api_error_type"] = api_error
            event_name = "ApiError"
        else:
            assistant_text = extract_last_assistant_text_from_entries(transcript_entries, session_id)
            if assistant_text and looks_like_user_question(assistant_text):
                state = LedState.APPROVAL
                raw["assistant_question_detected"] = True
                event_name = "UserAttention"

    return HookEvent(
        source=source,
        event=event_name,
        state=state,
        session_id=session_id,
        cwd=cwd,
        tool_name=tool_name,
        timestamp=timestamp,
        raw=raw,
    )


def map_event_to_state(event_name: str, payload: dict[str, Any] | None = None) -> LedState:
    payload = payload or {}
    if event_name in ERROR_EVENTS:
        return LedState.ERROR
    if event_name in APPROVAL_EVENTS:
        return LedState.APPROVAL
    if event_name in BUSY_EVENTS:
        return LedState.BUSY
    if event_name == "PostCompact" and payload.get("trigger") != "manual":
        return LedState.BUSY
    return LedState.IDLE


def post_state(event: HookEvent, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
    body = {
        "source": event.source,
        "event": event.event,
        "state": event.state.value,
        "session_id": event.session_id,
        "cwd": event.cwd,
        "tool_name": event.tool_name,
        "timestamp": event.timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "raw": event.raw,
    }
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"http://{host}:{port}{STATE_PATH}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=HOOK_TIMEOUT_SECONDS) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError):
        return False


def run_hook(event_name: str, port: int | None = None, source: str = SOURCE_CLAUDE_CODE) -> int:
    payload = read_stdin_json()
    event = build_hook_event(event_name, payload, source=source)
    if event is None:
        _append_hook_log(f"source={source} ignored unsupported event={event_name}")
        return 0
    ok = post_state(event, port=port or DEFAULT_PORT)
    _append_hook_log(
        f"source={source} event={event.event} state={event.state.value} session={event.session_id} posted={ok}"
    )
    if source == SOURCE_CODEX and event.event == "PermissionRequest":
        print("{}")
    return 0


def extract_api_error_from_transcript(transcript_path: Any, session_id: str) -> str | None:
    return extract_api_error_from_entries(read_transcript_tail_entries(transcript_path), session_id)


def extract_api_error_from_entries(entries: list[dict[str, Any]], session_id: str) -> str | None:
    if not entries:
        return None

    last_error_index = -1
    for index in range(len(entries) - 1, -1, -1):
        entry = entries[index]
        if not isinstance(entry, dict):
            continue
        if entry.get("isApiErrorMessage") is not True:
            continue
        if entry.get("sessionId") not in (None, session_id) and entry.get("session_id") not in (None, session_id):
            continue
        last_error_index = index
        break

    if last_error_index < 0:
        return None

    for entry in entries[last_error_index + 1 :]:
        entry_type = entry.get("type") if isinstance(entry, dict) else None
        if entry_type == "user":
            return None
        if entry_type == "assistant" and entry.get("isApiErrorMessage") is not True:
            return None

    raw_error = entries[last_error_index].get("error")
    return raw_error if raw_error in API_ERROR_TYPES else "unknown"


def extract_last_assistant_text_from_entries(entries: list[dict[str, Any]], session_id: str) -> str | None:
    if not entries:
        return None
    for entry in reversed(entries):
        if not isinstance(entry, dict):
            continue
        if _is_user_entry(entry):
            break
        if not _is_assistant_entry(entry):
            continue
        if entry.get("isApiErrorMessage") is True:
            continue
        entry_session = entry.get("sessionId") or entry.get("session_id")
        if entry_session and entry_session != session_id:
            continue
        text = _assistant_text(entry)
        if text:
            return text[-QUESTION_TEXT_MAX:]
    return None


def looks_like_user_question(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return False
    tail = normalized[-500:]
    if "?" in tail or "？" in tail:
        return True
    lower_tail = tail.lower()
    question_markers = (
        "需要你",
        "请确认",
        "是否",
        "要我",
        "可以吗",
        "继续吗",
        "你想",
        "请问",
        "请选择",
        "是否要",
        "do you want",
        "would you like",
        "should i",
        "shall i",
        "please confirm",
        "confirm whether",
        "which option",
        "choose one",
    )
    return any(marker in lower_tail for marker in question_markers)


def _assistant_text(entry: dict[str, Any]) -> str:
    payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else None
    if payload and payload.get("type") == "message":
        message = payload
    else:
        message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else entry.get("content")
    parts = _text_parts(content)
    return "\n\n".join(part for part in parts if part).strip()


def _is_user_entry(entry: dict[str, Any]) -> bool:
    if entry.get("type") == "user":
        return True
    payload = entry.get("payload")
    return isinstance(payload, dict) and payload.get("type") == "message" and payload.get("role") == "user"


def _is_assistant_entry(entry: dict[str, Any]) -> bool:
    if entry.get("type") == "assistant":
        return True
    payload = entry.get("payload")
    return isinstance(payload, dict) and payload.get("type") == "message" and payload.get("role") == "assistant"


def _text_parts(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            item_type = item.get("type")
            if item_type in {"tool_use", "server_tool_use"}:
                continue
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
    return parts


def read_transcript_tail_entries(transcript_path: Any) -> list[dict[str, Any]]:
    if not isinstance(transcript_path, str) or not transcript_path:
        return []

    path = Path(transcript_path)
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            read_len = min(size, TRANSCRIPT_TAIL_BYTES)
            handle.seek(max(0, size - read_len))
            data = handle.read(read_len).decode("utf-8", errors="replace")
    except OSError:
        return []

    lines = data.splitlines()
    if size > TRANSCRIPT_TAIL_BYTES and lines:
        lines = lines[1:]

    entries: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            entries.append(parsed)
    return entries


def event_from_state_request(data: dict[str, Any]) -> HookEvent:
    state = _state_from_request(data.get("state", LedState.IDLE.value))
    raw = data.get("raw") if isinstance(data.get("raw"), dict) else {}
    return HookEvent(
        source=str(data.get("source") or SOURCE_CLAUDE_CODE),
        event=str(data.get("event") or "Unknown"),
        state=state,
        session_id=str(data.get("session_id") or "default"),
        cwd=_string_or_none(data.get("cwd")),
        tool_name=_string_or_none(data.get("tool_name")),
        timestamp=parse_timestamp(data.get("timestamp") or utc_now()),
        raw=raw,
    )


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _state_from_request(value: Any) -> LedState:
    if isinstance(value, str):
        if value in {LedState.IDLE.value, LedState.BUSY.value, LedState.ERROR.value, LedState.APPROVAL.value}:
            return LedState(value)
        if value in {"thinking", "working"}:
            return LedState.BUSY
        if value in {"attention", "permission"}:
            return LedState.APPROVAL
    return LedState.IDLE


def _redacted_payload(payload: dict[str, Any]) -> dict[str, Any]:
    safe_keys = (
        "session_id",
        "sessionId",
        "hook_event_name",
        "cwd",
        "tool_name",
        "toolName",
        "tool_use_id",
        "toolUseId",
        "turn_id",
        "permission_mode",
        "model",
        "trigger",
        "source",
        "reason",
        "transcript_path",
    )
    return {key: payload[key] for key in safe_keys if key in payload}


def _append_hook_log(message: str) -> None:
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"hook {utc_now().isoformat()} {message}\n")
    except OSError:
        pass
