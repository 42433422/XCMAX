"""Narrow dependencies shared by workflow tool components."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

Payload = dict[str, Any]


class ExcelReader(Protocol):
    def __call__(
        self, p: Path, *, sheet_name: Any, header_row_1based: int | None
    ) -> pd.DataFrame: ...


@dataclass(frozen=True)
class ExcelIO:
    resolve: Callable[[str, str], Path]
    read: ExcelReader
    header: Callable[[Payload], int | None]


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: Payload
    workspace_root: str | None = None
    db_write_token: str | None = None
    runtime_context: Payload | None = None


ToolHandler = Callable[[ToolCall], str]
ExtensionHandler = Callable[[ToolCall], str | None]
