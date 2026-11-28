"""Turn an album cover into a muted, matted 4K picture for the TV's art mode.

The still for TVs that take pictures rather than the animated page. It follows the same look settings as the
page (display.look): fading, mat, cover size, grain, the caption, and the real-size scale for the TV it is
going to.

Usage: python treat.py cover.jpg out.jpg
"""
import io
import sys

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageStat

W, H = 3840, 2160
MATS = {"paper": (232, 226, 215), "white": (240, 239, 235), "charcoal": (46, 44, 41)}     # as in display/index.html
LOOK = {"mute": 0.5, "mat": "paper", "cover": 0.62, "grain": True, "scale": 1,
        "caption": True, "align": "center", "fields": ["title", "artist", "album"], "size": "medium"}
SIZES = {"small": 0.8, "medium": 1, "large": 1.3}
# The page's caption face, then what other computers have: (file, index of the upright face, of the italic).
FONTS = [("/System/Library/Fonts/Supplemental/Iowan Old Style.ttc", 0, 2), ("/System/Library/Fonts/Palatino.ttc", 0, 1),
         ("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", 0, None), ("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf", None, 0)]


def _font(px, italic=False):
    for path, upright, slanted in FONTS:
        index = slanted if italic else upright
        if index is not None:
            try:
                return ImageFont.truetype(path, px, index=index)
            except OSError:
                pass
    return ImageFont.load_default(px)       # no serif on this computer: Pillow's own


def _line(draw, text, font, width):
    """text, cut short with an ellipsis if it is wider than the cover."""
    while text and draw.textlength(text, font=font) > width:
        text = text[:-2].rstrip() + "\u2026"
    return text


def _mix(img, color, amount):
    return Image.blend(img, Image.new("RGB", img.size, color), amount)


def treat(cover, look=None, caption=None):
    """PIL image in, 3840x2160 PIL image out. look: any of LOOK's settings; the rest take its values.
    caption: {"title", "artist", "album"} of the song, printed under the cover as the page does."""
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

    # The caption, like a gallery label: the song, then artist and album in italics. Sizes as on the page.
    words = {k: (caption or {}).get(k) or "" for k in ("title", "artist", "album") if k in look["fields"]}
    if look["caption"] and any(words.values()):
        unit = H / 100 * look["scale"] * SIZES.get(look["size"], 1)
        dark = mat[0] * 0.3 + mat[1] * 0.59 + mat[2] * 0.11 < 110
        ink = (236, 230, 220) if dark else (60, 54, 46)
        draw, top = ImageDraw.Draw(canvas, "RGBA"), y + edge + H / 100 * look["scale"] * 2.2
        lines = [(words.get("title", ""), _font(round(unit * 2.3)), 200),
                 (" \u2014 ".join(w for w in (words.get("artist"), words.get("album")) if w), _font(round(unit * 1.6), italic=True), 160)]
        for text, font, alpha in lines:
            text = _line(draw, text, font, edge)
            if text:
                at = x if look["align"] == "left" else x + (edge - draw.textlength(text, font=font)) / 2
                draw.text((at, top), text, font=font, fill=ink + (alpha,))
                top += font.size * 1.45
    if not look["grain"]:
        return canvas

    # Paper grain over mat and cover alike.
    grain = Image.effect_noise((W // 2, H // 2), 14).resize((W, H), Image.BILINEAR)
    return Image.blend(canvas, grain.convert("RGB"), 0.05)


def treat_bytes(data, look=None, caption=None):
    """Cover file bytes in, JPEG bytes out."""
    out = io.BytesIO()
    treat(Image.open(io.BytesIO(data)), look, caption).save(out, "JPEG", quality=90)
    return out.getvalue()


if __name__ == "__main__":
    treat(Image.open(sys.argv[1])).save(sys.argv[2], quality=90)
