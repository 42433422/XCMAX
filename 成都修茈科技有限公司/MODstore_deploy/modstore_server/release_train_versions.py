"""Pure four-segment version arithmetic for the internal release train."""

from __future__ import annotations

from typing import Literal, Tuple

ReleaseKind = Literal["daily", "installer", "major"]
Quad = Tuple[int, int, int, int]


def parse_quad(version: str) -> Quad:
    raw = (version or "").strip().lstrip("vV")
    parts = raw.split(".")
    if len(parts) != 4:
        raise ValueError(f"release_train expects 4 segments, got {version!r}")
    try:
        return tuple(int(part) for part in parts)  # type: ignore[return-value]
    except ValueError as exc:
        raise ValueError(f"release_train non-integer segment in {version!r}") from exc


def format_quad(a: int, b: int, c: int, d: int) -> str:
    return f"{a}.{b}.{c}.{d}"


def bump_quad(current: str) -> str:
    a, b, c, d = parse_quad(current)
    d += 1
    if d >= 10:
        d = 0
        c += 1
    if c >= 10:
        c = 0
        b += 1
    if b >= 10:
        b = 0
        a += 1
    return format_quad(a, b, c, d)


def is_installer_day(version: str, *, day_index: int) -> bool:
    _a, _b, _c, d = parse_quad(version)
    return d == 0 and int(day_index) > 0


def is_major_day(day_index: int) -> bool:
    return int(day_index) > 0 and int(day_index) % 100 == 0


def decennial_generation(version: str) -> int:
    _a, _b, c, _d = parse_quad(version)
    return int(c) + 1


def decennial_generation_label(version: str) -> str:
    return f"G{decennial_generation(version)}"


def next_decennial_anchor(version: str) -> str:
    a, b, c, _d = parse_quad(version)
    return format_quad(a, b, c + 1, 0)


def classify_release_kind(version: str, day_index: int) -> ReleaseKind:
    if is_major_day(day_index):
        return "major"
    if is_installer_day(version, day_index=day_index):
        return "installer"
    return "daily"


def bump_daily(current: str, *, day_index: int) -> tuple[str, ReleaseKind]:
    new_version = bump_quad(current)
    return new_version, classify_release_kind(new_version, int(day_index) + 1)
