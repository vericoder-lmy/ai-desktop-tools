from __future__ import annotations

from cc_led.sound import (
    DEFAULT_SOUND,
    available_sound_options,
    bundled_sound_path,
    load_sound_path,
    reset_sound,
    selected_sound_id,
    selected_sound_label,
    set_sound_file,
)


def test_sound_selection_can_be_configured_per_kind(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    approval = tmp_path / "approval.m4a"
    complete = tmp_path / "complete.mp3"
    approval.write_bytes(b"approval")
    complete.write_bytes(b"complete")

    assert selected_sound_id("approval") == DEFAULT_SOUND
    assert selected_sound_id("complete") == DEFAULT_SOUND

    set_sound_file("approval", approval)
    set_sound_file("complete", complete)

    assert load_sound_path("approval") == approval
    assert load_sound_path("complete") == complete
    assert selected_sound_label("approval") == "approval.m4a"
    assert selected_sound_label("complete") == "complete.mp3"

    reset_sound("approval")

    assert selected_sound_id("approval") == DEFAULT_SOUND
    assert selected_sound_id("complete") == str(complete)


def test_bundled_sound_uses_stable_id_and_deduplicates_saved_path(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    bundled = bundled_sound_path("F1TR.wav")

    set_sound_file("approval", bundled)

    assert selected_sound_id("approval") == "bundled:F1TR.wav"
    assert [option.label for option in available_sound_options("approval")].count("F1TR.wav") == 1
