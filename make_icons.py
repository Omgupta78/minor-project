"""
make_icons.py - draw the app icons.

An installed app is judged by its icon before anything else, and a home screen
full of squares needs one that reads at 48 px. Generating them from code rather
than committing a binary nobody can edit means the colour can follow the app's
own palette, and a change is a one-line edit and a re-run rather than a trip
through an image editor.

    python make_icons.py

Writes into static/icons/. Run it again after changing BRAND.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / "static" / "icons"

BRAND = (36, 99, 235)        # the primary blue used throughout the app
BRAND_DEEP = (22, 79, 212)
WHITE = (255, 255, 255)

# Every size a phone, a browser tab or an app store asks for.
SIZES = {
    "icon-192.png": 192,
    "icon-512.png": 512,
    "apple-touch-icon.png": 180,
    "favicon-32.png": 32,
}
# Android may crop an icon to a circle or a squircle. A maskable icon keeps
# everything important inside the middle 80%, so no corner of the artwork is
# ever sliced off.
MASKABLE = {"icon-192-maskable.png": 192, "icon-512-maskable.png": 512}


def _gradient(size: int) -> Image.Image:
    """A vertical brand gradient, drawn a row at a time."""
    image = Image.new("RGB", (size, size), BRAND)
    draw = ImageDraw.Draw(image)
    for y in range(size):
        t = y / max(1, size - 1)
        draw.line(
            [(0, y), (size, y)],
            fill=tuple(
                int(a + (b - a) * t) for a, b in zip(BRAND, BRAND_DEEP)
            ),
        )
    return image


def draw_icon(size: int, *, maskable: bool = False) -> Image.Image:
    """A face inside scanner brackets: what the app does, in one glyph."""
    # Drawn at 4x and shrunk, which is the cheapest way to get clean edges
    # without pulling in a vector library.
    scale = 4
    box = size * scale
    canvas = Image.new("RGBA", (box, box), (0, 0, 0, 0))

    radius = int(box * (0.5 if maskable else 0.235))
    mask = Image.new("L", (box, box), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, box - 1, box - 1], radius, fill=255)
    canvas.paste(_gradient(box), (0, 0), mask)

    draw = ImageDraw.Draw(canvas)
    # A maskable icon has to survive a circular crop, so its artwork is smaller.
    inset = box * (0.30 if maskable else 0.22)
    left, top, right, bottom = inset, inset, box - inset, box - inset
    width = max(2, int(box * 0.032))
    arm = (right - left) * 0.30

    for x, y, dx, dy in (
        (left, top, 1, 1), (right, top, -1, 1),
        (left, bottom, 1, -1), (right, bottom, -1, -1),
    ):
        draw.line([(x, y), (x + arm * dx, y)], fill=WHITE, width=width)
        draw.line([(x, y), (x, y + arm * dy)], fill=WHITE, width=width)

    # head
    span = right - left
    head_r = span * 0.155
    cx, cy = box / 2, top + span * 0.40
    draw.ellipse([cx - head_r, cy - head_r, cx + head_r, cy + head_r],
                 outline=WHITE, width=width)
    # shoulders
    shoulder_w, shoulder_h = span * 0.44, span * 0.30
    draw.arc(
        [cx - shoulder_w / 2, cy + head_r * 0.45,
         cx + shoulder_w / 2, cy + head_r * 0.45 + shoulder_h * 2],
        start=200, end=340, fill=WHITE, width=width,
    )
    return canvas.resize((size, size), Image.LANCZOS)


# Android launcher icons. An adaptive icon is two layers: the system draws its
# own shape (circle, squircle, teardrop -- the manufacturer decides) over a
# background, and puts the foreground on top. The foreground canvas is 108dp
# but only the middle 72dp is guaranteed visible, so the glyph is drawn at two
# thirds and the rest is breathing room the system may crop.
ANDROID_DENSITIES = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}


def draw_foreground(size: int) -> Image.Image:
    """The white glyph alone, transparent behind it, filling the safe zone.

    Drawn across the whole canvas, not shrunk into it. The standard artwork
    already sits inside the middle 56% (draw_icon insets by 22% a side), which
    is comfortably within the 66% the system guarantees not to crop -- so
    scaling it down again would only make a small icon smaller, which is what
    a first attempt here did.

    The background is removed by whiteness rather than by a colour match, so
    the antialiased edges of the glyph keep their partial transparency instead
    of turning into a jagged cut-out.
    """
    import numpy as np

    art = np.asarray(draw_icon(size).convert("RGB"), dtype=np.float32)
    # White has a high minimum channel; the blue background's is low (36).
    whiteness = art.min(axis=2)
    alpha = np.clip((whiteness - 120.0) / (255.0 - 120.0), 0.0, 1.0) * 255.0
    out = np.zeros((size, size, 4), dtype=np.uint8)
    out[:, :, :3] = 255
    out[:, :, 3] = alpha.astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def write_android(res: Path) -> list[str]:
    written = []
    for density, factor in ANDROID_DENSITIES.items():
        folder = res / f"mipmap-{density}"
        folder.mkdir(parents=True, exist_ok=True)
        legacy = int(48 * factor)
        draw_icon(legacy).save(folder / "ic_launcher.png", "PNG")
        draw_icon(legacy).save(folder / "ic_launcher_round.png", "PNG")
        adaptive = int(108 * factor)
        draw_foreground(adaptive).save(folder / "ic_launcher_foreground.png", "PNG")
        written.append(f"mipmap-{density}: {legacy}px launcher, {adaptive}px foreground")
    return written


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    written = []
    for name, size in SIZES.items():
        icon = draw_icon(size)
        icon.save(OUT / name, "PNG")
        written.append(f"{name} ({size}px)")
    for name, size in MASKABLE.items():
        draw_icon(size, maskable=True).save(OUT / name, "PNG")
        written.append(f"{name} ({size}px, maskable)")

    # The .ico keeps old browsers and Windows shortcuts happy.
    draw_icon(64).save(OUT / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    written.append("favicon.ico")

    print(f"wrote {len(written)} icons to {OUT}:")
    for line in written:
        print("  " + line)

    # The Android project, when it is checked out alongside.
    res = Path(__file__).resolve().parent / "android" / "app" / "src" / "main" / "res"
    if res.exists():
        print(f"\nandroid launcher icons in {res}:")
        for line in write_android(res):
            print("  " + line)


if __name__ == "__main__":
    main()
