from __future__ import annotations

import json
import math
import struct
import wave
import logging
import threading
import time
import uuid
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import app_data_dir
from .events import GlobalState, LedState

SAMPLE_RATE = 44100
SOUND_KINDS = ("approval", "complete")
DEFAULT_SOUND = "default"
BUNDLED_SOUND_PREFIX = "bundled:"
BUNDLED_SOUNDS = ("F1TR.wav",)
SUPPORTED_AUDIO_PATTERNS = (
    ("Audio files", "*.wav *.mp3 *.m4a *.aac *.wma"),
    ("All files", "*.*"),
)


@dataclass(frozen=True)
class SoundOption:
    id: str
    label: str
    path: Path | None = None


class SoundPlayer:
    def __init__(self) -> None:
        self._last_state: LedState | None = None

    def handle_transition(self, state: GlobalState) -> None:
        previous = self._last_state
        current = state.led
        self._last_state = current

        if previous is None or previous == current:
            return
        if current == LedState.APPROVAL:
            play_approval_sound()
        elif current == LedState.IDLE and previous in {LedState.BUSY, LedState.APPROVAL, LedState.ERROR}:
            play_complete_sound()


def play_approval_sound() -> None:
    play_sound("approval")


def play_complete_sound() -> None:
    play_sound("complete")


def play_sound(kind: str) -> None:
    try:
        path = selected_sound_path(kind) or _ensure_sound_file(kind)
        _play_sound_file(path)
    except Exception as exc:
        logging.debug("sound unavailable: %s", exc)


def available_sound_options(kind: str) -> list[SoundOption]:
    _validate_sound_kind(kind)
    options = [SoundOption(DEFAULT_SOUND, "Default tone", _ensure_sound_file(kind))]
    for filename in BUNDLED_SOUNDS:
        bundled = bundled_sound_path(filename)
        if bundled.exists():
            options.append(SoundOption(_bundled_sound_id(filename), bundled.name, bundled))
    selected = load_sound_path(kind)
    if selected and selected.exists() and all(not _same_sound_option(option.path, selected) for option in options):
        options.append(SoundOption(str(selected), selected.name, selected))
    return options


def load_sound_path(kind: str) -> Path | None:
    _validate_sound_kind(kind)
    value = _read_sound_settings().get(kind)
    if not isinstance(value, str) or value == DEFAULT_SOUND:
        return None
    if value.startswith(BUNDLED_SOUND_PREFIX):
        return bundled_sound_path(value.removeprefix(BUNDLED_SOUND_PREFIX))
    return Path(value)


def selected_sound_path(kind: str) -> Path | None:
    path = load_sound_path(kind)
    if path and path.exists():
        return path
    if path and path.name == "F1TR.wav":
        bundled = bundled_sound_path("F1TR.wav")
        if bundled.exists():
            return bundled
    return None


def selected_sound_id(kind: str) -> str:
    path = selected_sound_path(kind)
    bundled_id = _bundled_sound_id_for_path(path)
    if bundled_id:
        return bundled_id
    return str(path) if path else DEFAULT_SOUND


def selected_sound_label(kind: str) -> str:
    path = selected_sound_path(kind)
    return path.name if path else "Default tone"


def set_sound_file(kind: str, path: str | Path) -> None:
    _validate_sound_kind(kind)
    resolved = Path(path).expanduser().resolve()
    settings = _read_sound_settings()
    settings[kind] = _bundled_sound_id_for_path(resolved) or str(resolved)
    _write_sound_settings(settings)


def reset_sound(kind: str) -> None:
    _validate_sound_kind(kind)
    settings = _read_sound_settings()
    settings[kind] = DEFAULT_SOUND
    _write_sound_settings(settings)


def bundled_sound_path(filename: str) -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS) / "cc_led"
    else:
        base = Path(__file__).resolve().parent
    return base / "assets" / "sounds" / filename


def _bundled_sound_id(filename: str) -> str:
    return f"{BUNDLED_SOUND_PREFIX}{filename}"


def _bundled_sound_id_for_path(path: Path | None) -> str | None:
    if not path:
        return None
    for filename in BUNDLED_SOUNDS:
        if path.name == filename and bundled_sound_path(filename).exists():
            return _bundled_sound_id(filename)
    return None


def _same_sound_option(option_path: Path | None, selected_path: Path) -> bool:
    if option_path == selected_path:
        return True
    return _bundled_sound_id_for_path(option_path) == _bundled_sound_id_for_path(selected_path)


def sound_settings_path() -> Path:
    return app_data_dir() / "sound_settings.json"


def _ensure_sound_file(kind: str):
    _validate_sound_kind(kind)
    directory = app_data_dir() / "sounds"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{kind}.wav"
    if path.exists():
        return path

    if kind == "approval":
        tones = [(880, 0.11), (0, 0.04), (880, 0.11), (0, 0.04), (660, 0.14)]
    else:
        tones = [(523, 0.10), (659, 0.10), (784, 0.16)]
    _write_tones(path, tones)
    return path


def _play_sound_file(path: Path) -> None:
    if path.suffix.lower() == ".wav":
        try:
            import winsound

            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
            return
        except Exception:
            logging.debug("winsound playback failed", exc_info=True)
    _play_with_mci(path)


def _play_with_mci(path: Path) -> None:
    import ctypes

    winmm = ctypes.windll.winmm
    alias = f"ccled_{uuid.uuid4().hex}"

    def send(command: str) -> str:
        buffer = ctypes.create_unicode_buffer(255)
        error = winmm.mciSendStringW(command, buffer, len(buffer), 0)
        if error:
            error_buffer = ctypes.create_unicode_buffer(255)
            winmm.mciGetErrorStringW(error, error_buffer, len(error_buffer))
            raise RuntimeError(error_buffer.value or f"MCI error {error}")
        return buffer.value

    def open_file() -> None:
        try:
            send(f'open "{path}" alias {alias}')
        except RuntimeError:
            send(f'open "{path}" type mpegvideo alias {alias}')

    def worker() -> None:
        try:
            open_file()
            send(f"play {alias}")
            for _ in range(600):
                time.sleep(0.1)
                mode = send(f"status {alias} mode")
                if mode in {"stopped", "not ready"}:
                    break
        except Exception:
            logging.debug("MCI playback failed", exc_info=True)
        finally:
            try:
                send(f"close {alias}")
            except Exception:
                pass

    threading.Thread(target=worker, daemon=True).start()


def _read_sound_settings() -> dict[str, Any]:
    try:
        with sound_settings_path().open("r", encoding="utf-8-sig") as handle:
            parsed = json.load(handle)
        return parsed if isinstance(parsed, dict) else {}
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def _write_sound_settings(settings: dict[str, Any]) -> None:
    path = sound_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(settings, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _validate_sound_kind(kind: str) -> None:
    if kind not in SOUND_KINDS:
        raise ValueError(f"Unknown sound kind: {kind}")


def _write_tones(path, tones: list[tuple[int, float]]) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        for frequency, duration in tones:
            samples = int(SAMPLE_RATE * duration)
            for index in range(samples):
                if frequency <= 0:
                    value = 0
                else:
                    envelope = min(1.0, index / max(1, SAMPLE_RATE * 0.01))
                    tail = min(1.0, (samples - index) / max(1, SAMPLE_RATE * 0.02))
                    amplitude = int(12000 * min(envelope, tail))
                    value = int(amplitude * math.sin(2 * math.pi * frequency * index / SAMPLE_RATE))
                wav.writeframesraw(struct.pack("<h", value))
