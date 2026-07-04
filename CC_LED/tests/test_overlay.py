from __future__ import annotations

from cc_led.events import GlobalState, LedState, utc_now
from cc_led.ui.overlay import OverlayWindow, _alpha_runs


def test_overlay_state_key_ignores_timestamp_only_changes():
    window = OverlayWindow.__new__(OverlayWindow)
    first = GlobalState(LedState.BUSY, "PreToolUse", 1, utc_now())
    second = GlobalState(LedState.BUSY, "PreToolUse", 1, utc_now())
    third = GlobalState(LedState.APPROVAL, "PermissionRequest", 1, utc_now())

    assert window._make_state_key(first) == window._make_state_key(second)
    assert window._make_state_key(first) != window._make_state_key(third)


def test_alpha_runs_extracts_opaque_spans():
    from PIL import Image

    image = Image.new("RGBA", (5, 3), (0, 0, 0, 0))
    pixels = image.load()
    pixels[1, 1] = (255, 255, 255, 255)
    pixels[2, 1] = (255, 255, 255, 255)
    pixels[4, 2] = (255, 255, 255, 64)

    assert _alpha_runs(image) == [(1, 1, 3), (2, 4, 5)]
