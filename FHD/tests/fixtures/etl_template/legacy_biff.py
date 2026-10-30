"""Synthetic, data-only BIFF8/OLE fixture; no user workbook bytes."""

import struct


def record(k, b=b""):
    return struct.pack("<HH", k, len(b)) + b


def fixture(extra=b"", stream_name="Workbook", font_weight=400, text=None):
    bof = lambda t: record(0x809, struct.pack("<HHHHII", 0x600, t, 0xDBB, 0x7CC, 0x41, 6))
    sheet = (
        bof(16)
        + record(0x200, struct.pack("<IIHHH", 0, 1, 0, 1, 0))
        + record(0x203, struct.pack("<HHHd", 0, 0, 0, 7.0))
        + extra
        + record(0xA)
    )
    font = record(
        0x31,
        struct.pack("<HHHHHBBBB", 220, 0, 0x7FFF, font_weight, 0, 0, 0, 0, 0) + b"\x05\x00Arial",
    )
    xf = record(0xE0, struct.pack("<HHHBBBBIIH", 0, 0, 0, 0x20, 0, 0, 0, 0, 0, 0))
    glob = bof(5) + record(0x42, struct.pack("<H", 1200)) + record(0x22, b"\0\0") + font + xf
    bound = lambda off: record(0x85, struct.pack("<IBBB", off, 0, 0, 5) + b"\0Sheet")
    if text is not None:
        encoded = text.encode("utf-16le")
        glob += record(0xFC, struct.pack("<IIHB", 1, 1, len(text), 1) + encoded)
        sheet = sheet.replace(
            record(0x203, struct.pack("<HHHd", 0, 0, 0, 7.0)),
            record(0xFD, struct.pack("<HHHI", 0, 0, 0, 0)),
        )
    wb = glob + bound(len(glob) + len(bound(0)) + 4) + record(0xA) + sheet
    wb = wb.ljust(4096, b"\0")
    h = bytearray(512)
    h[:8] = bytes.fromhex("d0cf11e0a1b11ae1")
    struct.pack_into("<HHHH", h, 24, 0x3E, 3, 0xFFFE, 9)
    struct.pack_into("<H", h, 32, 6)
    struct.pack_into("<IIIIIIIII", h, 40, 0, 1, 8, 0, 4096, 0xFFFFFFFE, 0, 0xFFFFFFFE, 0)
    struct.pack_into("<109I", h, 76, 9, *([0xFFFFFFFF] * 108))

    def entry(name, typ, start, size, child=0xFFFFFFFF):
        b = bytearray(128)
        n = (name + "\0").encode("utf-16le")
        b[: len(n)] = n
        struct.pack_into("<HBBIII", b, 64, len(n), typ, 1, 0xFFFFFFFF, 0xFFFFFFFF, child)
        struct.pack_into("<IQ", b, 116, start, size)
        return b

    directory = (
        entry("Root Entry", 5, 0xFFFFFFFE, 0, 1) + entry(stream_name, 2, 0, 4096) + bytes(256)
    )
    fat = struct.pack(
        "<128I", 1, 2, 3, 4, 5, 6, 7, 0xFFFFFFFE, 0xFFFFFFFE, 0xFFFFFFFD, *([0xFFFFFFFF] * 118)
    )
    return bytes(h) + wb + directory + fat
