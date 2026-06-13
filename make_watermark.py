"""Generate the channel watermark PNG (Twitch glyph + nickname) used by the renderer.

    python make_watermark.py            # uses defaults below
    python make_watermark.py pareek_    # custom nickname

Writes assets/watermark.png (transparent, white text + purple Twitch glyph). The renderer
overlays it semi-transparent (opacity from config edit.watermark.opacity) over the gameplay.
Drop in your own assets/watermark.png anytime to replace it (e.g. the official Twitch logo).
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
WIN_FONTS = Path("C:/Windows/Fonts")
PURPLE = (145, 70, 255, 255)   # Twitch #9146FF
WHITE = (255, 255, 255, 255)

# Twitch "glitch" glyph as straight-line polygons in a 2400x2800 viewBox (official path).
_OUTER = [(500, 0), (0, 500), (0, 2300), (600, 2300), (600, 2800),
          (1100, 2300), (1500, 2300), (2400, 1400), (2400, 0)]
_SCREEN = [(2200, 1300), (1800, 1700), (1400, 1700), (1050, 2050),
           (1050, 1700), (600, 1700), (600, 200), (2200, 200)]
_BAR_L = [(1150, 550), (1350, 550), (1350, 1150), (1150, 1150)]
_BAR_R = [(1700, 550), (1900, 550), (1900, 1150), (1700, 1150)]


def _glyph(height: int) -> Image.Image:
    """Render the purple Twitch glyph at the given pixel height (transparent background)."""
    s = height / 2800.0
    w = round(2400 * s)
    sc = lambda pts: [(round(x * s), round(y * s)) for x, y in pts]
    # mask: outer shape minus the screen, plus the two eye bars (the screen border + bars)
    mask = Image.new("L", (w, height), 0)
    md = ImageDraw.Draw(mask)
    md.polygon(sc(_OUTER), fill=255)
    md.polygon(sc(_SCREEN), fill=0)     # cut the screen out -> leaves the purple border
    md.polygon(sc(_BAR_L), fill=255)    # re-add the two bars inside the screen
    md.polygon(sc(_BAR_R), fill=255)
    glyph = Image.new("RGBA", (w, height), (0, 0, 0, 0))
    glyph.paste(Image.new("RGBA", (w, height), PURPLE), (0, 0), mask)
    return glyph


def _font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("impact.ttf", "ariblk.ttf", "arialbd.ttf"):
        p = WIN_FONTS / name
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def make(nickname: str = "pareek_", height: int = 220, out: Path | None = None) -> Path:
    out = out or (ROOT / "assets" / "watermark.png")
    out.parent.mkdir(parents=True, exist_ok=True)

    glyph = _glyph(height)
    font = _font(int(height * 0.78))
    # measure text
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bbox = tmp.textbbox((0, 0), nickname, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    gap = round(height * 0.18)
    W = glyph.width + gap + tw
    H = max(height, th)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    canvas.alpha_composite(glyph, (0, (H - height) // 2))
    draw = ImageDraw.Draw(canvas)
    tx = glyph.width + gap - bbox[0]
    ty = (H - th) // 2 - bbox[1]
    # subtle dark outline for legibility over any footage, then white fill
    draw.text((tx, ty), nickname, font=font, fill=WHITE,
              stroke_width=max(2, height // 50), stroke_fill=(0, 0, 0, 255))
    canvas.save(out)
    return out


if __name__ == "__main__":
    nick = sys.argv[1] if len(sys.argv) > 1 else "pareek_"
    path = make(nick)
    print(f"wrote {path} ({Image.open(path).size[0]}x{Image.open(path).size[1]})")
