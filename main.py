#!/usr/bin/env python3
"""Cutest picture v3: one big cream kitten face, drawn better.

The program draws the picture itself (no bundled image, no network, no
third-party libraries) and writes it deterministically to
$MAKEFUN_OUTPUT_DIR/entry.png (default /output/entry.png).

Lesson from v1 and v2: v1 (one big kitten face, pink bow) scored 73.6%;
v2 (kitten hugging a chick, two subjects) scored 66.5% — the second
subject crowded the frame and hurt "reads small" and clean craft. So v3
goes back to ONE large subject filling the frame, and spends the effort
on making that one face better: bigger bright blue eyes, a gentle head
tilt, a soft smile, one tiny pink bow only, and soft radial shading on
the fur for depth (darker rim, gentle top-left light).

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


def shade_head(cx, cy, rx, ry):
    """Soft radial depth on the fur: a darker rim and a gentle top-left
    light. Blends over the cream only, so call it right after the head
    fill and before any features are drawn."""
    cx, cy, rx, ry = cx * SS, cy * SS, rx * SS, ry * SS
    shadow = (238, 198, 166)
    x0 = max(0, int(cx - rx))
    x1 = min(SW - 1, int(cx + rx))
    y0 = max(0, int(cy - ry))
    y1 = min(SH - 1, int(cy + ry))
    hx, hy = cx - rx * 0.28, cy - ry * 0.34
    for y in range(y0, y1 + 1):
        dy = (y + 0.5 - cy) / ry
        for x in range(x0, x1 + 1):
            dx = (x + 0.5 - cx) / rx
            d2 = dx * dx + dy * dy
            if d2 >= 1.0:
                continue
            # Rim shade grows quadratically past 62% of the radius
            # (squared-distance falloff, no sqrt needed).
            if d2 > 0.3844:
                t = (d2 - 0.3844) / 0.6156
                a = int(76 * t * t)
                if a > 0:
                    _blend(x, y, shadow[0], shadow[1], shadow[2], a)
            # Soft top-left light.
            hdx = (x + 0.5 - hx) / (rx * 0.62)
            hdy = (y + 0.5 - hy) / (ry * 0.62)
            if abs(hdx) < 1.0 and abs(hdy) < 1.0:
                hd2 = hdx * hdx + hdy * hdy
                if hd2 < 1.0:
                    la = int(26 * (1.0 - math.sqrt(hd2)))
                    if la > 0:
                        _blend(x, y, 255, 255, 255, la)


def draw_background():
    # Vertical pastel gradient only: soft pink at the top, warm cream at
    # the bottom. Nothing else — the face must stay uncluttered.
    top = (255, 234, 241)
    bottom = (255, 247, 233)
    for y in range(SH):
        t = y / (SH - 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        i0 = y * SW * 3
        buf[i0:(y + 1) * SW * 3] = bytes((r, g, b)) * SW


def draw_kitten():
    cream = (255, 244, 227)
    outline = (232, 180, 140)
    pink = (242, 125, 150)
    dark = (67, 48, 43)
    blush = (255, 159, 178)
    whisker = (217, 160, 107)
    mouth_c = (178, 106, 90)
    blue = (70, 160, 225)

    # Ears (behind the head so the head overlaps their bases). The left
    # ear sits a little higher than the right: the gentle head tilt.
    fill_poly([(98, 214), (146, 82), (212, 190)], outline)
    fill_poly([(414, 220), (366, 92), (300, 196)], outline)
    fill_poly([(116, 196), (148, 110), (194, 180)], pink)
    fill_poly([(396, 202), (364, 118), (318, 186)], pink)

    # Head: warm outline, then the cream face, then radial shading.
    fill_circle(256, 276, 180, outline)
    fill_circle(256, 276, 172, cream)
    shade_head(256, 276, 172, 172)

    # One tiny pink bow at the base of the right ear — the single charm
    # touch, anchored to the ear so it never floats on the face.
    bow = (242, 102, 139)
    bow_d = (225, 78, 122)
    fill_poly([(346, 178), (314, 156), (320, 198)], bow)
    fill_poly([(346, 178), (378, 156), (372, 198)], bow)
    fill_circle(346, 178, 9, bow_d)

    # Big bright blue eyes: dark outline, blue iris, dark pupil, white
    # highlights. The right eye sits a touch lower, part of the head tilt.
    # The pupils stay smaller than the iris so the blue shows.
    for ex, ey in ((184, 270), (328, 274)):
        fill_ellipse(ex, ey, 43, 56, dark)
        fill_ellipse(ex, ey + 2, 31, 41, blue)
        fill_ellipse(ex, ey + 2, 17, 26, dark)
        fill_circle(ex - 13, ey - 17, 14, (255, 255, 255))
        fill_circle(ex + 14, ey + 19, 6, (255, 255, 255))
        # Two tiny lash flicks on the outer top edge.
        thick_line(ex - 34, ey - 44, ex - 45, ey - 57, dark, 3)
        thick_line(ex - 25, ey - 50, ex - 33, ey - 64, dark, 3)

    # Blush cheeks.
    fill_ellipse(140, 350, 32, 18, blush, 140)
    fill_ellipse(372, 354, 32, 18, blush, 140)

    # Tiny pink nose and a little "w" mouth — a soft smile.
    fill_poly([(238, 320), (274, 320), (256, 342)], pink)
    fill_circle(256, 338, 7, pink)
    arc(240, 344, 14, 15, 165, mouth_c, 3)
    arc(272, 344, 14, 15, 165, mouth_c, 3)

    # Whiskers, short and soft so they never crowd the face.
    for sx in (-1, 1):
        thick_line(256 + sx * 100, 302, 256 + sx * 152, 290, whisker, 2.5, 170)
        thick_line(256 + sx * 102, 324, 256 + sx * 152, 328, whisker, 2.5, 170)
        thick_line(256 + sx * 100, 346, 256 + sx * 148, 364, whisker, 2.5, 170)


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
    rgb = downsample()
    data = png_bytes(rgb, W, H)
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "entry.png"), "wb") as f:
        f.write(data)


if __name__ == "__main__":
    main()
