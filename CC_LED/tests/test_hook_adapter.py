from __future__ import annotations

import json

from cc_led.events import LedState
from cc_led.hook_adapter import (
    build_hook_event,
    extract_api_error_from_transcript,
    looks_like_user_question,
    map_event_to_state,
)
from cc_led.config import SOURCE_CODEX


def test_maps_core_events_to_led_states():
    assert map_event_to_state("UserPromptSubmit") == LedState.BUSY
    assert map_event_to_state("PreToolUse") == LedState.BUSY
    assert map_event_to_state("Stop") == LedState.IDLE
    assert map_event_to_state("StopFailure") == LedState.ERROR
    assert map_event_to_state("PermissionRequest") == LedState.APPROVAL
    assert map_event_to_state("Elicitation") == LedState.APPROVAL


def test_postcompact_manual_is_idle_auto_is_busy():
    assert map_event_to_state("PostCompact", {"trigger": "manual"}) == LedState.IDLE
    assert map_event_to_state("PostCompact", {"trigger": "auto"}) == LedState.BUSY
    assert map_event_to_state("PostCompact", {}) == LedState.BUSY


def test_unknown_hook_event_is_ignored():
    assert build_hook_event("MadeUpEvent", {}) is None


def test_permission_request_builds_approval_event():
    event = build_hook_event("PermissionRequest", {"session_id": "s1", "tool_name": "Bash"})

    assert event is not None
    assert event.state == LedState.APPROVAL
    assert event.tool_name == "Bash"


def test_codex_payload_builds_codex_event():
    event = build_hook_event(
        "PreToolUse",
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "turn_id": "turn-1",
            "tool_name": "shell_command",
            "model": "gpt-5.5",
        },
        source=SOURCE_CODEX,
    )

    assert event is not None
    assert event.source == SOURCE_CODEX
    assert event.state == LedState.BUSY
    assert event.raw["payload"]["turn_id"] == "turn-1"


def test_stop_transcript_api_error_becomes_error(tmp_path):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps({"type": "user", "sessionId": "s1"}),
                json.dumps({"type": "assistant", "sessionId": "s1", "isApiErrorMessage": True, "error": "rate_limit"}),
            ]
        ),
        encoding="utf-8",
    )

    event = build_hook_event("Stop", {"session_id": "s1", "transcript_path": str(transcript)})

    assert event is not None
    assert event.event == "ApiError"
    assert event.state == LedState.ERROR
    assert event.raw["api_error_type"] == "rate_limit"
    assert extract_api_error_from_transcript(str(transcript), "s1") == "rate_limit"


def test_stale_api_error_is_ignored_when_later_assistant_recovers(tmp_path):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps({"type": "assistant", "sessionId": "s1", "isApiErrorMessage": True, "error": "server_error"}),
                json.dumps({"type": "assistant", "sessionId": "s1", "message": {"content": "ok"}}),
            ]
        ),
        encoding="utf-8",
    )

    assert extract_api_error_from_transcript(str(transcript), "s1") is None


def test_stop_with_assistant_question_becomes_approval(tmp_path):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps({"type": "user", "sessionId": "s1"}),
                json.dumps(
                    {
                        "type": "assistant",
                        "sessionId": "s1",
                        "message": {"content": [{"type": "text", "text": "我可以继续修改这个文件吗？"}]},
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    event = build_hook_event("Stop", {"session_id": "s1", "transcript_path": str(transcript)})

    assert event is not None
    assert event.event == "UserAttention"
    assert event.state == LedState.APPROVAL
    assert event.raw["assistant_question_detected"] is True


def test_codex_stop_with_assistant_question_becomes_approval(tmp_path):
    transcript = tmp_path / "rollout.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user", "content": []}}),
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "Should I continue with the install?"}],
                        },
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    event = build_hook_event("Stop", {"session_id": "s1", "transcript_path": str(transcript)}, source=SOURCE_CODEX)

    assert event is not None
    assert event.source == SOURCE_CODEX
    assert event.event == "UserAttention"
    assert event.state == LedState.APPROVAL


def test_question_heuristic_accepts_question_like_text():
    assert looks_like_user_question("Should I continue with the install?")
    assert looks_like_user_question("请选择一个方案。")
