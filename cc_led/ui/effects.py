from __future__ import annotations

import json
import math
from enum import Enum
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..config import OVERLAY_DEFAULT_SCALE, OVERLAY_MAX_SCALE, OVERLAY_MIN_SCALE, app_data_dir
from ..events import GlobalState, LedState, display_led, should_blink


class OverlayEffect(str, Enum):
    CLASSIC = "classic"
    APPLE_GLASS = "apple_glass"
    REAL_LED = "real_led"
    FLAT_DOTS = "flat_dots"


class OverlayOrientation(str, Enum):
    VERTICAL = "vertical"
    HORIZONTAL = "horizontal"


EFFECT_LABELS = {
    OverlayEffect.CLASSIC: "Classic",
    OverlayEffect.APPLE_GLASS: "Apple Glass",
    OverlayEffect.REAL_LED: "Real LED",
    OverlayEffect.FLAT_DOTS: "Pixel",
}

ORIENTATION_LABELS = {
    OverlayOrientation.VERTICAL: "Vertical",
    OverlayOrientation.HORIZONTAL: "Horizontal",
}

EFFECT_BACKGROUNDS = {
    OverlayEffect.CLASSIC: "#111318",
    OverlayEffect.APPLE_GLASS: "#111318",
    OverlayEffect.REAL_LED: "#0d0f13",
    OverlayEffect.FLAT_DOTS: "#111318",
}

LIGHT_COLORS = {
    LedState.ERROR: (235, 76, 82),
    LedState.BUSY: (247, 190, 67),
    LedState.IDLE: (48, 199, 128),
}

OVERLAY_DEFAULT_OPACITY = 0.94
OVERLAY_MIN_OPACITY = 0.1
OVERLAY_MAX_OPACITY = 1.0


def render_overlay_image(
    effect: OverlayEffect,
    state: GlobalState,
    blink_on: bool,
    scale: float,
    orientation: OverlayOrientation = OverlayOrientation.VERTICAL,
) -> Image.Image:
    width, height = overlay_size(scale, orientation)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")
    active_led = display_led(state.led)
    blinking = should_blink(state.led)

    if effect == OverlayEffect.CLASSIC:
        _draw_classic_panel(image, draw, scale)
    elif effect == OverlayEffect.REAL_LED:
        _draw_real_panel(image, draw, scale)
    elif effect == OverlayEffect.FLAT_DOTS:
        _draw_flat_panel(image, draw, scale)
    else:
        _draw_apple_panel(image, draw, scale)

    centers, radius = _light_centers(image, scale, orientation)

    for x, y, led in centers:
        lit = active_led == led and (not blinking or blink_on)
        if effect == OverlayEffect.CLASSIC:
            _draw_classic_light(image, x, y, radius, LIGHT_COLORS[led], lit)
        elif effect == OverlayEffect.REAL_LED:
            _draw_real_light(image, x, y, radius, LIGHT_COLORS[led], lit)
        elif effect == OverlayEffect.FLAT_DOTS:
            _draw_pixel_light(image, x, y, radius, LIGHT_COLORS[led], lit, scale)
        else:
            _draw_apple_light(image, x, y, radius, LIGHT_COLORS[led], lit)

    return _clean_alpha_edges(_clip_to_panel(image, scale, effect))


def load_overlay_effect() -> OverlayEffect:
    try:
        data = _load_settings()
        value = data.get("effect", OverlayEffect.APPLE_GLASS.value)
        return OverlayEffect(value)
    except Exception:
        return OverlayEffect.APPLE_GLASS


def save_overlay_effect(effect: OverlayEffect) -> None:
    data = _load_settings()
    data["effect"] = effect.value
    _save_settings(data)


def load_overlay_orientation() -> OverlayOrientation:
    try:
        data = _load_settings()
        value = data.get("orientation", OverlayOrientation.VERTICAL.value)
        return OverlayOrientation(value)
    except Exception:
        return OverlayOrientation.VERTICAL


def save_overlay_orientation(orientation: OverlayOrientation) -> None:
    data = _load_settings()
    data["orientation"] = orientation.value
    _save_settings(data)


def load_overlay_scale() -> float:
    try:
        value = float(_load_settings().get("scale", OVERLAY_DEFAULT_SCALE))
    except Exception:
        value = OVERLAY_DEFAULT_SCALE
    value = min(OVERLAY_MAX_SCALE, max(OVERLAY_MIN_SCALE, value))
    return round(value, 1)


def save_overlay_scale(scale: float) -> None:
    data = _load_settings()
    data["scale"] = round(min(OVERLAY_MAX_SCALE, max(OVERLAY_MIN_SCALE, scale)), 1)
    _save_settings(data)


def load_overlay_opacity() -> float:
    try:
        value = float(_load_settings().get("opacity", OVERLAY_DEFAULT_OPACITY))
    except Exception:
        value = OVERLAY_DEFAULT_OPACITY
    value = min(OVERLAY_MAX_OPACITY, max(OVERLAY_MIN_OPACITY, value))
    return round(value, 1)


def save_overlay_opacity(opacity: float) -> None:
    data = _load_settings()
    data["opacity"] = round(min(OVERLAY_MAX_OPACITY, max(OVERLAY_MIN_OPACITY, opacity)), 1)
    _save_settings(data)


def _load_settings() -> dict:
    path = _settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_settings(data: dict) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def overlay_size(
    scale: float,
    orientation: OverlayOrientation = OverlayOrientation.VERTICAL,
) -> tuple[int, int]:
    short = round(108 * scale)
    long = round(246 * scale)
    if orientation == OverlayOrientation.HORIZONTAL:
        return long, short
    return short, long


def _settings_path() -> Path:
    return app_data_dir() / "ui.json"


def _draw_classic_panel(image: Image.Image, draw: ImageDraw.ImageDraw, scale: float) -> None:
    width, height = image.size
    rect = _panel_rect(image, scale)
    radius = _panel_radius(scale)
    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow, "RGBA")
    shadow_draw.rounded_rectangle(_offset(rect, 0, round(5 * scale)), radius, fill=(0, 0, 0, 95))
    image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(round(7 * scale))))
    draw.rounded_rectangle(rect, radius, fill=(17, 19, 24, 232), outline=(64, 70, 80, 230), width=max(1, round(1.5 * scale)))
    draw.rounded_rectangle(_inset(rect, round(3 * scale)), radius - round(3 * scale), outline=(255, 255, 255, 32), width=1)


def _draw_apple_panel(image: Image.Image, draw: ImageDraw.ImageDraw, scale: float) -> None:
    width, height = image.size
    rect = _panel_rect(image, scale)
    radius = _panel_radius(scale)
    panel = Image.new("RGBA", image.size, (0, 0, 0, 0))
    panel_draw = ImageDraw.Draw(panel, "RGBA")
    panel_draw.rounded_rectangle(
        rect,
        radius,
        fill=(24, 28, 36, 238),
        outline=(112, 122, 138, 180),
        width=max(1, round(1.4 * scale)),
    )
    panel_draw.rounded_rectangle(
        _inset(rect, round(3 * scale)),
        radius - round(3 * scale),
        outline=(255, 255, 255, 36),
        width=1,
    )
    image.alpha_composite(panel)


def _draw_real_panel(image: Image.Image, draw: ImageDraw.ImageDraw, scale: float) -> None:
    width, height = image.size
    rect = _panel_rect(image, scale)
    radius = _panel_radius(scale)
    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow, "RGBA")
    shadow_draw.rounded_rectangle(_offset(rect, 0, round(5 * scale)), radius, fill=(0, 0, 0, 94))
    image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(round(8 * scale))))

    panel = Image.new("RGBA", image.size, (0, 0, 0, 0))
    panel_draw = ImageDraw.Draw(panel, "RGBA")
    panel_mask = Image.new("L", image.size, 0)
    mask_draw = ImageDraw.Draw(panel_mask)
    mask_draw.rounded_rectangle(rect, radius, fill=255)
    top = rect[1]
    bottom = rect[3]
    for y in range(top, bottom):
        t = (y - top) / max(1, bottom - top)
        shade = 22 - round(9 * t)
        panel_draw.line((rect[0], y, rect[2], y), fill=(shade, shade + 2, shade + 7, 245))
    panel.putalpha(panel_mask)
    image.alpha_composite(panel)

    draw.rounded_rectangle(rect, radius, outline=(112, 116, 126, 240), width=max(1, round(2 * scale)))
    draw.rounded_rectangle(_inset(rect, round(4 * scale)), radius - round(4 * scale), outline=(255, 255, 255, 24), width=1)
    x1, y1, x2, y2 = rect
    draw.line((x1 + round(8 * scale), y1 + round(14 * scale), x1 + round(8 * scale), y2 - round(14 * scale)), fill=(255, 255, 255, 18), width=1)
    draw.line((x2 - round(8 * scale), y1 + round(14 * scale), x2 - round(8 * scale), y2 - round(14 * scale)), fill=(0, 0, 0, 72), width=1)


def _draw_flat_panel(image: Image.Image, draw: ImageDraw.ImageDraw, scale: float) -> None:
    width, height = image.size
    rect = _panel_rect(image, scale)
    block = max(2, round(4 * scale))
    x1, y1, x2, y2 = rect
    draw.rectangle(rect, fill=(16, 19, 25, 255))
    draw.rectangle(rect, outline=(88, 96, 111, 230), width=max(1, block // 2))
    draw.rectangle((x1 + block, y1 + block, x2 - block, y2 - block), outline=(6, 8, 12, 255), width=max(1, block // 2))
    draw.rectangle((x1 + block * 2, y1 + block * 2, x2 - block * 2, y2 - block * 2), outline=(255, 255, 255, 28), width=1)


def _draw_classic_light(image: Image.Image, x: int, y: int, radius: int, color: tuple[int, int, int], lit: bool) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    if lit:
        _glow(image, x, y, radius + 9, color, 72)
    draw.ellipse(_circle(x + round(2 * radius / 26), y + round(3 * radius / 26), radius + 5), fill=(0, 0, 0, 82))
    draw.ellipse(_circle(x, y, radius + 4), fill=(40, 45, 54, 255), outline=(5, 6, 8, 170), width=2)
    base = color if lit else _mix(color, (42, 47, 55), 0.68)
    _radial_disc(image, x, y, radius, base, lit, glass=True)



def _draw_apple_light(image: Image.Image, x: int, y: int, radius: int, color: tuple[int, int, int], lit: bool) -> None:
    if lit:
        _glow(image, x, y, radius + 10, color, 86)
    draw = ImageDraw.Draw(image, "RGBA")
    outer = _circle(x, y, radius + 4)
    draw.ellipse(outer, fill=(55, 61, 72, 255), outline=(190, 198, 210, 135), width=1)
    draw.ellipse(_circle(x, y, radius + 2), outline=(6, 8, 12, 185), width=1)
    base = color if lit else _mix(color, (40, 44, 52), 0.72)
    _radial_disc(image, x, y, radius, base, lit, glass=True)


def _draw_real_light(image: Image.Image, x: int, y: int, radius: int, color: tuple[int, int, int], lit: bool) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    if lit:
        _glow(image, x, y, radius + 17, color, 132)
    draw.ellipse(_circle(x + round(2 * radius / 25), y + round(4 * radius / 25), radius + 9), fill=(0, 0, 0, 118))
    draw.ellipse(_circle(x, y, radius + 8), fill=(34, 36, 42, 255), outline=(7, 8, 11, 230), width=max(1, radius // 11))
    draw.arc(_circle(x, y, radius + 8), 208, 335, fill=(232, 235, 240, 148), width=max(1, radius // 8))
    draw.arc(_circle(x, y, radius + 7), 28, 154, fill=(0, 0, 0, 122), width=max(1, radius // 7))
    draw.ellipse(_circle(x, y, radius + 4), fill=(12, 14, 18, 255), outline=(126, 132, 144, 108), width=1)
    draw.ellipse(_circle(x, y, radius + 1), fill=(18, 21, 27, 255), outline=(0, 0, 0, 172), width=1)
    base = color if lit else _mix(color, (28, 31, 37), 0.68)
    _radial_disc(image, x, y, radius, base, lit, glass=True)
    lens = Image.new("RGBA", image.size, (0, 0, 0, 0))
    lens_draw = ImageDraw.Draw(lens, "RGBA")
    lens_draw.pieslice(_circle(x, y - radius // 3, radius), 195, 345, fill=(255, 255, 255, 34 if lit else 18))
    lens_draw.arc(_circle(x - radius // 8, y - radius // 6, radius - 3), 205, 330, fill=(255, 255, 255, 126 if lit else 48), width=max(1, radius // 9))
    lens_draw.ellipse(_circle(x, y, radius), outline=(255, 255, 255, 42 if lit else 24), width=1)
    image.alpha_composite(lens)


def _draw_pixel_light(
    image: Image.Image,
    x: int,
    y: int,
    radius: int,
    color: tuple[int, int, int],
    lit: bool,
    scale: float,
) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    cell = max(3, round(4 * scale))
    grid_radius = max(1, radius // cell)
    size = grid_radius * 2 + 1
    left = x - grid_radius * cell
    top = y - grid_radius * cell
    draw.rectangle(
        (left - cell, top - cell, left + size * cell, top + size * cell),
        fill=(3, 4, 7, 255),
    )
    draw.rectangle(
        (left - cell, top - cell, left + size * cell, top + size * cell),
        outline=(91, 101, 118, 220),
        width=max(1, cell // 2),
    )
    base = color if lit else _mix(color, (24, 29, 36), 0.78)
    for row in range(size):
        for col in range(size):
            dx = col - grid_radius
            dy = row - grid_radius
            distance = math.sqrt(dx * dx + dy * dy)
            if distance > grid_radius + 0.2:
                continue
            t = distance / max(1, grid_radius)
            highlight = max(0, 1 - math.sqrt((dx + grid_radius * 0.35) ** 2 + (dy + grid_radius * 0.45) ** 2) / grid_radius)
            shade = 0.88 - 0.28 * t + 0.28 * highlight
            if lit:
                shade += 0.14
            rgb = tuple(max(0, min(255, int(c * shade + 255 * highlight * 0.08))) for c in base)
            alpha = 255
            x1 = left + col * cell
            y1 = top + row * cell
            draw.rectangle((x1, y1, x1 + cell - 1, y1 + cell - 1), fill=(*rgb, alpha))
    draw.rectangle(
        (left, top, left + size * cell - 1, top + size * cell - 1),
        outline=(255, 255, 255, 34 if lit else 22),
        width=1,
    )


def _radial_disc(image: Image.Image, x: int, y: int, radius: int, color: tuple[int, int, int], lit: bool, glass: bool) -> None:
    disc = Image.new("RGBA", image.size, (0, 0, 0, 0))
    px = disc.load()
    for yy in range(y - radius, y + radius + 1):
        for xx in range(x - radius, x + radius + 1):
            dx = xx - x
            dy = yy - y
            distance = math.sqrt(dx * dx + dy * dy)
            if distance > radius:
                continue
            t = distance / radius
            highlight = max(0, 1 - math.sqrt((xx - (x - radius * 0.35)) ** 2 + (yy - (y - radius * 0.45)) ** 2) / radius)
            shade = 0.88 - 0.34 * t + 0.35 * highlight
            if lit:
                shade += 0.12
            rgb = tuple(max(0, min(255, int(c * shade + 255 * highlight * (0.18 if glass else 0.08)))) for c in color)
            alpha = 255 if lit else (150 if glass else 170)
            px[xx, yy] = (*rgb, alpha)
    image.alpha_composite(disc)


def _glow(image: Image.Image, x: int, y: int, radius: int, color: tuple[int, int, int], alpha: int) -> None:
    glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow, "RGBA")
    draw.ellipse(_circle(x, y, radius), fill=(*color, alpha))
    image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(max(1, radius // 3))))


def _draw_status_text(image: Image.Image, state: GlobalState, scale: float, effect: OverlayEffect) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    text = f"{state.led.value}"
    if state.last_event:
        text += f" / {state.last_event}"
    font = _font(max(8, round(8 * scale)))
    bbox = draw.textbbox((0, 0), text, font=font)
    x = (image.size[0] - (bbox[2] - bbox[0])) // 2
    y = image.size[1] - round(17 * scale)
    fill = (219, 224, 232, 210) if effect == OverlayEffect.REAL_LED else (65, 72, 84, 220)
    draw.text((x, y), text, font=font, fill=fill)


def _light_centers(
    image: Image.Image,
    scale: float,
    orientation: OverlayOrientation,
) -> tuple[list[tuple[int, int, LedState]], int]:
    width, height = image.size
    radius = round(27 * scale)
    gap = round(17 * scale)
    offset = round(20 * scale)
    if orientation == OverlayOrientation.HORIZONTAL:
        center_y = height // 2
        return (
            [
                (offset + radius, center_y, LedState.ERROR),
                (offset + radius * 3 + gap, center_y, LedState.BUSY),
                (offset + radius * 5 + gap * 2, center_y, LedState.IDLE),
            ],
            radius,
        )
    center_x = width // 2
    return (
        [
            (center_x, offset + radius, LedState.ERROR),
            (center_x, offset + radius * 3 + gap, LedState.BUSY),
            (center_x, offset + radius * 5 + gap * 2, LedState.IDLE),
        ],
        radius,
    )


def _font(size: int):
    for name in ("segoeui.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _circle(x: int, y: int, radius: int) -> tuple[int, int, int, int]:
    return (x - radius, y - radius, x + radius, y + radius)


def _inset(rect: tuple[int, int, int, int], amount: int) -> tuple[int, int, int, int]:
    return (rect[0] + amount, rect[1] + amount, rect[2] - amount, rect[3] - amount)


def _offset(rect: tuple[int, int, int, int], dx: int, dy: int) -> tuple[int, int, int, int]:
    return (rect[0] + dx, rect[1] + dy, rect[2] + dx, rect[3] + dy)


def _panel_rect(image: Image.Image, scale: float) -> tuple[int, int, int, int]:
    x_margin = max(1, round(8 * scale))
    y_margin = max(1, round(8 * scale))
    return (x_margin, y_margin, image.size[0] - x_margin, image.size[1] - y_margin)


def _panel_radius(scale: float) -> int:
    return max(1, round(25 * scale))


def _rgb(value: tuple[int, int, int]) -> str:
    return f"#{value[0]:02x}{value[1]:02x}{value[2]:02x}"


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] * (1 - t) + b[i] * t) for i in range(3))


def _clean_alpha_edges(image: Image.Image) -> Image.Image:
    if image.mode != "RGBA":
        return image
    r, g, b, alpha = image.split()
    # Binary clamp: no semi-transparent edge pixels against Tk background.
    alpha = alpha.point(lambda value: 0 if value <= 48 else 255)
    image.putalpha(alpha)
    return image


def _clip_to_panel(image: Image.Image, scale: float, effect: OverlayEffect) -> Image.Image:
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    mask = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(mask)
    if effect == OverlayEffect.FLAT_DOTS:
        draw.rectangle(_panel_rect(image, scale), fill=255)
    else:
        draw.rounded_rectangle(_panel_rect(image, scale), _panel_radius(scale), fill=255)
    flattened = Image.new("RGBA", image.size, (*_hex_to_rgb(EFFECT_BACKGROUNDS[effect]), 255))
    flattened.alpha_composite(image)
    flattened.putalpha(mask)
    return flattened


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))
