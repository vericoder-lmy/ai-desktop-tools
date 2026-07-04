from __future__ import annotations

from datetime import timedelta

from cc_led.config import ATTENTION_HOLD_SECONDS
from cc_led.events import HookEvent, LedState, utc_now
from cc_led.reducer import SessionStore


def test_aggregate_prefers_error_over_busy_and_idle():
    store = SessionStore()

    store.apply(HookEvent("test", "SessionStart", LedState.IDLE, "a"))
    assert store.aggregate().led == LedState.IDLE

    store.apply(HookEvent("test", "PreToolUse", LedState.BUSY, "b"))
    assert store.aggregate().led == LedState.BUSY

    store.apply(HookEvent("test", "StopFailure", LedState.ERROR, "c"))
    assert store.aggregate().led == LedState.ERROR

    store.apply(HookEvent("test", "PermissionRequest", LedState.APPROVAL, "d"))
    assert store.aggregate().led == LedState.APPROVAL


def test_busy_session_expires_to_idle():
    now = utc_now()
    store = SessionStore(busy_ttl_seconds=10)
    store.apply(HookEvent("test", "PreToolUse", LedState.BUSY, "a", timestamp=now - timedelta(seconds=11)))

    assert store.aggregate(now=now).led == LedState.IDLE
    assert store.sessions()[0].last_event == "BusyExpired"


def test_clear_errors_sets_error_sessions_idle():
    store = SessionStore()
    store.apply(HookEvent("test", "StopFailure", LedState.ERROR, "a"))

    state = store.clear_errors()

    assert state.led == LedState.IDLE
    assert store.sessions()[0].last_event == "ClearError"


def test_real_hook_event_clears_manual_test_state():
    store = SessionStore()
    store.apply(HookEvent("manual", "TestBusy", LedState.BUSY, "manual-test"))

    state = store.apply(HookEvent("claude-code", "Stop", LedState.IDLE, "claude-session"))

    assert state.led == LedState.IDLE
    assert {session.session_id for session in store.sessions()} == {"claude-session"}


def test_approval_holds_briefly_over_followup_busy_event():
    now = utc_now()
    store = SessionStore()
    store.apply(HookEvent("claude-code", "PermissionRequest", LedState.APPROVAL, "s1", timestamp=now))
    store.apply(HookEvent("claude-code", "PreToolUse", LedState.BUSY, "s1", timestamp=now + timedelta(seconds=0.4)))

    assert store.aggregate(now=now + timedelta(seconds=0.5)).led == LedState.APPROVAL
    assert store.aggregate(now=now + timedelta(seconds=10)).led == LedState.APPROVAL

    state = store.apply(HookEvent("claude-code", "PostToolUse", LedState.BUSY, "s1", timestamp=now + timedelta(seconds=11)))

    assert state.led == LedState.BUSY


def test_new_codex_prompt_clears_stale_approval_session():
    now = utc_now()
    store = SessionStore()
    store.apply(HookEvent("codex", "UserAttention", LedState.APPROVAL, "old", timestamp=now))

    state = store.apply(HookEvent("codex", "UserPromptSubmit", LedState.BUSY, "new", timestamp=now + timedelta(seconds=1)))

    assert state.led == LedState.BUSY
    assert {session.session_id: session.led for session in store.sessions()} == {
        "old": LedState.IDLE,
        "new": LedState.BUSY,
    }


def test_user_attention_expires_back_to_idle():
    now = utc_now()
    store = SessionStore()
    store.apply(HookEvent("codex", "UserAttention", LedState.APPROVAL, "s1", timestamp=now))

    state = store.aggregate(now=now + timedelta(seconds=ATTENTION_HOLD_SECONDS + 1))

    assert state.led == LedState.IDLE
    assert store.sessions()[0].last_event == "ApprovalExpired"


def test_permission_request_uses_longer_approval_timeout():
    now = utc_now()
    store = SessionStore()
    store.apply(HookEvent("codex", "PermissionRequest", LedState.APPROVAL, "s1", timestamp=now))

    state = store.aggregate(now=now + timedelta(seconds=ATTENTION_HOLD_SECONDS + 1))

    assert state.led == LedState.APPROVAL
