"""Bounded PNG validation shared by generated explanations, charts and Publication (#493)."""

from __future__ import annotations

import struct
import zlib

from .research_package_format import MAX_ITEM_BYTES

MAX_PIXELS = 4 * 1024 * 1024


def png_size(data: bytes) -> tuple[int, int]:
    """Validate bounded, non-interlaced 8-bit RGB/RGBA PNG without re-encoding.

    PNG signature, CRC, chunk ordering, IHDR and filtered scanlines follow
    https://www.w3.org/TR/png-3/. Other image encodings require an explicit
    retained conversion; Publication does not invent an image from a label.
    """
    if len(data) > MAX_ITEM_BYTES or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("not a bounded PNG")
    pos = 8
    width = height = channels = 0
    chunks = []
    compressed = bytearray()
    ended = False
    while pos + 12 <= len(data):
        size = int.from_bytes(data[pos : pos + 4], "big")
        kind = data[pos + 4 : pos + 8]
        end = pos + 12 + size
        if end > len(data) or zlib.crc32(data[pos + 4 : end - 4]) != int.from_bytes(
            data[end - 4 : end], "big"
        ):
            raise ValueError("PNG chunk/CRC mismatch")
        payload = data[pos + 8 : end - 4]
        if not chunks and kind != b"IHDR":
            raise ValueError("PNG header is missing")
        if kind == b"IHDR":
            if chunks or size != 13:
                raise ValueError("invalid PNG header")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
            if (
                not width
                or not height
                or width * height > MAX_PIXELS
                or depth != 8
                or color not in {2, 6}
                or compression
                or filtering
                or interlace
            ):
                raise ValueError("unsupported PNG dimensions/encoding")
            channels = 3 if color == 2 else 4
        elif kind == b"IDAT":
            if b"IDAT" in chunks and chunks[-1] != b"IDAT":
                raise ValueError("noncontiguous PNG image data")
            compressed.extend(payload)
        elif kind == b"IEND":
            if size or not compressed or end != len(data):
                raise ValueError("invalid PNG end")
            ended = True
        elif kind == b"PLTE":
            if b"PLTE" in chunks or compressed or not 3 <= size <= 768 or size % 3:
                raise ValueError("invalid PNG palette")
        elif kind in {b"acTL", b"fcTL", b"fdAT"} or not (kind[0] & 32):
            raise ValueError("unsupported PNG chunk")
        chunks.append(kind)
        pos = end
        if ended:
            break
    if not ended:
        raise ValueError("incomplete PNG")
    stride = width * channels + 1
    expected = stride * height
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(bytes(compressed), expected + 1)
    except zlib.error as exc:
        raise ValueError("invalid PNG compression") from exc
    if len(raw) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError("PNG scanline size mismatch")
    if any(raw[offset] > 4 for offset in range(0, expected, stride)):
        raise ValueError("invalid PNG scanline filter")
    return width, height
