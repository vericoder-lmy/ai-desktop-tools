from __future__ import annotations

import logging
import time

from .config import DEFAULT_PORT, log_path
from .events import GlobalState
from .health import HealthMonitor
from .reducer import SessionStore
from .server import StateServer
from .sound import SoundPlayer
from .ui.overlay import OverlayWindow
from .ui.tray import TrayController


class CCLedApp:
    def __init__(self, port: int = DEFAULT_PORT) -> None:
        self.store = SessionStore()
        self.tray = TrayController(self.store)
        self.overlay: OverlayWindow | None = None
        self.sound = SoundPlayer()
        self.server = StateServer(self.store, port=port, on_state_change=self._on_state_change)
        self.health = HealthMonitor(self.store, interval_seconds=0.5, on_state_change=self._on_health_tick)

    def run(self) -> int:
        setup_logging()
        self.server.start()
        self.health.start()
        self.overlay = OverlayWindow(self.store, on_exit=self.stop)
        self.tray.start(on_exit=self.stop)
        logging.info("CC LED server started")
        try:
            self.overlay.run()
        finally:
            self.stop()
        return 0

    def stop(self) -> None:
        self.health.stop()
        self.server.stop()
        self.tray.stop()

    def _on_state_change(self, state: GlobalState) -> None:
        logging.info("state=%s event=%s sessions=%s", state.led.value, state.last_event, state.session_count)
        self.sound.handle_transition(state)
        self.tray.update(state)
        if self.overlay:
            self.overlay.update(state)

    def _on_health_tick(self) -> None:
        state = self.store.aggregate()
        self.tray.update(state)
        if self.overlay:
            self.overlay.update(state)


def setup_logging() -> None:
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def run_tray_app(port: int | None = None) -> int:
    try:
        return CCLedApp(port=port or DEFAULT_PORT).run()
    except ImportError as exc:
        print(f"Missing GUI dependency: {exc}. Install requirements.txt and run again.")
        return 2
    except OSError as exc:
        print(f"Unable to start CC LED: {exc}")
        time.sleep(1)
        return 1
