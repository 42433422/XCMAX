"""Structured output models for Excel template analysis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CellStyle:
    font_name: str | None = None
    font_size: float | None = None
    font_bold: bool | None = None
    font_color: str | None = None
    fill_pattern: str | None = None
    fill_fg_color: str | None = None
    fill_bg_color: str | None = None
    alignment_horizontal: str | None = None
    alignment_vertical: str | None = None
    border_style: str | None = None
    border_color: str | None = None
    number_format: str | None = None


@dataclass
class CellInfo:
    address: str
    row: int
    col: int
    value: Any
    type: str
    formula: str | None = None
    style: CellStyle | None = None
    is_merged: bool = False
    merged_range: str | None = None


@dataclass
class MergedCellInfo:
    range: str
    min_row: int
    max_row: int
    min_col: int
    max_col: int
    purpose: str = ""


@dataclass
class ContentZone:
    name: str
    rows: list[int]
    type: str
    description: str = ""


@dataclass
class EditableRange:
    range: str
    min_row: int
    max_row: int
    min_col: int
    max_col: int
    description: str
