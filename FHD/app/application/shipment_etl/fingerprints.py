"""Compatibility storage adapters and the import coordinator deduplication port."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.utils.operational_errors import RECOVERABLE_ERRORS


def _fingerprint_store_path() -> Path:
    """兼容旧测试 monkeypatch；真实幂等改走 SQLite。"""
    try:
        from app.utils.path_io.path_utils import get_data_dir

        root = Path(get_data_dir())
    except RECOVERABLE_ERRORS:
        root = Path.cwd() / "data"
    root.mkdir(parents=True, exist_ok=True)
    return root / "shipment_etl_fingerprints.json"


def _legacy_json_has_fingerprint(fingerprint: str, *, path_provider: Callable[[], Path]) -> bool:
    path = path_provider()
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data.get("entries") if isinstance(data, dict) else None
        return bool(isinstance(entries, dict) and fingerprint in entries)
    except RECOVERABLE_ERRORS:
        return False


def _is_fingerprint_imported(
    tenant_key: str, fingerprint: str, *, legacy_lookup: Callable[[str], bool]
) -> bool:
    from app.application.shipment_excel_etl_fingerprint_store import has_fingerprint

    if has_fingerprint(tenant_key, fingerprint):
        return True
    return legacy_lookup(fingerprint)


def _record_fingerprint_now(
    tenant_key: str,
    fingerprint: str,
    *,
    shipment_id: Any = None,
    unit_name: str = "",
    order_number: str = "",
    file_name: str = "",
) -> None:
    from app.application.shipment_excel_etl_fingerprint_store import record_fingerprint

    record_fingerprint(
        tenant_key,
        fingerprint,
        shipment_id=shipment_id,
        unit_name=unit_name,
        order_number=order_number,
        file_name=file_name,
    )


def _load_fingerprints(
    *, path_provider: Callable[[], Path], logger: logging.Logger
) -> dict[str, Any]:
    path = path_provider()
    if not path.is_file():
        return {"entries": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("entries"), dict):
            return data
    except RECOVERABLE_ERRORS:
        logger.warning("failed to load shipment etl fingerprints", exc_info=True)
    return {"entries": {}}


def _save_fingerprints(data: dict[str, Any], *, path_provider: Callable[[], Path]) -> None:
    path = path_provider()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class RecordFingerprint(Protocol):
    def __call__(
        self,
        tenant_key: str,
        fingerprint: str,
        *,
        shipment_id: Any = None,
        unit_name: str = "",
        order_number: str = "",
        file_name: str = "",
    ) -> None: ...


@dataclass(frozen=True)
class FingerprintPorts:
    contains: Callable[[str, str], bool]
    record: RecordFingerprint
    remove: Callable[[str, str], None]
