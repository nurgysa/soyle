"""Generate `icon.ico` for the PyInstaller build.

Design: deep-blue circle, white microphone (capsule + U-stand + base),
two concentric sound-wave arcs on either side. Multi-resolution
(.ico carries 16/32/48/64/128/256px). Sound waves are omitted at
<32px — they alias to noise at that scale. Stand detail is omitted
at ≤16px, where only the mic head remains legible.

All drawing coordinates are authored in a virtual 256-unit canvas and
scaled down per size, so proportions stay consistent across resolutions.

Run from the project root:

    uv run python scripts/generate_icon.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "src" / "whisperflow" / "assets" / "icon.ico"
SIZES = [16, 32, 48, 64, 128, 256]

BG = (30, 88, 168, 255)     # deep blue
FG = (255, 255, 255, 255)   # white


def _render(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Everything below is authored in 256-unit virtual coords.
    def sc(v: float) -> int:
        return int(round(v * size / 256))

    # Background circle with a small transparent margin so the shape
    # doesn't crop on circular-badge OSes (macOS dock, some Windows skins).
    pad = sc(12)
    d.ellipse((pad, pad, size - pad, size - pad), fill=BG)

    # --- Microphone capsule (head) ---
    mic_x1, mic_y1 = sc(96), sc(60)
    mic_x2, mic_y2 = sc(160), sc(156)
    d.rounded_rectangle(
        (mic_x1, mic_y1, mic_x2, mic_y2),
        radius=sc(32),
        fill=FG,
    )

    # --- Stand + base (skip on tiny sizes — aliases to a blob) ---
    if size >= 20:
        stand_stroke = max(2, sc(10))
        # U-arc under the capsule
        d.arc(
            (sc(80), sc(116), sc(176), sc(200)),
            start=0, end=180,
            fill=FG, width=stand_stroke,
        )
        # Vertical pole
        d.line(
            [(sc(128), sc(190)), (sc(128), sc(214))],
            fill=FG, width=stand_stroke,
        )
        # Horizontal base
        d.line(
            [(sc(100), sc(214)), (sc(156), sc(214))],
            fill=FG, width=stand_stroke,
        )

    # --- Sound-wave arcs (skip when detail would disappear) ---
    if size >= 32:
        wave_stroke = max(2, sc(7))
        # Inner arcs — closer to the mic
        d.arc(
            (sc(54), sc(72), sc(86), sc(144)),
            start=90, end=270,
            fill=FG, width=wave_stroke,
        )
        d.arc(
            (sc(170), sc(72), sc(202), sc(144)),
            start=-90, end=90,
            fill=FG, width=wave_stroke,
        )
        # Outer arcs — wider ripple
        d.arc(
            (sc(32), sc(56), sc(86), sc(160)),
            start=90, end=270,
            fill=FG, width=wave_stroke,
        )
        d.arc(
            (sc(170), sc(56), sc(224), sc(160)),
            start=-90, end=90,
            fill=FG, width=wave_stroke,
        )

    return img


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # Render at full 256px resolution — Pillow resamples (Lanczos) to each
    # smaller size via the `sizes=` kwarg. The per-size branches in
    # `_render` still matter: we call it once at max SIZE so the full
    # design is drawn; for previews/debug they can be invoked per-size.
    base = _render(max(SIZES))
    base.save(OUT, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes, {len(SIZES)} sizes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
