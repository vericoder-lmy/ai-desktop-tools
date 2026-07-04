from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "CC LED"
SOURCE_CLAUDE_CODE = "claude-code"
SOURCE_CODEX = "codex"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 32333
STATE_PATH = "/state"
HEALTH_PATH = "/health"
PERMISSION_PATH = "/permission"
HOOK_TIMEOUT_SECONDS = 0.2
OVERLAY_MIN_SCALE = 0.1
OVERLAY_MAX_SCALE = 1.0
OVERLAY_DEFAULT_SCALE = 1.0
OVERLAY_BLINK_INTERVAL_MS = 500
OVERLAY_BACKGROUND_COLOR = "#000000"

CORE_HOOK_EVENTS = (
    "SessionStart",
    "SessionEnd",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "Stop",
    "SubagentStart",
    "SubagentStop",
    "Notification",
    "Elicitation",
)

VERSIONED_HOOK_EVENTS = (
    "PreCompact",
    "PostCompact",
    "StopFailure",
)

SUPPORTED_HOOK_EVENTS = CORE_HOOK_EVENTS + VERSIONED_HOOK_EVENTS
SUPPORTED_HOOK_EVENTS = SUPPORTED_HOOK_EVENTS + ("PermissionRequest",)
CODEX_HOOK_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "Stop",
)

HOOK_MARKER = "cc-led"
BUSY_TTL_SECONDS = 30 * 60
IDLE_TTL_SECONDS = 2 * 60 * 60
PERMISSION_TIMEOUT_SECONDS = 600
ATTENTION_HOLD_SECONDS = 8
APPROVAL_HOLD_SECONDS = 2.5
APPROVAL_LATCH_SECONDS = 30 * 60


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / f".{APP_NAME.lower().replace(' ', '-')}"


def log_path() -> Path:
    return app_data_dir() / "cc-led.log"


def default_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def default_codex_hooks_path() -> Path:
    return Path.home() / ".codex" / "hooks.json"
