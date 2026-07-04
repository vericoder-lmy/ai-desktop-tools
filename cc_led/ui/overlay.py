from __future__ import annotations

import tkinter as tk
from queue import Empty, Queue
from typing import Callable

from ..config import (
    OVERLAY_BACKGROUND_COLOR,
    OVERLAY_BLINK_INTERVAL_MS,
    OVERLAY_MAX_SCALE,
    OVERLAY_MIN_SCALE,
)
from ..events import GlobalState, LedState, should_blink
from ..reducer import SessionStore
from .effects import (
    EFFECT_BACKGROUNDS,
    EFFECT_LABELS,
    ORIENTATION_LABELS,
    OverlayEffect,
    OverlayOrientation,
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


PERCENTAGES = tuple(range(10, 101, 10))
SCALE_STEP = 0.1


class OverlayWindow:
    def __init__(self, store: SessionStore, on_exit: Callable[[], None] | None = None) -> None:
        self.store = store
        self.on_exit = on_exit
        self.root = tk.Tk()
        self.root.title("CC LED")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=OVERLAY_BACKGROUND_COLOR)

        self.scale = load_overlay_scale()
        self.opacity = load_overlay_opacity()
        self.effect = load_overlay_effect()
        self.orientation = load_overlay_orientation()
        self._effect_var = tk.StringVar(value=self.effect.value)
        self._orientation_var = tk.StringVar(value=self.orientation.value)
        self._scale_var = tk.IntVar(value=self._scale_percent())
        self._opacity_var = tk.IntVar(value=self._opacity_percent())
        self.root.wm_attributes("-alpha", self.opacity)
        self.current_state = self.store.aggregate()
        self._updates: Queue[GlobalState] = Queue()
        self._blink_on = True
        self._state_key = self._make_state_key(self.current_state)
        self._drag_origin: tuple[int, int] | None = None
        self._window_origin: tuple[int, int] | None = None
        self._photo = None
        self._image_item: int | None = None
        self._last_size: tuple[int, int] | None = None
        self._shape_key: tuple[str, float, int, int] | None = None
        self._last_bg: str | None = None

        self.canvas = tk.Canvas(self.root, highlightthickness=0, bd=0, bg=OVERLAY_BACKGROUND_COLOR)
        self.canvas.pack(fill="both", expand=True)
        self._bind_events()
        self._render()
        self.root.after(100, self._poll_updates)
        self.root.after(OVERLAY_BLINK_INTERVAL_MS, self._blink_tick)

    def run(self) -> None:
        self.root.mainloop()

    def close(self) -> None:
        try:
            self.root.quit()
            self.root.destroy()
        except tk.TclError:
            pass

    def update(self, state: GlobalState) -> None:
        self._updates.put(state)

    def _poll_updates(self) -> None:
        changed = False
        state_changed = False
        while True:
            try:
                next_state = self._updates.get_nowait()
                next_key = self._make_state_key(next_state)
                if next_key != self._state_key:
                    state_changed = True
                    self._state_key = next_key
                self.current_state = next_state
                changed = True
            except Empty:
                break
        if changed:
            if state_changed:
                self._blink_on = True
            self._render()
        try:
            self.root.after(100, self._poll_updates)
        except tk.TclError:
            pass

    def _bind_events(self) -> None:
        self.canvas.bind("<ButtonPress-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<MouseWheel>", self._mousewheel_resize)
        self.canvas.bind("<Button-4>", lambda _event: self._resize(SCALE_STEP))
        self.canvas.bind("<Button-5>", lambda _event: self._resize(-SCALE_STEP))
        self.canvas.bind("<Double-Button-1>", lambda _event: self._cycle_manual_state())
        self.canvas.bind("<Button-3>", self._show_menu)
        self.root.bind("<Escape>", lambda _event: self._exit())

    def _render(self) -> None:
        try:
            from PIL import ImageTk
        except ImportError as exc:
            raise ImportError("Pillow is required for overlay effects") from exc

        width, height = overlay_size(self.scale, self.orientation)
        size = (width, height)
        if size != self._last_size:
            self.root.geometry(f"{width}x{height}")
            self.canvas.config(width=width, height=height)
            self._last_size = size
        image = render_overlay_image(self.effect, self.current_state, self._blink_on, self.scale, self.orientation)
        bg = EFFECT_BACKGROUNDS.get(self.effect, OVERLAY_BACKGROUND_COLOR)
        if bg != self._last_bg:
            self.root.configure(bg=bg)
            self.canvas.configure(bg=bg)
            self._last_bg = bg
        shape_key = (self.effect.value, self.orientation.value, round(self.scale, 3), width, height)
        if shape_key != self._shape_key:
            self._apply_image_shape(image)
            self._shape_key = shape_key
        self._photo = ImageTk.PhotoImage(image)
        if self._image_item is None:
            self._image_item = self.canvas.create_image(0, 0, anchor="nw", image=self._photo)
        else:
            self.canvas.itemconfig(self._image_item, image=self._photo)

    def _start_drag(self, event: tk.Event) -> None:
        self._drag_origin = (event.x_root, event.y_root)
        self._window_origin = (self.root.winfo_x(), self.root.winfo_y())

    def _drag(self, event: tk.Event) -> None:
        if not self._drag_origin or not self._window_origin:
            return
        dx = event.x_root - self._drag_origin[0]
        dy = event.y_root - self._drag_origin[1]
        self.root.geometry(f"+{self._window_origin[0] + dx}+{self._window_origin[1] + dy}")

    def _mousewheel_resize(self, event: tk.Event) -> None:
        self._resize(SCALE_STEP if event.delta > 0 else -SCALE_STEP)

    def _resize(self, delta: float) -> None:
        self._set_scale(self.scale + delta)

    def _set_scale(self, scale: float) -> None:
        scale = round(scale, 1)
        self.scale = min(OVERLAY_MAX_SCALE, max(OVERLAY_MIN_SCALE, scale))
        self._scale_var.set(self._scale_percent())
        save_overlay_scale(self.scale)
        self._render()

    def _set_opacity(self, opacity: float) -> None:
        self.opacity = min(1.0, max(0.1, round(opacity, 1)))
        self._opacity_var.set(self._opacity_percent())
        save_overlay_opacity(self.opacity)
        self.root.wm_attributes("-alpha", self.opacity)

    def _blink_tick(self) -> None:
        if should_blink(self.current_state.led):
            self._blink_on = not self._blink_on
            self._render()
        else:
            self._blink_on = True
        try:
            self.root.after(OVERLAY_BLINK_INTERVAL_MS, self._blink_tick)
        except tk.TclError:
            pass

    def _cycle_manual_state(self) -> None:
        from ..events import HookEvent

        order = {
            LedState.IDLE: LedState.BUSY,
            LedState.BUSY: LedState.APPROVAL,
            LedState.APPROVAL: LedState.ERROR,
            LedState.ERROR: LedState.IDLE,
        }
        next_state = order[self.current_state.led]
        state = self.store.apply(
            HookEvent(source="manual", event=f"Manual{next_state.value.title()}", state=next_state, session_id="manual")
        )
        self.update(state)

    def _show_menu(self, event: tk.Event) -> None:
        menu = tk.Menu(self.root, tearoff=False)
        effect_menu = tk.Menu(menu, tearoff=False)
        for effect in OverlayEffect:
            effect_menu.add_radiobutton(
                label=EFFECT_LABELS[effect],
                value=effect.value,
                variable=self._effect_var,
                command=lambda selected=effect: self._set_effect(selected),
            )
        menu.add_cascade(label="Effect", menu=effect_menu)
        layout_menu = tk.Menu(menu, tearoff=False)
        for orientation in OverlayOrientation:
            layout_menu.add_radiobutton(
                label=ORIENTATION_LABELS[orientation],
                value=orientation.value,
                variable=self._orientation_var,
                command=lambda selected=orientation: self._set_orientation(selected),
            )
        menu.add_cascade(label="Layout", menu=layout_menu)
        menu.add_separator()
        scale_menu = tk.Menu(menu, tearoff=False)
        for percent in PERCENTAGES:
            scale_menu.add_radiobutton(
                label=f"{percent}%",
                value=percent,
                variable=self._scale_var,
                command=lambda selected=percent: self._set_scale(selected / 100),
            )
        menu.add_cascade(label="Size", menu=scale_menu)
        opacity_menu = tk.Menu(menu, tearoff=False)
        for percent in PERCENTAGES:
            opacity_menu.add_radiobutton(
                label=f"{percent}%",
                value=percent,
                variable=self._opacity_var,
                command=lambda selected=percent: self._set_opacity(selected / 100),
            )
        menu.add_cascade(label="Opacity", menu=opacity_menu)
        menu.add_separator()
        menu.add_command(label="Exit", command=self._exit)
        menu.tk_popup(event.x_root, event.y_root)

    def _set_manual(self, state: LedState) -> None:
        from ..events import HookEvent

        global_state = self.store.apply(
            HookEvent(source="manual", event=f"Manual{state.value.title()}", state=state, session_id="manual")
        )
        self.update(global_state)

    def _exit(self) -> None:
        if self.on_exit:
            self.on_exit()
        self.close()

    def _set_effect(self, effect: OverlayEffect) -> None:
        self.effect = effect
        self._effect_var.set(effect.value)
        save_overlay_effect(effect)
        self._render()

    def _set_orientation(self, orientation: OverlayOrientation) -> None:
        self.orientation = orientation
        self._orientation_var.set(orientation.value)
        save_overlay_orientation(orientation)
        self._last_size = None
        self._shape_key = None
        self._render()

    def _make_state_key(self, state: GlobalState) -> tuple[str, str | None, int]:
        return (state.led.value, state.last_event, state.session_count)

    def _scale_percent(self) -> int:
        return round(self.scale * 100)

    def _opacity_percent(self) -> int:
        return round(self.opacity * 100)

    def _apply_image_shape(self, image) -> None:
        if not self.root.tk.call("tk", "windowingsystem") == "win32":
            return
        try:
            import ctypes

            self.root.update_idletasks()
            hwnd = int(self.root.winfo_id())
            root_hwnd = int(ctypes.windll.user32.GetAncestor(hwnd, 2)) or hwnd
            _set_window_region(root_hwnd, image, ctypes)
            if root_hwnd != hwnd:
                _set_window_region(hwnd, image, ctypes)
        except Exception:
            pass


def _set_window_region(hwnd: int, image, ctypes) -> None:
    region = _region_from_alpha(image, ctypes)
    if not region:
        return
    result = ctypes.windll.user32.SetWindowRgn(hwnd, region, True)
    if result == 0:
        ctypes.windll.gdi32.DeleteObject(region)


def _alpha_runs(image, threshold: int = 32) -> list[tuple[int, int, int]]:
    alpha = image.getchannel("A")
    width, height = alpha.size
    pixels = alpha.load()
    runs: list[tuple[int, int, int]] = []
    for y in range(height):
        x = 0
        while x < width:
            while x < width and pixels[x, y] <= threshold:
                x += 1
            if x >= width:
                break
            start = x
            while x < width and pixels[x, y] > threshold:
                x += 1
            runs.append((y, start, x))
    return runs


def _region_from_alpha(image, ctypes, threshold: int = 32):
    gdi32 = ctypes.windll.gdi32
    region = gdi32.CreateRectRgn(0, 0, 0, 0)
    if not region:
        return 0

    RGN_OR = 2
    for y, start, end in _alpha_runs(image, threshold):
        row_region = gdi32.CreateRectRgn(start, y, end, y + 1)
        if row_region:
            gdi32.CombineRgn(region, region, row_region, RGN_OR)
            gdi32.DeleteObject(row_region)
    return region
