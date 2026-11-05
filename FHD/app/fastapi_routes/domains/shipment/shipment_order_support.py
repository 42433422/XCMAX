"""Shipment service access shared by the shipment order route modules."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from app.bootstrap import get_shipment_application_service_core


def svc() -> Any:
    """Single patch point for the shipment application service."""
    return get_shipment_application_service_core()


def safe_shipment_export_path(result: dict[str, Any]) -> str | None:
    from app.infrastructure.workspace import resolve_existing_file_under_root
    from app.utils.path_io.path_utils import get_data_dir

    filename = os.path.basename(str(result.get("filename") or ""))
    if not re.fullmatch(r"shipment_records_[^/\\]{1,160}_\d{8}_\d{6}\.xlsx", filename):
        return None
    try:
        candidate = resolve_existing_file_under_root(
            Path(get_data_dir()).resolve() / "exports", filename
        )
    except (OSError, ValueError):
        return None
    return str(candidate)
