from __future__ import annotations

from cc_led.events import GlobalState, LedState, utc_now
from cc_led.ui.effects import (
    OverlayOrientation,
    OverlayEffect,
    load_overlay_effect,
    load_overlay_opacity,
    load_overlay_orientation,
    load_overlay_scale,
    overlay_size,
    render_overlay_image,
    save_overlay_effect,
    save_overlay_opacity,
    save_overlay_orientation,
    save_overlay_scale,
)


def test_all_overlay_effects_render_rgba_images():
    state = GlobalState(LedState.BUSY, "PreToolUse", 1, utc_now())

    for effect in OverlayEffect:
        image = render_overlay_image(effect, state, blink_on=True, scale=1.0)

        assert image.mode == "RGBA"
        assert image.size == (108, 246)
        assert image.getbbox() is not None
        assert image.getpixel((0, 0))[3] == 0
        assert image.getpixel((107, 0))[3] == 0
        assert image.getpixel((0, 245))[3] == 0
        assert image.getpixel((107, 245))[3] == 0


def test_classic_effect_is_available():
    assert OverlayEffect.CLASSIC.value == "classic"


def test_overlay_effects_render_every_menu_scale():
    state = GlobalState(LedState.IDLE, "Stop", 1, utc_now())

    for percent in range(10, 101, 10):
        for effect in OverlayEffect:
            image = render_overlay_image(effect, state, blink_on=True, scale=percent / 100)

            assert image.getbbox() is not None


def test_overlay_effects_render_horizontal_layout():
    state = GlobalState(LedState.BUSY, "PreToolUse", 1, utc_now())

    assert overlay_size(1.0, OverlayOrientation.HORIZONTAL) == (246, 108)

    for effect in OverlayEffect:
        image = render_overlay_image(
            effect,
            state,
            blink_on=True,
            scale=1.0,
            orientation=OverlayOrientation.HORIZONTAL,
        )

        assert image.mode == "RGBA"
        assert image.size == (246, 108)
        assert image.getbbox() is not None


def test_overlay_ui_settings_preserve_effect_scale_opacity_and_orientation(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))

    save_overlay_effect(OverlayEffect.REAL_LED)
    save_overlay_orientation(OverlayOrientation.HORIZONTAL)
    save_overlay_scale(0.3)
    save_overlay_opacity(0.7)

    assert load_overlay_effect() == OverlayEffect.REAL_LED
    assert load_overlay_orientation() == OverlayOrientation.HORIZONTAL
    assert load_overlay_scale() == 0.3
    assert load_overlay_opacity() == 0.7
