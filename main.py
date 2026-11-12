#!/usr/bin/env python3
"""Cutest picture v4 — one big cream kitten face, painted from scratch.

The program paints a single picture onto a 512x512 canvas and writes it as
a PNG. The subject is one large cream kitten face filling the frame: two
triangular ears (the left one a little higher, for a gentle head tilt), two
big bright blue eyes, a tiny pink nose, a small "w" mouth, soft pink blush
cheeks, thin whiskers and one small pink bow at the base of the right ear.
The background is a plain pink-to-cream gradient, so nothing crowds the
subject and it still reads clearly when shown small.

Everything is drawn with the Python standard library only. The run is fully
deterministic: no randomness, no clock, no network, so running it twice
produces byte-identical output.
"""

import math
import os
import struct
import zlib

# ---------------------------------------------------------------------------
# Canvas size and palette
# ---------------------------------------------------------------------------

SIZE = 512

BG_TOP = (250, 226, 233)      # pale pink at the top of the background
BG_BOTTOM = (253, 245, 232)   # pale cream at the bottom
FACE_CREAM = (250, 238, 211)  # main fur colour
FACE_LIGHT = (255, 248, 232)  # soft highlight on the fur
FACE_RIM = (232, 205, 170)    # faint darker tone near the fur's edge
OUTLINE = (206, 162, 118)     # warm tan outline of the face and ears
INNER_EAR = (246, 172, 186)   # pink inside the ears
EYE_RIM = (74, 48, 36)        # dark brown ring around each eye
IRIS = (72, 166, 218)         # bright blue iris
PUPIL = (48, 34, 30)          # dark pupil
HIGHLIGHT = (255, 255, 255)   # white sparkle in the eyes
NOSE = (238, 128, 148)        # pink nose
MOUTH = (90, 60, 48)          # dark brown mouth line
BLUSH = (245, 175, 190)       # pink blush
WHISKER = (198, 162, 118)     # tan whiskers
BOW = (238, 108, 144)         # pink bow
BOW_KNOT = (224, 84, 122)     # slightly deeper pink for the bow knot

FACE_CX, FACE_CY = 256, 272
FACE_R = 185


# ---------------------------------------------------------------------------
# Small numeric helpers
# ---------------------------------------------------------------------------

def clamp01(value):
    """Clamp a number into [0, 1]."""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def smoothstep(edge0, edge1, value):
    """Smooth 0 -> 1 ramp between edge0 and edge1."""
    t = clamp01((value - edge0) / (edge1 - edge0))
    return t * t * (3.0 - 2.0 * t)


def feather(signed, width):
    """Coverage of a pixel whose signed distance inside a shape is `signed`.

    Returns 1 well inside the shape, 0 well outside, and a smooth ramp
    across an edge `width` pixels wide.
    """
    return smoothstep(-width, width, signed)


# ---------------------------------------------------------------------------
# The canvas: a flat list of floats, three per pixel (r, g, b)
# ---------------------------------------------------------------------------

class Canvas:
    def __init__(self, size):
        self.size = size
        self.pix = [0.0] * (size * size * 3)

    def blend(self, x, y, colour, alpha):
        """Blend `colour` over pixel (x, y) with opacity `alpha`."""
        if alpha <= 0.0:
            return
        if x < 0 or y < 0 or x >= self.size or y >= self.size:
            return
        idx = (y * self.size + x) * 3
        if alpha >= 1.0:
            self.pix[idx] = colour[0]
            self.pix[idx + 1] = colour[1]
            self.pix[idx + 2] = colour[2]
        else:
            keep = 1.0 - alpha
            self.pix[idx] = colour[0] * alpha + self.pix[idx] * keep
            self.pix[idx + 1] = colour[1] * alpha + self.pix[idx + 1] * keep
            self.pix[idx + 2] = colour[2] * alpha + self.pix[idx + 2] * keep

    def fill_vertical_gradient(self, top, bottom):
        """Paint a smooth top-to-bottom gradient over the whole canvas."""
        size = self.size
        for y in range(size):
            t = y / (size - 1)
            r = top[0] + (bottom[0] - top[0]) * t
            g = top[1] + (bottom[1] - top[1]) * t
            b = top[2] + (bottom[2] - top[2]) * t
            base = y * size * 3
            for x in range(size):
                idx = base + x * 3
                self.pix[idx] = r
                self.pix[idx + 1] = g
                self.pix[idx + 2] = b

    def disc(self, cx, cy, r, colour, alpha=1.0, edge=1.5):
        """Stamp a filled circle with a soft edge."""
        x0 = max(0, int(cx - r - edge))
        x1 = min(self.size - 1, int(cx + r + edge) + 1)
        y0 = max(0, int(cy - r - edge))
        y1 = min(self.size - 1, int(cy + r + edge) + 1)
        for y in range(y0, y1 + 1):
            dy = y - cy
            for x in range(x0, x1 + 1):
                dx = x - cx
                dist = math.hypot(dx, dy)
                cov = feather(r - dist, edge)
                if cov > 0.0:
                    self.blend(x, y, colour, alpha * cov)

    def ellipse(self, cx, cy, rx, ry, colour, alpha=1.0, edge=1.5):
        """Stamp a filled ellipse with a soft edge."""
        x0 = max(0, int(cx - rx - edge))
        x1 = min(self.size - 1, int(cx + rx + edge) + 1)
        y0 = max(0, int(cy - ry - edge))
        y1 = min(self.size - 1, int(cy + ry + edge) + 1)
        shortest = min(rx, ry)
        for y in range(y0, y1 + 1):
            ny = (y - cy) / ry
            for x in range(x0, x1 + 1):
                nx = (x - cx) / rx
                q = math.sqrt(nx * nx + ny * ny)
                signed = (1.0 - q) * shortest
                cov = feather(signed, edge)
                if cov > 0.0:
                    self.blend(x, y, colour, alpha * cov)

    def polygon(self, points, colour, alpha=1.0, edge=1.5):
        """Stamp a filled convex polygon with a soft edge.

        A pixel is inside when it lies on the inner side of every edge;
        the smallest signed distance to an edge gives the coverage ramp.
        """
        cx = sum(p[0] for p in points) / len(points)
        cy = sum(p[1] for p in points) / len(points)
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        x0 = max(0, int(min(xs) - edge))
        x1 = min(self.size - 1, int(max(xs) + edge) + 1)
        y0 = max(0, int(min(ys) - edge))
        y1 = min(self.size - 1, int(max(ys) + edge) + 1)
        count = len(points)
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                nearest = None
                for i in range(count):
                    ax, ay = points[i]
                    bx, by = points[(i + 1) % count]
                    ex, ey = bx - ax, by - ay
                    # Inward normal: the perpendicular that points at the
                    # polygon's centroid.
                    nx, ny = -ey, ex
                    if (cx - ax) * nx + (cy - ay) * ny < 0:
                        nx, ny = -nx, -ny
                    length = math.hypot(nx, ny)
                    d = ((x - ax) * nx + (y - ay) * ny) / length
                    if nearest is None or d < nearest:
                        nearest = d
                cov = feather(nearest, edge)
                if cov > 0.0:
                    self.blend(x, y, colour, alpha * cov)

    def segment(self, x1, y1, x2, y2, half, colour, alpha=1.0, edge=1.5):
        """Stamp a thick straight line with soft ends and edges."""
        x0 = max(0, int(min(x1, x2) - half - edge))
        x1b = min(self.size - 1, int(max(x1, x2) + half + edge) + 1)
        y0 = max(0, int(min(y1, y2) - half - edge))
        y1b = min(self.size - 1, int(max(y1, y2) + half + edge) + 1)
        dx = x2 - x1
        dy = y2 - y1
        length_sq = dx * dx + dy * dy
        for y in range(y0, y1b + 1):
            for x in range(x0, x1b + 1):
                if length_sq > 0:
                    t = ((x - x1) * dx + (y - y1) * dy) / length_sq
                else:
                    t = 0.0
                t = max(0.0, min(1.0, t))
                px = x1 + t * dx
                py = y1 + t * dy
                dist = math.hypot(x - px, y - py)
                cov = feather(half - dist, edge)
                if cov > 0.0:
                    self.blend(x, y, colour, alpha * cov)

    def curve(self, p0, p1, p2, half, colour, alpha=1.0, steps=24):
        """Stamp a thick quadratic Bezier curve as a chain of discs."""
        for i in range(steps + 1):
            t = i / steps
            u = 1.0 - t
            x = u * u * p0[0] + 2.0 * u * t * p1[0] + t * t * p2[0]
            y = u * u * p0[1] + 2.0 * u * t * p1[1] + t * t * p2[1]
            self.disc(x, y, half, colour, alpha, edge=1.5)

    def shade_face(self):
        """Soft radial light and a faint darker rim over the face disc."""
        x0 = max(0, FACE_CX - FACE_R)
        x1 = min(self.size - 1, FACE_CX + FACE_R)
        y0 = max(0, FACE_CY - FACE_R)
        y1 = min(self.size - 1, FACE_CY + FACE_R)
        light_x, light_y = FACE_CX - 42, FACE_CY - 52
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                d = math.hypot(x - FACE_CX, y - FACE_CY)
                if d >= FACE_R - 6:
                    continue
                # Gentle light from the upper left.
                dl = math.hypot(x - light_x, y - light_y)
                glow = max(0.0, 1.0 - dl / 215.0)
                if glow > 0.0:
                    self.blend(x, y, FACE_LIGHT, 0.45 * glow * glow)
                # Faint darkening right at the rim.
                rim = smoothstep(0.80 * FACE_R, 0.985 * FACE_R, d)
                if rim > 0.0:
                    self.blend(x, y, FACE_RIM, 0.30 * rim)


# ---------------------------------------------------------------------------
# The picture, painted shape by shape
# ---------------------------------------------------------------------------

def draw_eye(canvas, cx, cy):
    """One big blue eye: dark rim, blue iris, dark pupil, two sparkles."""
    canvas.ellipse(cx, cy, 40, 54, EYE_RIM)
    canvas.ellipse(cx, cy, 29, 42, IRIS)
    canvas.ellipse(cx, cy - 2, 15, 23, PUPIL)
    canvas.disc(cx - 13, cy - 20, 13, HIGHLIGHT)
    canvas.disc(cx + 12, cy + 16, 6, HIGHLIGHT)


def paint():
    """Paint the whole picture and return the canvas."""
    canvas = Canvas(SIZE)
    canvas.fill_vertical_gradient(BG_TOP, BG_BOTTOM)

    # Ears first: the face disc painted next covers their bases, so the
    # ears look like they grow out of the head. The left ear sits higher
    # than the right one — that is the head tilt.
    canvas.polygon([(138, 56), (88, 152), (188, 136)], OUTLINE)
    canvas.polygon([(377, 80), (325, 142), (425, 154)], OUTLINE)
    canvas.polygon([(146, 86), (114, 144), (174, 130)], INNER_EAR)
    canvas.polygon([(370, 106), (338, 142), (396, 150)], INNER_EAR)

    # Face: tan rim, cream fill, then soft shading.
    canvas.disc(FACE_CX, FACE_CY, FACE_R, OUTLINE)
    canvas.disc(FACE_CX, FACE_CY, FACE_R - 6, FACE_CREAM)
    canvas.shade_face()

    # Eyes: the left one a touch higher, following the tilt.
    draw_eye(canvas, 180, 240)
    draw_eye(canvas, 335, 250)

    # Blush cheeks, very soft edges.
    canvas.ellipse(138, 324, 40, 23, BLUSH, alpha=0.55, edge=6.0)
    canvas.ellipse(374, 334, 40, 23, BLUSH, alpha=0.55, edge=6.0)

    # Nose and the little "w" mouth underneath it.
    canvas.polygon([(239, 304), (273, 304), (256, 326)], NOSE)
    canvas.curve((256, 336), (241, 362), (226, 338), 2.4, MOUTH)
    canvas.curve((256, 336), (271, 362), (286, 338), 2.4, MOUTH)

    # Whiskers, three per cheek, reaching past the face's edge.
    for x1, y1, x2, y2 in [
        (120, 282, 52, 262), (116, 308, 46, 306), (122, 336, 56, 356),
        (392, 282, 460, 262), (396, 308, 466, 306), (390, 336, 456, 356),
    ]:
        canvas.segment(x1, y1, x2, y2, 1.4, WHISKER, alpha=0.85)

    # One small pink bow at the base of the right ear.
    canvas.polygon([(332, 148), (292, 124), (296, 172)], BOW)
    canvas.polygon([(332, 148), (372, 124), (368, 172)], BOW)
    canvas.disc(332, 148, 9, BOW_KNOT)

    return canvas


# ---------------------------------------------------------------------------
# PNG encoding (standard library only)
# ---------------------------------------------------------------------------

def _chunk(kind, data):
    """One PNG chunk: length, type, data, CRC."""
    out = struct.pack(">I", len(data))
    out += kind + data
    out += struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return out


def encode_png(canvas):
    """Serialise the canvas as a 512x512 RGB PNG."""
    raw = bytearray()
    stride = SIZE * 3
    pixels = canvas.pix
    for y in range(SIZE):
        raw.append(0)  # filter: none
        start = y * stride
        for value in pixels[start:start + stride]:
            raw.append(max(0, min(255, int(round(value)))))
    header = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _chunk(b"IEND", b"")
    )


def main():
    """Render the kitten and write entry.png into the output directory."""
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    png = encode_png(paint())
    with open(os.path.join(out_dir, "entry.png"), "wb") as handle:
        handle.write(png)


if __name__ == "__main__":
    main()
