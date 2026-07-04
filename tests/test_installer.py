from __future__ import annotations

import json
import sys

from cc_led.config import CORE_HOOK_EVENTS, VERSIONED_HOOK_EVENTS
from cc_led.installer import _command_prefix, hooks_installed, install_hooks, uninstall_hooks


EXPECTED_INSTALL_COUNT = len(CORE_HOOK_EVENTS + VERSIONED_HOOK_EVENTS) + 1


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_install_hooks_is_append_only_and_idempotent(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {
                            "matcher": "",
                            "hooks": [{"type": "command", "command": "echo existing"}],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    first = install_hooks(settings_path=settings, exe_path=r"C:\Program Files\CC LED\cc-led.exe")
    second = install_hooks(settings_path=settings, exe_path=r"C:\Program Files\CC LED\cc-led.exe")
    data = read_json(settings)

    assert first.added == EXPECTED_INSTALL_COUNT
    assert second.added == 0
    assert data["hooks"]["Stop"][0]["hooks"][0]["command"] == "echo existing"
    cc_led_stop_hooks = [
        hook
        for entry in data["hooks"]["Stop"]
        for hook in entry.get("hooks", [])
        if "--hook Stop" in hook.get("command", "")
    ]
    assert len(cc_led_stop_hooks) == 1
    assert first.backup_path is not None


def test_uninstall_hooks_removes_only_cc_led_entries(tmp_path):
    settings = tmp_path / "settings.json"
    install_hooks(settings_path=settings, exe_path=r"C:\Program Files\CC LED\cc-led.exe")
    data = read_json(settings)
    data["hooks"]["Stop"].append({"matcher": "", "hooks": [{"type": "command", "command": "echo existing"}]})
    settings.write_text(json.dumps(data), encoding="utf-8")

    result = uninstall_hooks(settings_path=settings)
    data = read_json(settings)

    assert result.removed == EXPECTED_INSTALL_COUNT
    assert data["hooks"]["Stop"][0]["hooks"][0]["command"] == "echo existing"
    assert "SessionStart" not in data["hooks"]
    assert not hooks_installed(settings_path=settings)


def test_hooks_installed_requires_complete_cc_led_hooks(tmp_path):
    settings = tmp_path / "settings.json"

    assert not hooks_installed(settings_path=settings)
    install_hooks(settings_path=settings, exe_path=r"C:\Program Files\CC LED\cc-led.exe")
    assert hooks_installed(settings_path=settings)

    data = read_json(settings)
    del data["hooks"]["Stop"]
    settings.write_text(json.dumps(data), encoding="utf-8")

    assert not hooks_installed(settings_path=settings)


def test_install_hooks_updates_legacy_main_py_hook(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "matcher": "",
                            "hooks": [
                                {
                                    "type": "command",
                                    "shell": "powershell",
                                    "command": '& "D:\\Workspace\\CC LED\\CC_LED\\main.py" --hook UserPromptSubmit',
                                    "async": True,
                                    "timeout": 5,
                                }
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    install_hooks(settings_path=settings, exe_path=r"C:\Program Files\CC LED\cc-led.exe")
    data = read_json(settings)

    hooks = data["hooks"]["UserPromptSubmit"]
    commands = [hook["command"] for entry in hooks for hook in entry.get("hooks", [])]
    assert len([command for command in commands if "--hook UserPromptSubmit" in command]) == 1
    assert commands[0] == '& "C:\\Program Files\\CC LED\\cc-led.exe" --hook UserPromptSubmit --cc-led-marker'


def test_install_hooks_reads_utf8_bom_settings(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text('{"hooks":{}}', encoding="utf-8-sig")

    result = install_hooks(settings_path=settings, exe_path=r"C:\Program Files\CC LED\cc-led.exe")

    assert result.added == EXPECTED_INSTALL_COUNT


def test_frozen_main_exe_prefers_sibling_hook_exe(monkeypatch, tmp_path):
    main_exe = tmp_path / "CC_LED.exe"
    hook_exe = tmp_path / "CC_LED_Hook.exe"
    main_exe.write_text("", encoding="utf-8")
    hook_exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(main_exe))

    assert _command_prefix() == f'"{hook_exe}"'
