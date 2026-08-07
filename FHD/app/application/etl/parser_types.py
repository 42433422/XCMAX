"""Shared parsed-dataset value objects for ETL input parsers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ParsedRow:
    sheet: str
    row_number: int
    values: dict[str, Any]
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedDataset:
    headers: list[str]
    rows: list[ParsedRow]
    source_features: dict[str, Any]
    warnings: list[dict[str, Any]] = field(default_factory=list)
