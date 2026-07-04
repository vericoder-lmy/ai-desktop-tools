from __future__ import annotations

from .theme import COLORS


def create_icon(state: str, size: int = 64):
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise ImportError("Pillow is required for tray icons") from exc

    fill = COLORS.get(state, COLORS["idle"])

    # Supersample: render at 4x then downscale for smooth antialiasing
    scale = 4
    big = size * scale
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    c = big // 2
    r = (big - big // 8) // 2

    # Shadow
    draw.ellipse((c - r + 4, c - r + 6, c + r + 4, c + r + 6), fill=(0, 0, 0, 55))

    # Main circle: single smooth ellipse, no dark border
    draw.ellipse((c - r, c - r, c + r, c + r), fill=fill)

    # Downscale with Lanczos for crisp edges
    img = img.resize((size, size), Image.LANCZOS)
    return img
