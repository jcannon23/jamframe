"""Turn an album cover into a muted, matted 4K picture for the TV's art mode.

Usage: python treat.py cover.jpg out.jpg
"""
import io
import sys

from PIL import Image, ImageEnhance, ImageFilter, ImageStat

W, H = 3840, 2160
PAPER = (232, 226, 215)  # warm off-white mat
COVER = 1340             # cover edge in px, 62% of the screen height


def _mix(img, color, amount):
    return Image.blend(img, Image.new("RGB", img.size, color), amount)


def treat(cover):
    """PIL image in, 3840x2160 PIL image out."""
    cover = cover.convert("RGB").resize((COVER, COVER), Image.LANCZOS)
    avg = tuple(int(v) for v in ImageStat.Stat(cover.resize((32, 32))).mean)

    # The cover should read as a print, not a screen: less colour and contrast,
    # blacks lifted towards grey, a slight warm cast.
    cover = ImageEnhance.Color(cover).enhance(0.55)
    cover = ImageEnhance.Contrast(cover).enhance(0.82)
    cover = _mix(cover, (128, 120, 108), 0.08)
    cover = _mix(cover, (255, 236, 205), 0.06)

    # Mat: paper with a hint of the cover's own colour.
    mat = tuple(int(p * 0.88 + a * 0.12) for p, a in zip(PAPER, avg))
    canvas = Image.new("RGB", (W, H), mat)
    x, y = (W - COVER) // 2, (H - COVER) // 2

    # Soft shadow so the cover sits in the mat instead of floating on it.
    shadow = Image.new("L", (W, H), 0)
    shadow.paste(90, (x - 10, y - 6, x + COVER + 10, y + COVER + 18))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    canvas = Image.composite(Image.new("RGB", (W, H), (40, 36, 30)), canvas, shadow)
    canvas.paste(cover, (x, y))

    # Paper grain over mat and cover alike.
    grain = Image.effect_noise((W // 2, H // 2), 14).resize((W, H), Image.BILINEAR)
    return Image.blend(canvas, grain.convert("RGB"), 0.05)


def treat_bytes(data):
    """Cover file bytes in, JPEG bytes out."""
    out = io.BytesIO()
    treat(Image.open(io.BytesIO(data))).save(out, "JPEG", quality=90)
    return out.getvalue()


if __name__ == "__main__":
    treat(Image.open(sys.argv[1])).save(sys.argv[2], quality=90)
