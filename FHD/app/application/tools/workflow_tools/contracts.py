"""Narrow dependencies shared by workflow tool components."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

Payload = dict[str, Any]
JsonTool = Callable[[Payload], Payload]


class ExcelReader(Protocol):
    def __call__(
        self, p: Path, *, sheet_name: Any, header_row_1based: int | None
    ) -> pd.DataFrame: ...


@dataclass(frozen=True)
class ExcelIO:
    resolve: Callable[[str, str], Path]
    read: ExcelReader
    header: Callable[[Payload], int | None]


class NaturalQuery(Protocol):
    def __call__(self, df: pd.DataFrame, natural_language: str, **kwargs: Any) -> Payload: ...


class WorkbookSchema(Protocol):
    def understand_dataframe(self, df: pd.DataFrame, *, file_path: str) -> Payload: ...


class VectorIngest(Protocol):
    def __call__(
        self, *, file_path: str, index_name: str | None, index_id: str | None
    ) -> Payload: ...


class CustomerWriter(Protocol):
    def create(self, data: Payload) -> Payload: ...


class ProductWriter(Protocol):
    def batch_add_products(self, products_data: list[Payload]) -> Payload: ...


class ShipmentWriter(Protocol):
    def create_shipment(self, unit_name: str, items_data: list[Payload]) -> Payload: ...


@dataclass(frozen=True)
class ImportServices:
    customer: Callable[[], CustomerWriter]
    products: Callable[[], ProductWriter]
    shipment: Callable[[], ShipmentWriter]
    find_customer: Callable[[str], Payload | None]


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: Payload
    workspace_root: str | None = None
    db_write_token: str | None = None
    runtime_context: Payload | None = None


ToolHandler = Callable[[ToolCall], str]
ExtensionHandler = Callable[[ToolCall], str | None]
