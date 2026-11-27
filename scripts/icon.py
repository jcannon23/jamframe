"""Draws the JamFrame app icon: a framed print of a record sleeve, record half out. Usage: python scripts/icon.py
Writes mac/JamFrame.icns (and mac/icon.png, the 1024 px master)."""
import os
import subprocess
import tempfile

from PIL import Image, ImageChops, ImageDraw, ImageFilter

N = 2048   # drawn at twice the size, scaled down for smooth edges
HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mac")


def gradient(size, top, bottom):
    ramp = Image.linear_gradient("L").resize(size)
    return Image.composite(Image.new("RGB", size, bottom), Image.new("RGB", size, top), ramp)


def shadow(shape_mask, blur, offset, strength):
    """A soft dark layer in the shape of a mask, to lay under it."""
    s = Image.new("L", (N, N), 0)
    s.paste(shape_mask.point(lambda v: int(v * strength)), offset)
    return s.filter(ImageFilter.GaussianBlur(blur))


def mask(draw_shape):
    m = Image.new("L", (N, N), 0)
    draw_shape(ImageDraw.Draw(m))
    return m


icon = Image.new("RGBA", (N, N), (0, 0, 0, 0))

# the frame: a dark rounded square, on Apple's icon grid (824 of 1024, centred)
frame = mask(lambda d: d.rounded_rectangle((200, 200, 1848, 1848), 370, fill=255))
icon.paste((0, 0, 0), (0, 0), shadow(frame, 36, (0, 24), 0.45))
icon.paste(gradient((N, N), (58, 53, 48), (30, 28, 26)), (0, 0), frame)

# the mat: warm paper inside the frame
mat = mask(lambda d: d.rounded_rectangle((290, 290, 1758, 1758), 290, fill=255))
icon.paste(gradient((N, N), (238, 233, 223), (222, 215, 202)), (0, 0), mat)
inner = shadow(ImageChops.invert(mat), 30, (0, 18), 0.5)      # the frame's shadow falling on the mat
icon.paste((40, 34, 28), (0, 0), ImageChops.multiply(inner, mat))

# the record, half out of the sleeve to the right
cx, cy, r = 1210, 1024, 400
disc = mask(lambda d: d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255))
icon.paste((40, 34, 28), (0, 0), ImageChops.multiply(shadow(disc, 26, (10, 22), 0.5), mat))
icon.paste(gradient((N, N), (52, 48, 45), (26, 24, 23)), (0, 0), disc)
d = ImageDraw.Draw(icon)
for groove in range(190, r - 20, 34):
    d.ellipse((cx - groove, cy - groove, cx + groove, cy + groove), outline=(70, 65, 60), width=4)
d.ellipse((cx - 150, cy - 150, cx + 150, cy + 150), fill=(196, 122, 84))      # label
d.ellipse((cx - 150, cy - 150, cx + 150, cy + 150), outline=(160, 96, 66), width=8)
d.ellipse((cx - 26, cy - 26, cx + 26, cy + 26), fill=(232, 226, 215))         # spindle hole

# the sleeve: a muted sunset, like a faded print
x0, y0, s = 560, 644, 760
sleeve = mask(lambda d: d.rectangle((x0, y0, x0 + s, y0 + s), fill=255))
icon.paste((40, 34, 28), (0, 0), ImageChops.multiply(shadow(sleeve, 28, (12, 24), 0.55), mat))
art = gradient((s, s), (214, 160, 120), (96, 108, 112))
a = ImageDraw.Draw(art)
a.ellipse((s * 0.5 - 150, s * 0.50 - 150, s * 0.5 + 150, s * 0.50 + 150), fill=(238, 208, 160))   # sun
a.polygon([(0, s * 0.70), (s * 0.30, s * 0.52), (s * 0.55, s * 0.66), (s * 0.80, s * 0.48), (s, s * 0.62), (s, s), (0, s)],
          fill=(74, 82, 88))                                                                     # far hills
a.polygon([(0, s * 0.84), (s * 0.35, s * 0.70), (s * 0.70, s * 0.82), (s, s * 0.74), (s, s), (0, s)], fill=(52, 58, 64))
icon.paste(art, (x0, y0))

# paper grain over everything inside the frame
grain = Image.effect_noise((N, N), 26).convert("RGB")
icon.paste(Image.blend(icon.convert("RGB"), grain, 0.05), (0, 0), frame)

os.makedirs(HERE, exist_ok=True)
master = icon.resize((1024, 1024), Image.LANCZOS)
master.save(os.path.join(HERE, "icon.png"))
with tempfile.TemporaryDirectory() as tmp:
    iconset = os.path.join(tmp, "JamFrame.iconset")
    os.mkdir(iconset)
    for size in (16, 32, 128, 256, 512):
        master.resize((size, size), Image.LANCZOS).save(os.path.join(iconset, "icon_%dx%d.png" % (size, size)))
        master.resize((size * 2, size * 2), Image.LANCZOS).save(os.path.join(iconset, "icon_%dx%d@2x.png" % (size, size)))
    subprocess.run(["iconutil", "-c", "icns", iconset, "-o", os.path.join(HERE, "JamFrame.icns")], check=True)
print("wrote mac/JamFrame.icns")
