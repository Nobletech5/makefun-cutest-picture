#!/usr/bin/env python3
"""Cutest picture v2: a cream kitten hugging a tiny yellow chick.

The program draws the picture itself (no bundled image, no network, no
third-party libraries) and writes it deterministically to
$MAKEFUN_OUTPUT_DIR/entry.png (default /output/entry.png).

The pair fills the frame so it reads clearly at ~300px: a big cream kitten
with a gentle head tilt, big bright blue eyes and a small mint scarf, its
clumsy paws wrapped around a tiny yellow chick with big blue eyes, a tiny
orange beak and a feather tuft. Soft blush on both, calm uncluttered
background.

Technique: a small scanline rasteriser draws filled ellipses, polygons and
thick lines into a 2x supersampled framebuffer, which is then box-downsampled
to 512x512 for smooth edges. The PNG is encoded by hand with zlib+struct.
"""

import math
import os
import struct
import zlib

W = H = 512
SS = 2  # supersampling factor
SW, SH = W * SS, H * SS

# Framebuffer: RGB bytes at supersampled resolution.
buf = bytearray(SW * SH * 3)


def _blend(x, y, r, g, b, a):
    """Blend one supersampled pixel. a is 0..255."""
    if a <= 0 or x < 0 or y < 0 or x >= SW or y >= SH:
        return
    i = (y * SW + x) * 3
    if a >= 255:
        buf[i] = r
        buf[i + 1] = g
        buf[i + 2] = b
    else:
        buf[i] = (r * a + buf[i] * (255 - a)) // 255
        buf[i + 1] = (g * a + buf[i + 1] * (255 - a)) // 255
        buf[i + 2] = (b * a + buf[i + 2] * (255 - a)) // 255


def _span(x0, x1, y, r, g, b, a):
    """Fill a horizontal run of supersampled pixels (inclusive)."""
    if y < 0 or y >= SH or x1 < 0 or x0 >= SW:
        return
    x0 = max(0, x0)
    x1 = min(SW - 1, x1)
    if x0 > x1:
        return
    i0 = (y * SW + x0) * 3
    i1 = (y * SW + x1 + 1) * 3
    if a >= 255:
        buf[i0:i1] = bytes((r, g, b)) * (x1 - x0 + 1)
    else:
        for x in range(x0, x1 + 1):
            _blend(x, y, r, g, b, a)


def fill_ellipse(cx, cy, rx, ry, color, alpha=255):
    """Filled ellipse, logical (512-space) coordinates."""
    cx, cy, rx, ry = cx * SS, cy * SS, rx * SS, ry * SS
    r, g, b = color
    y0 = max(0, int(math.ceil(cy - ry)))
    y1 = min(SH - 1, int(math.floor(cy + ry)))
    for y in range(y0, y1 + 1):
        dy = (y + 0.5 - cy) / ry
        t = 1.0 - dy * dy
        if t <= 0:
            continue
        dx = rx * math.sqrt(t)
        _span(int(math.ceil(cx - dx)), int(math.floor(cx + dx)), y, r, g, b, alpha)


def fill_circle(cx, cy, rad, color, alpha=255):
    fill_ellipse(cx, cy, rad, rad, color, alpha)


def fill_poly(points, color, alpha=255):
    """Filled polygon, logical coordinates. Points: list of (x, y)."""
    pts = [(x * SS, y * SS) for x, y in points]
    r, g, b = color
    ys = [p[1] for p in pts]
    y0 = max(0, int(math.ceil(min(ys))))
    y1 = min(SH - 1, int(math.floor(max(ys))))
    n = len(pts)
    for y in range(y0, y1 + 1):
        yc = y + 0.5
        xs = []
        for i in range(n):
            x1, y1p = pts[i]
            x2, y2p = pts[(i + 1) % n]
            if (y1p <= yc < y2p) or (y2p <= yc < y1p):
                xs.append(x1 + (yc - y1p) * (x2 - x1) / (y2p - y1p))
        if len(xs) < 2:
            continue
        xs.sort()
        for k in range(0, len(xs) - 1, 2):
            _span(int(math.ceil(xs[k])), int(math.floor(xs[k + 1])), y, r, g, b, alpha)


def _stamp(cx, cy, rad, r, g, b, alpha):
    fill_ellipse(cx / SS, cy / SS, rad / SS, rad / SS, (r, g, b), alpha)


def thick_line(x0, y0, x1, y1, color, width, alpha=255):
    """A line drawn as a chain of small discs (round caps, smooth)."""
    x0, y0, x1, y1 = x0 * SS, y0 * SS, x1 * SS, y1 * SS
    r, g, b = color
    rad = width * SS / 2.0
    dist = math.hypot(x1 - x0, y1 - y0)
    steps = max(1, int(dist / max(1.0, rad * 0.6)) + 1)
    for i in range(steps + 1):
        t = i / steps
        _stamp(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, rad, r, g, b, alpha)


def arc(cx, cy, rad, a0, a1, color, width, alpha=255):
    """An arc (angles in degrees, 0 = east, increasing clockwise in screen space)."""
    r, g, b = color
    steps = max(4, int(abs(a1 - a0) / 6) + 1)
    prev = None
    for i in range(steps + 1):
        a = math.radians(a0 + (a1 - a0) * i / steps)
        px = cx + rad * math.cos(a)
        py = cy + rad * math.sin(a)
        if prev is not None:
            thick_line(prev[0], prev[1], px, py, color, width, alpha)
        prev = (px, py)


def heart(cx, cy, s, color, alpha=255):
    """A small heart centred near (cx, cy), size s."""
    fill_circle(cx - s * 0.38, cy - s * 0.18, s * 0.40, color, alpha)
    fill_circle(cx + s * 0.38, cy - s * 0.18, s * 0.40, color, alpha)
    fill_poly(
        [(cx - s * 0.72, cy - s * 0.05), (cx + s * 0.72, cy - s * 0.05),
         (cx, cy + s * 0.85)],
        color, alpha,
    )


def _lcg(seed):
    x = seed
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x


def draw_background():
    # Vertical gradient: soft periwinkle at the top, warm cream at the bottom.
    top = (233, 239, 253)
    bottom = (255, 247, 233)
    for y in range(SH):
        t = y / (SH - 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        i0 = y * SW * 3
        buf[i0:(y + 1) * SW * 3] = bytes((r, g, b)) * SW
    # A few faint white dots, fixed positions from a seeded generator.
    rng = _lcg(20261113)
    for _ in range(12):
        x = 24 + next(rng) % 464
        y = 24 + next(rng) % 464
        rad = 4 + next(rng) % 7
        fill_circle(x, y, rad, (255, 255, 255), 60)


def draw_kitten():
    cream = (255, 244, 227)
    outline = (232, 180, 140)
    pink = (242, 125, 150)
    dark = (67, 48, 43)
    blush = (255, 159, 178)
    whisker = (217, 160, 107)
    mouth_c = (178, 106, 90)
    blue = (70, 160, 225)
    mint = (168, 220, 190)
    mint_d = (140, 198, 166)

    # Soft ground shadow.
    fill_ellipse(256, 468, 150, 12, (228, 200, 192), 80)

    # Ears (behind the head so the head overlaps their bases).
    # Left ear sits a little higher than the right: the gentle head tilt.
    fill_poly([(126, 192), (168, 80), (222, 168)], outline)
    fill_poly([(398, 198), (360, 92), (312, 172)], outline)
    fill_poly([(144, 174), (170, 106), (204, 162)], pink)
    fill_poly([(382, 180), (358, 116), (326, 168)], pink)

    # Head: warm outline, then the cream face.
    fill_circle(252, 262, 158, outline)
    fill_circle(252, 262, 150, cream)

    # Big bright blue eyes: dark outline, blue iris, dark pupil, white
    # highlights. The right eye sits a touch lower, part of the head tilt.
    for ex, ey in ((196, 250), (316, 256)):
        fill_ellipse(ex, ey, 34, 44, dark)
        fill_ellipse(ex, ey + 2, 25, 33, blue)
        fill_ellipse(ex, ey + 2, 13, 19, dark)
        fill_circle(ex - 10, ey - 14, 11, (255, 255, 255))
        fill_circle(ex + 11, ey + 13, 5, (255, 255, 255))
        # Two tiny lash flicks on the outer top edge.
        thick_line(ex - 28, ey - 34, ex - 38, ey - 46, dark, 3)
        thick_line(ex - 20, ey - 40, ex - 28, ey - 54, dark, 3)

    # Blush cheeks.
    fill_ellipse(148, 336, 26, 14, blush, 140)
    fill_ellipse(358, 340, 26, 14, blush, 140)

    # Tiny pink nose and a little "w" mouth.
    fill_poly([(236, 314), (268, 314), (252, 332)], pink)
    fill_circle(252, 328, 7, pink)
    arc(238, 334, 13, 15, 165, mouth_c, 3)
    arc(266, 334, 13, 15, 165, mouth_c, 3)

    # Whiskers.
    for sx in (-1, 1):
        thick_line(252 + sx * 104, 300, 252 + sx * 158, 288, whisker, 2.5, 180)
        thick_line(252 + sx * 106, 322, 252 + sx * 158, 326, whisker, 2.5, 180)
        thick_line(252 + sx * 104, 344, 252 + sx * 154, 362, whisker, 2.5, 180)

    # Small mint scarf around the neck: band, knot on the left, two short
    # tails splayed outward so they read as scarf tails, not legs.
    thick_line(150, 408, 354, 408, mint, 26)
    fill_circle(185, 412, 14, mint_d)
    thick_line(178, 420, 160, 442, mint, 15)
    thick_line(194, 420, 210, 440, mint, 15)


def draw_chick():
    yellow = (255, 214, 90)
    yellow_d = (244, 196, 72)
    orange = (255, 150, 60)
    dark = (67, 48, 43)
    blue = (90, 175, 235)
    blush = (255, 159, 178)

    # Round chubby body, tucked against the kitten's cheek.
    fill_ellipse(345, 385, 52, 58, yellow_d)
    fill_ellipse(345, 385, 48, 54, yellow)

    # Feather tuft on top.
    thick_line(345, 332, 335, 312, yellow_d, 4)
    thick_line(345, 330, 345, 308, yellow_d, 4)
    thick_line(345, 332, 355, 312, yellow_d, 4)

    # Little wing on the chick's left side.
    fill_ellipse(308, 408, 12, 20, yellow_d)

    # Big bright blue eyes.
    for ex in (326, 362):
        fill_ellipse(ex, 370, 11, 13, dark)
        fill_ellipse(ex, 371, 8, 10, blue)
        fill_ellipse(ex, 371, 4, 5, dark)
        fill_circle(ex - 3, 366, 3, (255, 255, 255))

    # Tiny orange beak.
    fill_poly([(330, 388), (356, 388), (343, 404)], orange)
    fill_poly([(334, 396), (352, 396), (343, 406)], (230, 120, 45))

    # Blush on the chick's cheek.
    fill_ellipse(318, 398, 10, 6, blush, 160)

    # Tiny orange feet peeking out below the body.
    fill_ellipse(332, 446, 9, 5, orange)
    fill_ellipse(360, 446, 9, 5, orange)


def draw_paws():
    cream = (255, 244, 227)
    outline = (232, 180, 140)

    # The kitten's clumsy paws wrapped around the chick, in front of it.
    # Toe lines slant inward, toward the chick, so the paws read as
    # gripping it rather than sitting beside it.
    for px, s in ((296, 1), (394, -1)):
        fill_ellipse(px, 422, 34, 20, outline)
        fill_ellipse(px, 420, 30, 17, cream)
        thick_line(px - 12 * s, 408, px - 8 * s, 428, outline, 2)
        thick_line(px + 8 * s, 408, px + 12 * s, 428, outline, 2)


def draw_hearts():
    heart(76, 92, 16, (255, 143, 171), 180)
    heart(436, 78, 20, (255, 143, 171), 180)


def downsample():
    """Box-average the 2x framebuffer down to 512x512 RGB bytes."""
    out = bytearray(W * H * 3)
    for y in range(H):
        for x in range(W):
            r = g = b = 0
            for dy in (0, 1):
                base = ((y * SS + dy) * SW + x * SS) * 3
                for dx in (0, 1):
                    i = base + dx * 3
                    r += buf[i]
                    g += buf[i + 1]
                    b += buf[i + 2]
            o = (y * W + x) * 3
            out[o] = (r + 2) // 4
            out[o + 1] = (g + 2) // 4
            out[o + 2] = (b + 2) // 4
    return bytes(out)


def png_bytes(rgb, w, h):
    raw = b"".join(b"\x00" + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def main():
    draw_background()
    draw_kitten()
    draw_chick()
    draw_paws()
    draw_hearts()
    rgb = downsample()
    data = png_bytes(rgb, W, H)
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "entry.png"), "wb") as f:
        f.write(data)


if __name__ == "__main__":
    main()
