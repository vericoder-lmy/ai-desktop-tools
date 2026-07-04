from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import (
    CORE_HOOK_EVENTS,
    DEFAULT_HOST,
    DEFAULT_PORT,
    HOOK_MARKER,
    PERMISSION_PATH,
    PERMISSION_TIMEOUT_SECONDS,
    VERSIONED_HOOK_EVENTS,
    default_settings_path,
)


@dataclass(frozen=True)
class InstallResult:
    changed: bool
    added: int
    updated: int
    removed: int
    backup_path: Path | None
    settings_path: Path

    @property
    def message(self) -> str:
        action = "updated" if self.changed else "already up to date"
        backup = f"\nBackup: {self.backup_path}" if self.backup_path else ""
        return (
            f"Claude hooks {action}: {self.settings_path}\n"
            f"Added: {self.added}, Updated: {self.updated}, Removed: {self.removed}"
            f"{backup}"
        )


def install_hooks(settings_path: str | os.PathLike[str] | None = None, exe_path: str | None = None) -> InstallResult:
    path = Path(settings_path) if settings_path else default_settings_path()
    command_prefix = _command_prefix(exe_path)
    settings = _read_settings(path)
    if not isinstance(settings.get("hooks"), dict):
        settings["hooks"] = {}

    added = 0
    updated = 0
    changed = False

    for event in CORE_HOOK_EVENTS + VERSIONED_HOOK_EVENTS:
        entries = settings["hooks"].get(event)
        if not isinstance(entries, list):
            entries = [] if entries is None else [entries]
            settings["hooks"][event] = entries
            changed = True

        desired = _build_command_hook(command_prefix, event)
        found, entry_updated = _sync_or_append_hook(entries, desired)
        if found:
            if entry_updated:
                updated += 1
                changed = True
        else:
            entries.append({"matcher": "", "hooks": [desired]})
            added += 1
            changed = True

    permission_result = _sync_permission_hook(settings["hooks"])
    added += permission_result[0]
    updated += permission_result[1]
    changed = changed or permission_result[2]

    backup_path = _write_with_backup(path, settings) if changed else None
    return InstallResult(changed, added, updated, 0, backup_path, path)


def uninstall_hooks(settings_path: str | os.PathLike[str] | None = None) -> InstallResult:
    path = Path(settings_path) if settings_path else default_settings_path()
    settings = _read_settings(path)
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return InstallResult(False, 0, 0, 0, None, path)

    removed = 0
    changed = False
    for event, entries in list(hooks.items()):
        if not isinstance(entries, list):
            continue
        next_entries, count = _remove_marker_hooks(entries)
        if count:
            removed += count
            changed = True
            if next_entries:
                hooks[event] = next_entries
            else:
                del hooks[event]

    backup_path = _write_with_backup(path, settings) if changed else None
    return InstallResult(changed, 0, 0, removed, backup_path, path)


def hooks_installed(settings_path: str | os.PathLike[str] | None = None) -> bool:
    path = Path(settings_path) if settings_path else default_settings_path()
    hooks = _read_settings(path).get("hooks")
    if not isinstance(hooks, dict):
        return False

    for event in CORE_HOOK_EVENTS + VERSIONED_HOOK_EVENTS:
        entries = hooks.get(event)
        if not isinstance(entries, list):
            return False
        if not any(_is_cc_led_command(hook.get("command")) for hook in _iter_command_hooks(entries)):
            return False

    entries = hooks.get("PermissionRequest")
    return isinstance(entries, list) and any(_is_cc_led_permission_hook(hook) for hook in _iter_http_hooks(entries))


def _build_command_hook(command_prefix: str, event: str) -> dict[str, Any]:
    return {
        "type": "command",
        "shell": "powershell",
        "command": f"& {command_prefix} --hook {event} --cc-led-marker",
        "async": True,
        "timeout": 5,
    }


def _build_permission_hook() -> dict[str, Any]:
    return {
        "type": "http",
        "url": f"http://{DEFAULT_HOST}:{DEFAULT_PORT}{PERMISSION_PATH}",
        "timeout": PERMISSION_TIMEOUT_SECONDS,
    }


def _sync_permission_hook(hooks: dict[str, Any]) -> tuple[int, int, bool]:
    event = "PermissionRequest"
    entries = hooks.get(event)
    if not isinstance(entries, list):
        entries = [] if entries is None else [entries]
        hooks[event] = entries
    desired = _build_permission_hook()
    found = False
    updated = 0
    changed = False

    for hook in _iter_http_hooks(entries):
        if not _is_cc_led_permission_hook(hook):
            continue
        found = True
        for key in ("type", "url", "timeout"):
            if hook.get(key) != desired.get(key):
                hook[key] = desired[key]
                changed = True
        if changed:
            updated = 1

    if found:
        return 0, updated, changed

    entries.append({"matcher": "", "hooks": [desired]})
    return 1, 0, True


def _sync_or_append_hook(entries: list[Any], desired: dict[str, Any]) -> tuple[bool, bool]:
    found = False
    changed = False
    for hook in _iter_command_hooks(entries):
        command = hook.get("command")
        if not _is_cc_led_command(command):
            continue
        found = True
        for key in ("type", "shell", "command", "async", "timeout"):
            if hook.get(key) != desired.get(key):
                hook[key] = desired[key]
                changed = True
    return found, changed


def _remove_marker_hooks(entries: list[Any]) -> tuple[list[Any], int]:
    removed = 0
    next_entries: list[Any] = []
    for entry in entries:
        if isinstance(entry, dict) and _is_cc_led_command(entry.get("command")):
            removed += 1
            continue

        if isinstance(entry, dict) and isinstance(entry.get("hooks"), list):
            next_hooks = []
            for hook in entry["hooks"]:
                if isinstance(hook, dict) and (
                    _is_cc_led_command(hook.get("command")) or _is_cc_led_permission_hook(hook)
                ):
                    removed += 1
                else:
                    next_hooks.append(hook)
            if next_hooks:
                next_entry = dict(entry)
                next_entry["hooks"] = next_hooks
                next_entries.append(next_entry)
            elif "command" in entry:
                next_entries.append({key: value for key, value in entry.items() if key != "hooks"})
            continue

        next_entries.append(entry)
    return next_entries, removed


def _iter_command_hooks(entries: list[Any]) -> list[dict[str, Any]]:
    hooks: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if isinstance(entry.get("command"), str):
            hooks.append(entry)
        nested = entry.get("hooks")
        if isinstance(nested, list):
            hooks.extend(hook for hook in nested if isinstance(hook, dict) and isinstance(hook.get("command"), str))
    return hooks


def _iter_http_hooks(entries: list[Any]) -> list[dict[str, Any]]:
    hooks: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") == "http":
            hooks.append(entry)
        nested = entry.get("hooks")
        if isinstance(nested, list):
            hooks.extend(hook for hook in nested if isinstance(hook, dict) and hook.get("type") == "http")
    return hooks


def _is_cc_led_command(command: Any) -> bool:
    if not isinstance(command, str):
        return False
    lowered = command.lower()
    if "--hook" not in lowered:
        return False
    return (
        HOOK_MARKER in lowered
        or "cc_led" in lowered
        or "cc led" in lowered
    )


def _is_cc_led_permission_hook(hook: Any) -> bool:
    if not isinstance(hook, dict) or hook.get("type") != "http":
        return False
    url = hook.get("url")
    return isinstance(url, str) and url == f"http://{DEFAULT_HOST}:{DEFAULT_PORT}{PERMISSION_PATH}"


def _read_settings(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            parsed = json.load(handle)
        return parsed if isinstance(parsed, dict) else {}
    except FileNotFoundError:
        return {}


def _write_with_backup(path: Path, data: dict[str, Any]) -> Path | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = None
    if path.exists():
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup_path = path.with_name(f"{path.name}.cc-led.bak.{stamp}")
        shutil.copy2(path, backup_path)

    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return backup_path


def _command_prefix(exe_path: str | None = None) -> str:
    if exe_path:
        return _quote(exe_path)
    if getattr(sys, "frozen", False):
        return _quote(sys.executable)
    return f"{_quote(sys.executable)} -B {_quote(str(Path(__file__).resolve().parents[1] / 'main.py'))}"


def _quote(value: str) -> str:
    return f'"{value.replace(chr(34), chr(92) + chr(34))}"'
