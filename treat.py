"""Turn an album cover into a muted, matted 4K picture for the TV's art mode.

The still for TVs that take pictures rather than the animated page. It follows the same look settings as the
page (display.look): fading, mat, cover size, grain, and the real-size scale for the TV it is going to.

Usage: python treat.py cover.jpg out.jpg
"""
import io
import sys

from PIL import Image, ImageEnhance, ImageFilter, ImageStat

W, H = 3840, 2160
MATS = {"paper": (232, 226, 215), "white": (240, 239, 235), "charcoal": (46, 44, 41)}     # as in display/index.html
LOOK = {"mute": 0.5, "mat": "paper", "cover": 0.62, "grain": True, "scale": 1}


def _mix(img, color, amount):
    return Image.blend(img, Image.new("RGB", img.size, color), amount)


def treat(cover, look=None):
    """PIL image in, 3840x2160 PIL image out. look: any of LOOK's settings; the rest take its values."""
    look = {**LOOK, **(look or {})}
    edge = round(H * min(look["cover"] * look["scale"], 0.84))
    cover = cover.convert("RGB").resize((edge, edge), Image.LANCZOS)

    # The cover should read as a print, not a screen: less colour and contrast,
    # blacks lifted towards grey, a slight warm cast.
    m = look["mute"]
    cover = ImageEnhance.Color(cover).enhance(1 - 0.9 * m)
    cover = ImageEnhance.Contrast(cover).enhance(1 - 0.36 * m)
    cover = _mix(cover, (128, 120, 108), 0.16 * m)
    cover = _mix(cover, (255, 236, 205), 0.12 * m)
    avg = tuple(int(v) for v in ImageStat.Stat(cover.resize((32, 32))).mean)

    # Mat: its own colour with a hint of the cover's, or mostly the cover's.
    base, tint = (MATS["paper"], 0.55) if look["mat"] == "cover" else (MATS.get(look["mat"], MATS["paper"]), 0.12)
    mat = tuple(int(p * (1 - tint) + a * tint) for p, a in zip(base, avg))
    canvas = Image.new("RGB", (W, H), mat)
    x, y = (W - edge) // 2, (H - edge) // 2

    # Soft shadow so the cover sits in the mat instead of floating on it.
    shadow = Image.new("L", (W, H), 0)
    shadow.paste(90, (x - 10, y - 6, x + edge + 10, y + edge + 18))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    canvas = Image.composite(Image.new("RGB", (W, H), (40, 36, 30)), canvas, shadow)
    canvas.paste(cover, (x, y))
    if not look["grain"]:
        return canvas

    # Paper grain over mat and cover alike.
    grain = Image.effect_noise((W // 2, H // 2), 14).resize((W, H), Image.BILINEAR)
    return Image.blend(canvas, grain.convert("RGB"), 0.05)


def treat_bytes(data, look=None):
    """Cover file bytes in, JPEG bytes out."""
    out = io.BytesIO()
    treat(Image.open(io.BytesIO(data)), look).save(out, "JPEG", quality=90)
    return out.getvalue()


if __name__ == "__main__":
    treat(Image.open(sys.argv[1])).save(sys.argv[2], quality=90)
