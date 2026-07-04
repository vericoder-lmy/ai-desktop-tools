from __future__ import annotations

import json
import sys

from cc_led.codex_installer import _command_prefix, codex_hooks_installed, install_codex_hooks, uninstall_codex_hooks
from cc_led.config import CODEX_HOOK_EVENTS


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_install_codex_hooks_is_append_only_and_idempotent(tmp_path):
    hooks = tmp_path / "hooks.json"
    hooks.write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {
                            "hooks": [{"type": "command", "command": "echo existing", "timeout": 30}],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    first = install_codex_hooks(hooks_path=hooks, exe_path=r"C:\Program Files\CC LED\cc-led.exe")
    second = install_codex_hooks(hooks_path=hooks, exe_path=r"C:\Program Files\CC LED\cc-led.exe")
    data = read_json(hooks)

    assert first.added == len(CODEX_HOOK_EVENTS)
    assert second.added == 0
    assert data["hooks"]["Stop"][0]["hooks"][0]["command"] == "echo existing"
    assert len(data["hooks"]["Stop"]) == 1
    cc_led_stop_hooks = [
        hook
        for entry in data["hooks"]["Stop"]
        for hook in entry.get("hooks", [])
        if "--codex-hook Stop" in hook.get("command", "")
    ]
    assert len(cc_led_stop_hooks) == 1
    assert first.backup_path is not None


def test_uninstall_codex_hooks_removes_only_cc_led_entries(tmp_path):
    hooks = tmp_path / "hooks.json"
    install_codex_hooks(hooks_path=hooks, exe_path=r"C:\Program Files\CC LED\cc-led.exe")
    data = read_json(hooks)
    data["hooks"]["Stop"].append({"hooks": [{"type": "command", "command": "echo existing"}]})
    hooks.write_text(json.dumps(data), encoding="utf-8")

    result = uninstall_codex_hooks(hooks_path=hooks)
    data = read_json(hooks)

    assert result.removed == len(CODEX_HOOK_EVENTS)
    assert data["hooks"]["Stop"][0]["hooks"][0]["command"] == "echo existing"
    assert "SessionStart" not in data["hooks"]
    assert not codex_hooks_installed(hooks_path=hooks)


def test_codex_hooks_installed_requires_complete_cc_led_hooks(tmp_path):
    hooks = tmp_path / "hooks.json"

    assert not codex_hooks_installed(hooks_path=hooks)
    install_codex_hooks(hooks_path=hooks, exe_path=r"C:\Program Files\CC LED\cc-led.exe")
    assert codex_hooks_installed(hooks_path=hooks)

    data = read_json(hooks)
    del data["hooks"]["Stop"]
    hooks.write_text(json.dumps(data), encoding="utf-8")

    assert not codex_hooks_installed(hooks_path=hooks)


def test_codex_permission_hook_uses_long_timeout(tmp_path):
    hooks = tmp_path / "hooks.json"

    install_codex_hooks(hooks_path=hooks, exe_path=r"C:\Program Files\CC LED\cc-led.exe")
    data = read_json(hooks)

    permission_hook = data["hooks"]["PermissionRequest"][0]["hooks"][0]
    assert permission_hook["timeout"] == 600
    assert "--codex-hook PermissionRequest" in permission_hook["command"]


def test_install_codex_hooks_uses_existing_hook_group(tmp_path):
    hooks = tmp_path / "hooks.json"
    hooks.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "hooks": [{"type": "command", "command": "echo existing", "timeout": 30}],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    install_codex_hooks(hooks_path=hooks, exe_path=r"C:\Program Files\CC LED\cc-led.exe")
    data = read_json(hooks)

    assert len(data["hooks"]["PreToolUse"]) == 1
    assert len(data["hooks"]["PreToolUse"][0]["hooks"]) == 2
    assert "--codex-hook PreToolUse" in data["hooks"]["PreToolUse"][0]["hooks"][1]["command"]


def test_frozen_main_exe_prefers_sibling_hook_exe(monkeypatch, tmp_path):
    main_exe = tmp_path / "CC_LED.exe"
    hook_exe = tmp_path / "CC_LED_Hook.exe"
    main_exe.write_text("", encoding="utf-8")
    hook_exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(main_exe))

    assert _command_prefix() == f'"{hook_exe}"'
