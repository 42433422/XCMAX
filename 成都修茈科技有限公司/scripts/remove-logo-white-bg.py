#!/usr/bin/env python3
"""Remove baked-in white / near-white backgrounds from partner logos (RGBA PNG).

Uses border-connected flood fill from image edges — not CSS edge masks.
"""
from __future__ import annotations

import argparse
from collections import deque
from pathlib import Path

from PIL import Image

DEFAULT_FILES = (
    "sunbird-logo.png",
    "partner-emblem-logo.png",
    "xiu-ci-logo.png",
)


def _is_background_pixel(r: int, g: int, b: int, bg_ref: tuple[int, int, int], tol: float) -> bool:
    dr = r - bg_ref[0]
    dg = g - bg_ref[1]
    db = b - bg_ref[2]
    dist = (dr * dr + dg * dg + db * db) ** 0.5
    if dist <= tol:
        return True
    # neutral light gray / off-white card (xiu-ci rounded rect)
    mx, mn = max(r, g, b), min(r, g, b)
    if mx >= 190 and (mx - mn) <= 28:
        return True
    # sunbird peachy paper white
    if r >= 210 and g >= 185 and b >= 170 and (r - b) <= 65 and (mx - mn) <= 55:
        return True
    return False


def _border_background_ref(im: Image.Image) -> tuple[int, int, int]:
    px = im.load()
    w, h = im.size
    samples: list[tuple[int, int, int]] = []
    for x in range(w):
        for y in (0, h - 1):
            r, g, b, a = px[x, y]
            if a > 8:
                samples.append((r, g, b))
    for y in range(h):
        for x in (0, w - 1):
            r, g, b, a = px[x, y]
            if a > 8:
                samples.append((r, g, b))
    if samples:
        return samples[0]
    return (255, 255, 255)


def remove_logo_background(im: Image.Image, tolerance: float = 42.0) -> Image.Image:
    im = im.convert("RGBA")
    px = im.load()
    w, h = im.size
    bg_ref = _border_background_ref(im)
    visited: set[tuple[int, int]] = set()
    q: deque[tuple[int, int]] = deque()

    for x in range(w):
        q.append((x, 0))
        q.append((x, h - 1))
    for y in range(h):
        q.append((0, y))
        q.append((w - 1, y))

    while q:
        x, y = q.popleft()
        if x < 0 or x >= w or y < 0 or y >= h:
            continue
        if (x, y) in visited:
            continue
        visited.add((x, y))
        r, g, b, a = px[x, y]
        if a < 8 or _is_background_pixel(r, g, b, bg_ref, tolerance):
            px[x, y] = (r, g, b, 0)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                q.append((x + dx, y + dy))

    return im


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove logo white backgrounds (flood from edges)")
    parser.add_argument(
        "--assets-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "assets",
    )
    parser.add_argument("--tolerance", type=float, default=42.0)
    parser.add_argument("files", nargs="*", default=list(DEFAULT_FILES))
    args = parser.parse_args()

    for name in args.files:
        path = args.assets_dir / name
        if not path.is_file():
            print(f"skip missing: {path}")
            continue
        tol = 38.0 if "emblem" in name else args.tolerance
        out = remove_logo_background(Image.open(path), tolerance=tol)
        out.save(path, "PNG", optimize=True)
        print(f"ok {path}")


if __name__ == "__main__":
    main()
