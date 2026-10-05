"""Dependency-free deterministic RGB chart raster with numeric axes.

Category names and units are retained in a required native legend by the consumer;
the PNG uses exact row ordinals rather than lossy Unicode font substitution.
"""
from __future__ import annotations

import struct
import zlib

RENDERER_ID = "research-chart-png/1"
WIDTH, HEIGHT = 800, 480
_FONT = {
    "0": (14,17,19,21,25,17,14), "1": (4,12,4,4,4,4,14),
    "2": (14,17,1,2,4,8,31), "3": (30,1,1,14,1,1,30),
    "4": (2,6,10,18,31,2,2), "5": (31,16,16,30,1,1,30),
    "6": (14,16,16,30,17,17,14), "7": (31,1,2,4,8,8,8),
    "8": (14,17,17,14,17,17,14), "9": (14,17,17,15,1,1,14),
    "-": (0,0,0,31,0,0,0), ".": (0,0,0,0,0,12,12),
    "+": (0,4,4,31,4,4,0), "e": (0,0,14,17,31,16,14),
    "x": (0,0,17,10,4,10,17), "y": (0,0,17,17,15,1,14),
}


def render_chart(validated: dict) -> bytes:
    points = validated["points"]
    chart_type = validated["spec"]["chart_type"]
    pixels = bytearray(b"\xff" * WIDTH * HEIGHT * 3)

    def pixel(x, y, color):
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            start = 3 * (y * WIDTH + x)
            pixels[start:start+3] = bytes(color)

    def line(x0, y0, x1, y1, color):
        dx, dy = abs(x1-x0), -abs(y1-y0)
        sx, sy = 1 if x0 < x1 else -1, 1 if y0 < y1 else -1
        error = dx+dy
        while True:
            pixel(x0, y0, color)
            if x0 == x1 and y0 == y1:
                return
            twice = 2*error
            if twice >= dy:
                error += dy; x0 += sx
            if twice <= dx:
                error += dx; y0 += sy

    def text(x, y, value):
        for char in value:
            for row, bits in enumerate(_FONT[char]):
                for col in range(5):
                    if bits & (1 << (4-col)):
                        for xx in range(2):
                            for yy in range(2):
                                pixel(x+col*2+xx, y+row*2+yy, (40,40,40))
            x += 12

    xs = list(range(1, len(points)+1)) if chart_type == "bar" else [p[0] for p in points]
    ys = [p[1] for p in points]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(0, min(ys)), max(0, max(ys))
    if chart_type == "bar":
        xmin, xmax = 0.5, len(points)+0.5
    if xmin == xmax:
        xmin -= 1; xmax += 1
    if ymin == ymax:
        ymin -= 1; ymax += 1
    left, right, top, bottom = 160, 760, 30, 420
    def px(value): return round(left+(value-xmin)/(xmax-xmin)*(right-left))
    def py(value): return round(bottom-(value-ymin)/(ymax-ymin)*(bottom-top))
    for i in range(5):
        value = ymin+(ymax-ymin)*i/4
        y = py(value)
        line(left, y, right, y, (220,220,220))
        text(8, y-7, format(value, ".5g"))
    ticks = xs[::max(1, (len(xs)+15)//16)] if chart_type == "bar" else [xmin+(xmax-xmin)*i/4 for i in range(5)]
    for value in ticks:
        text(max(left, min(right-120, px(value)-20)), bottom+20, format(value, ".5g"))
    text(right+10, bottom, "x"); text(left-15, top-20, "y")
    line(left, top, left, bottom, (40,40,40))
    line(left, py(0), right, py(0), (40,40,40))
    previous = None
    for x, y in zip(xs, ys):
        xx, yy = px(x), py(y)
        if chart_type == "bar":
            half_width = max(1, int((right-left)/len(points)*0.35))
            for col in range(xx-half_width, xx+half_width+1):
                line(col, py(0), col, yy, (38,103,170))
        else:
            if chart_type == "line" and previous is not None:
                line(*previous, xx, yy, (38,103,170))
            for col in range(xx-3, xx+4):
                for row in range(yy-3, yy+4):
                    pixel(col, row, (38,103,170))
        previous = (xx, yy)
    def chunk(kind, payload):
        return struct.pack(">I", len(payload))+kind+payload+struct.pack(">I", zlib.crc32(kind+payload)&0xffffffff)
    raw = b"".join(b"\0"+pixels[y*WIDTH*3:(y+1)*WIDTH*3] for y in range(HEIGHT))
    return b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR", struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0))+chunk(b"IDAT", zlib.compress(raw, 9))+chunk(b"IEND", b"")
