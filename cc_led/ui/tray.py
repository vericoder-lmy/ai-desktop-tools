from __future__ import annotations

from .icons import create_icon
from ..codex_installer import codex_hooks_installed, install_codex_hooks, uninstall_codex_hooks
from ..events import GlobalState, LedState, display_led
from ..installer import hooks_installed, install_hooks, uninstall_hooks
from ..reducer import SessionStore
from ..sound import (
    SUPPORTED_AUDIO_PATTERNS,
    available_sound_options,
    play_sound,
    reset_sound,
    selected_sound_id,
    selected_sound_label,
    set_sound_file,
)


class TrayController:
    def __init__(self, store: SessionStore) -> None:
        self.store = store
        self.icon = None

    def start(self, on_exit=None) -> None:
        self._create_icon(on_exit=on_exit)
        self.icon.run_detached()

    def run(self) -> None:
        self._create_icon()
        self.icon.run()

    def stop(self) -> None:
        if self.icon:
            self.icon.stop()

    def _create_icon(self, on_exit=None) -> None:
        try:
            import pystray
        except ImportError as exc:
            raise ImportError("pystray is required for tray UI") from exc

        menu = pystray.Menu(
            pystray.MenuItem(lambda item: self._status_title(), None, enabled=False),
            pystray.MenuItem("Set green", lambda icon, item: self._manual(LedState.IDLE)),
            pystray.MenuItem("Set yellow", lambda icon, item: self._manual(LedState.BUSY)),
            pystray.MenuItem("Set red", lambda icon, item: self._manual(LedState.ERROR)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda item: self._hook_label("Claude", hooks_installed()), self._toggle_claude_hooks),
            pystray.MenuItem(lambda item: self._hook_label("Codex", codex_hooks_installed()), self._toggle_codex_hooks),
            pystray.MenuItem("Sounds", self._sound_menu(pystray)),
            pystray.MenuItem("Clear error", lambda icon, item: self.update(self.store.clear_errors())),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", lambda icon, item: self._exit(icon, on_exit)),
        )
        state = self.store.aggregate()
        self.icon = pystray.Icon("cc-led", create_icon(display_led(state.led).value), self._tooltip(state), menu)

    def update(self, state: GlobalState) -> None:
        if not self.icon:
            return
        self.icon.icon = create_icon(display_led(state.led).value)
        self.icon.title = self._tooltip(state)
        # Force pystray to repaint the icon on Windows (run_detached mode)
        self.icon.visible = True

    def _manual(self, state: LedState) -> None:
        from ..events import HookEvent

        global_state = self.store.apply(
            HookEvent(source="manual", event=f"Manual{state.value.title()}", state=state, session_id="manual")
        )
        self.update(global_state)

    def _status_title(self) -> str:
        state = self.store.aggregate()
        return self._tooltip(state)

    def _tooltip(self, state: GlobalState) -> str:
        event = state.last_event or "idle"
        return f"CC LED: {state.led.value} - {event}"

    def _hook_label(self, name: str, installed: bool) -> str:
        return f"{chr(0x25CF) if installed else chr(0x25CB)} {name} hooks"

    def _toggle_claude_hooks(self, icon, item) -> None:
        if hooks_installed():
            uninstall_hooks()
        else:
            install_hooks()
        self._refresh_menu(icon)

    def _toggle_codex_hooks(self, icon, item) -> None:
        if codex_hooks_installed():
            uninstall_codex_hooks()
        else:
            install_codex_hooks()
        self._refresh_menu(icon)

    def _refresh_menu(self, icon) -> None:
        if hasattr(icon, "update_menu"):
            icon.update_menu()

    def _sound_menu(self, pystray):
        return pystray.Menu(
            pystray.MenuItem("Approval sound", self._sound_kind_menu(pystray, "approval")),
            pystray.MenuItem("Complete sound", self._sound_kind_menu(pystray, "complete")),
        )

    def _sound_kind_menu(self, pystray, kind: str):
        items = []
        for option in available_sound_options(kind):
            items.append(
                pystray.MenuItem(
                    self._sound_option_text(kind, option.id, option.label),
                    self._sound_option_action(kind, option.path),
                )
            )
        items.extend(
            [
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(self._current_sound_text(kind), None, enabled=False),
                pystray.MenuItem("Test", self._test_sound_action(kind)),
                pystray.MenuItem("Choose file...", self._choose_sound_action(kind)),
                pystray.MenuItem("Restore default", self._reset_sound_action(kind)),
            ]
        )
        return pystray.Menu(*items)

    def _sound_option_text(self, kind: str, option_id: str, label: str):
        def text(item) -> str:
            return self._sound_option_label(kind, option_id, label)

        return text

    def _sound_option_action(self, kind: str, path):
        def action(icon, item) -> None:
            self._select_sound(icon, kind, path)

        return action

    def _current_sound_text(self, kind: str):
        def text(item) -> str:
            return f"Current: {selected_sound_label(kind)}"

        return text

    def _test_sound_action(self, kind: str):
        def action(icon, item) -> None:
            play_sound(kind)

        return action

    def _choose_sound_action(self, kind: str):
        def action(icon, item) -> None:
            self._choose_sound_file(icon, kind)

        return action

    def _reset_sound_action(self, kind: str):
        def action(icon, item) -> None:
            self._reset_sound(icon, kind)

        return action

    def _sound_option_label(self, kind: str, option_id: str, label: str) -> str:
        selected = selected_sound_id(kind)
        marker = chr(0x25CF) if selected == option_id else chr(0x25CB)
        return f"{marker} {label}"

    def _select_sound(self, icon, kind: str, path) -> None:
        if path is None:
            reset_sound(kind)
        else:
            set_sound_file(kind, path)
        self._refresh_menu(icon)

    def _choose_sound_file(self, icon, kind: str) -> None:
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            filename = filedialog.askopenfilename(title="Choose sound", filetypes=SUPPORTED_AUDIO_PATTERNS)
            root.destroy()
        except Exception:
            return

        if filename:
            set_sound_file(kind, filename)
            self._refresh_menu(icon)

    def _reset_sound(self, icon, kind: str) -> None:
        reset_sound(kind)
        self._refresh_menu(icon)

    def _exit(self, icon, on_exit=None) -> None:
        icon.stop()
        if on_exit:
            on_exit()
