from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from pathlib import Path

from cc_led.reducer import SessionStore
from cc_led.server import StateServer


def test_state_server_accepts_state_event():
    store = SessionStore()
    server = StateServer(store, port=32335)
    server.start()
    try:
        body = json.dumps(
            {
                "source": "test",
                "event": "UserPromptSubmit",
                "state": "busy",
                "session_id": "s1",
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            "http://127.0.0.1:32335/state",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=1) as response:
            assert response.status == 200
        assert store.aggregate().led.value == "busy"
    finally:
        server.stop()


def test_permission_endpoint_sets_approval_and_returns_no_decision():
    store = SessionStore()
    server = StateServer(store, port=32337)
    server.start()
    try:
        body = json.dumps(
            {
                "session_id": "s1",
                "tool_name": "Bash",
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            "http://127.0.0.1:32337/permission",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=1) as response:
            assert response.status == 204
        assert store.aggregate().led.value == "approval"
    finally:
        server.stop()


def test_codex_hook_cli_clears_stale_approval_through_server():
    store = SessionStore()
    server = StateServer(store, port=32339)
    main_py = Path(__file__).resolve().parents[1] / "main.py"
    server.start()
    try:
        subprocess.run(
            [sys.executable, str(main_py), "--codex-hook", "PermissionRequest", "--port", "32339"],
            input=json.dumps({"session_id": "old", "tool_name": "shell_command"}),
            text=True,
            check=True,
            cwd=main_py.parent,
        )
        assert store.aggregate().led.value == "approval"

        subprocess.run(
            [sys.executable, str(main_py), "--codex-hook", "UserPromptSubmit", "--port", "32339"],
            input=json.dumps({"session_id": "new"}),
            text=True,
            check=True,
            cwd=main_py.parent,
        )

        assert store.aggregate().led.value == "busy"
    finally:
        server.stop()
