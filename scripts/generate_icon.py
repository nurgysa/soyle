"""Generate a placeholder `icon.ico` for the PyInstaller build.

The real design is TBD — this writes a simple dark blue circle with a
white "W" glyph. Multi-resolution (.ico carries 16/32/48/64/128/256px
so Windows picks the right one for Explorer, tray, alt-tab, etc).

Run from the project root:

    uv run python scripts/generate_icon.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "src" / "whisperflow" / "assets" / "icon.ico"
SIZES = [16, 32, 48, 64, 128, 256]

BG = (30, 88, 168, 255)     # deep blue
FG = (255, 255, 255, 255)   # white glyph
PAD_RATIO = 0.12            # transparent margin around the circle


def _render(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = int(size * PAD_RATIO)
    d.ellipse((pad, pad, size - pad, size - pad), fill=BG)

    # Glyph: bold W. At small sizes a font can alias badly, so fall back
    # to drawing strokes for sizes < 24.
    if size >= 24:
        try:
            font = ImageFont.truetype("arialbd.ttf", int(size * 0.55))
        except OSError:
            font = ImageFont.load_default()
        glyph = "W"
        bbox = d.textbbox((0, 0), glyph, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        d.text(
            ((size - w) / 2 - bbox[0], (size - h) / 2 - bbox[1] - size * 0.02),
            glyph,
            font=font,
            fill=FG,
        )
    else:
        # Tiny icon: three diagonal strokes approximating W.
        stroke = max(1, size // 8)
        inset = int(size * 0.3)
        d.line([(inset, inset), (size // 2 - 1, size - inset)], fill=FG, width=stroke)
        d.line([(size // 2 - 1, size - inset), (size // 2 + 1, size - inset)], fill=FG, width=stroke)
        d.line([(size // 2 + 1, size - inset), (size - inset, inset)], fill=FG, width=stroke)
    return img


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames = [_render(s) for s in SIZES]
    # Pillow's ICO writer takes the largest image and a `sizes` list.
    frames[-1].save(OUT, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes, {len(SIZES)} sizes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
