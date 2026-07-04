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

from .config import CODEX_HOOK_EVENTS, HOOK_MARKER, default_codex_hooks_path


@dataclass(frozen=True)
class CodexInstallResult:
    changed: bool
    added: int
    updated: int
    removed: int
    backup_path: Path | None
    hooks_path: Path

    @property
    def message(self) -> str:
        action = "updated" if self.changed else "already up to date"
        backup = f"\nBackup: {self.backup_path}" if self.backup_path else ""
        return (
            f"Codex hooks {action}: {self.hooks_path}\n"
            f"Added: {self.added}, Updated: {self.updated}, Removed: {self.removed}"
            f"{backup}"
        )


def install_codex_hooks(
    hooks_path: str | os.PathLike[str] | None = None,
    exe_path: str | None = None,
) -> CodexInstallResult:
    path = Path(hooks_path) if hooks_path else default_codex_hooks_path()
    command_prefix = _command_prefix(exe_path)
    settings = _read_json(path)
    if not isinstance(settings.get("hooks"), dict):
        settings["hooks"] = {}

    added = 0
    updated = 0
    changed = False

    for event in CODEX_HOOK_EVENTS:
        entries = settings["hooks"].get(event)
        if not isinstance(entries, list):
            entries = [] if entries is None else [entries]
            settings["hooks"][event] = entries
            changed = True

        desired = _build_codex_hook(command_prefix, event)
        existed, entry_changed = _ensure_single_hook(entries, desired)
        if existed:
            if entry_changed:
                updated += 1
                changed = True
        else:
            added += 1
            changed = True

    backup_path = _write_with_backup(path, settings) if changed else None
    return CodexInstallResult(changed, added, updated, 0, backup_path, path)


def uninstall_codex_hooks(hooks_path: str | os.PathLike[str] | None = None) -> CodexInstallResult:
    path = Path(hooks_path) if hooks_path else default_codex_hooks_path()
    settings = _read_json(path)
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return CodexInstallResult(False, 0, 0, 0, None, path)

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
    return CodexInstallResult(changed, 0, 0, removed, backup_path, path)


def codex_hooks_installed(hooks_path: str | os.PathLike[str] | None = None) -> bool:
    path = Path(hooks_path) if hooks_path else default_codex_hooks_path()
    hooks = _read_json(path).get("hooks")
    if not isinstance(hooks, dict):
        return False

    for event in CODEX_HOOK_EVENTS:
        entries = hooks.get(event)
        if not isinstance(entries, list):
            return False
        if not any(_is_cc_led_codex_command(hook.get("command")) for hook in _iter_command_hooks(entries)):
            return False
    return True


def _build_codex_hook(command_prefix: str, event: str) -> dict[str, Any]:
    return {
        "type": "command",
        "command": f"& {command_prefix} --codex-hook {event} --cc-led-marker",
        "timeout": 600 if event == "PermissionRequest" else 30,
    }


def _ensure_single_hook(entries: list[Any], desired: dict[str, Any]) -> tuple[bool, bool]:
    target_entry = _first_nested_hook_entry(entries)
    target_hooks = target_entry.get("hooks") if target_entry else None
    desired_already_in_target = (
        isinstance(target_hooks, list)
        and sum(1 for hook in target_hooks if isinstance(hook, dict) and _is_cc_led_codex_command(hook.get("command"))) == 1
        and any(_same_hook(hook, desired) for hook in target_hooks if isinstance(hook, dict))
        and sum(1 for hook in _iter_command_hooks(entries) if _is_cc_led_codex_command(hook.get("command"))) == 1
    )
    if desired_already_in_target:
        return True, False

    had_existing = any(_is_cc_led_codex_command(hook.get("command")) for hook in _iter_command_hooks(entries))
    next_entries, _removed = _remove_marker_hooks(entries)
    entries[:] = next_entries
    target_entry = _first_nested_hook_entry(entries)
    if target_entry is None:
        entries.append({"hooks": [desired]})
    else:
        target_entry["hooks"].append(desired)
    return had_existing, True


def _same_hook(hook: dict[str, Any], desired: dict[str, Any]) -> bool:
    return all(hook.get(key) == desired.get(key) for key in ("type", "command", "timeout"))


def _first_nested_hook_entry(entries: list[Any]) -> dict[str, Any] | None:
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("hooks"), list):
            return entry
    return None


def _remove_marker_hooks(entries: list[Any]) -> tuple[list[Any], int]:
    removed = 0
    next_entries: list[Any] = []
    for entry in entries:
        if isinstance(entry, dict) and _is_cc_led_codex_command(entry.get("command")):
            removed += 1
            continue

        if isinstance(entry, dict) and isinstance(entry.get("hooks"), list):
            next_hooks = [
                hook
                for hook in entry["hooks"]
                if not (isinstance(hook, dict) and _is_cc_led_codex_command(hook.get("command")))
            ]
            removed += len(entry["hooks"]) - len(next_hooks)
            if next_hooks:
                next_entry = dict(entry)
                next_entry["hooks"] = next_hooks
                next_entries.append(next_entry)
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


def _is_cc_led_codex_command(command: Any) -> bool:
    if not isinstance(command, str):
        return False
    lowered = command.lower()
    return HOOK_MARKER in lowered and "--codex-hook" in lowered


def _read_json(path: Path) -> dict[str, Any]:
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
