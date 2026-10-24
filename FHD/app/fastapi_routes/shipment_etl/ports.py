"""Explicit application and file boundaries used by shipment HTTP adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

Payload = dict[str, Any]


class ShipmentApplication(Protocol):
    def preview(self, file_path: str | Path, **kwargs: Any) -> Payload: ...
    def execute(self, file_path: str | Path, **kwargs: Any) -> Payload: ...
    def batch_preview(self, directory: str | Path, **kwargs: Any) -> Payload: ...
    def batch_execute(self, directory: str | Path, **kwargs: Any) -> Payload: ...
    def write_delivery_template(self, notes: list[Payload], output_path: str | Path) -> Payload: ...
    def write_ledger_template(
        self, rows: list[Payload], output_path: str | Path, *, unit_name: str
    ) -> Payload: ...
    def regenerate(
        self, file_path: str | Path, output_path: str | Path, *, include_ledger: bool | str
    ) -> Payload: ...


class DocumentPreview(Protocol):
    def __call__(
        self, file_path: str | Path, *, include_ledger: bool | str, workspace_root: str | None
    ) -> Payload: ...


class TemplateIngest(Protocol):
    def __call__(
        self,
        result: Payload,
        *,
        file_path: str | Path | None,
        save_as_template: bool,
        template_name: str,
        template_scope: str,
        source: str,
    ) -> Payload: ...


class OutputPath(Protocol):
    def __call__(
        self, output_path: str | Path, *, workspace_root: str | Path | None = None
    ) -> Path: ...


class InputPath(Protocol):
    def __call__(
        self,
        file_path: str | Path,
        *,
        workspace_root: str | Path | None = None,
        must_exist: bool = False,
    ) -> Path: ...


class ExtractionHistory(Protocol):
    def get_logs(
        self, *, data_type: str | None, status: str | None, limit: int, offset: int
    ) -> list[Payload]: ...
    def get_log(self, log_id: int) -> Payload | None: ...


@dataclass(frozen=True)
class TemplateCapture:
    enabled: bool
    name: str
    scope: str
