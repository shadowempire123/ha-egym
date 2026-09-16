#!/usr/bin/env python3
"""Draw the brand images that Home Assistant serves for this integration.

Deliberately a self-made mark rather than eGym's logo. The brands repository no
longer takes icons for custom integrations, so the files ship here instead --
and shipping somebody else's trademark in a repository is a different question
from naming their product in the README. A dumbbell says what the integration
is about and belongs to nobody.

Regenerate with: python3 scripts/make_brand_images.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "custom_components" / "egym" / "brand"
# Drawn at 4x and scaled down: PIL has no anti-aliasing of its own, so this is
# what keeps the rounded corners from looking chewed.
SCALE = 4
BASE = 256
BACKGROUND = (17, 94, 89, 255)
FOREGROUND = (255, 255, 255, 255)


def draw_mark(size: int) -> Image.Image:
    canvas = size * SCALE
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    unit = canvas / 1024

    def box(x0: float, y0: float, x1: float, y1: float, radius: float, fill) -> None:
        draw.rounded_rectangle(
            [x0 * unit, y0 * unit, x1 * unit, y1 * unit], radius=radius * unit, fill=fill
        )

    box(0, 0, 1024, 1024, 220, BACKGROUND)
    # Bar, then the inner and outer plates of a dumbbell, mirrored either side.
    box(300, 470, 724, 554, 38, FOREGROUND)
    for left, right in ((232, 304), (720, 792)):
        box(left, 408, right, 616, 30, FOREGROUND)
    for left, right in ((160, 220), (804, 864)):
        box(left, 444, right, 580, 24, FOREGROUND)
    return image.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, size in (("icon.png", BASE), ("icon@2x.png", BASE * 2)):
        draw_mark(size).save(OUT / name)
    # The mark is square, so the logo is the same image. Home Assistant allows
    # that, and inventing a wordmark without a font on this machine would only
    # produce something worse.
    for icon, logo in (("icon.png", "logo.png"), ("icon@2x.png", "logo@2x.png")):
        (OUT / logo).write_bytes((OUT / icon).read_bytes())
    for path in sorted(OUT.iterdir()):
        with Image.open(path) as image:
            print(f"{path.name}: {image.size[0]}x{image.size[1]}")


if __name__ == "__main__":
    main()
