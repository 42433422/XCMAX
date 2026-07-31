"""Universal ETL V1 application service facade."""

from __future__ import annotations

import logging
import threading
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text

from app.application.etl.adviser import EtlRowAdviser, get_etl_row_adviser
from app.application.etl.parsers import (
    KNOWLEDGE_ONLY_SUFFIXES,
    MAX_ROWS,
    OCR_SUFFIXES,
    STRUCTURED_SUFFIXES,
)
from app.application.etl.service_draft import DraftServiceMixin
from app.application.etl.service_execution import ExecutionServiceMixin
from app.application.etl.service_history import HistoryServiceMixin
from app.application.etl.service_preview import PreviewServiceMixin
from app.application.etl.service_shipment_templates import ShipmentTemplateServiceMixin
from app.application.etl.service_support import MAX_FILE_BYTES
from app.application.etl.service_targets import TargetConfigServiceMixin
from app.application.etl.service_templates import TemplateServiceMixin
from app.application.etl.service_uploads import UploadServiceMixin
from app.application.etl.targets import target_capabilities
from app.application.etl.transforms import ALLOWED_TRANSFORMS
from app.db import SessionLocal as SessionLocal

logger = logging.getLogger(__name__)


class EtlService(
    UploadServiceMixin,
    PreviewServiceMixin,
    HistoryServiceMixin,
    DraftServiceMixin,
    ExecutionServiceMixin,
    TemplateServiceMixin,
    ShipmentTemplateServiceMixin,
    TargetConfigServiceMixin,
):
    def __init__(self, *, adviser: EtlRowAdviser | None = None) -> None:
        self._adviser = adviser or get_etl_row_adviser()

    def capabilities(self) -> dict[str, Any]:
        try:
            from app.application.shipment_etl_profile import list_profiles

            compatibility_presets = list_profiles()
        except Exception:  # noqa: BLE001
            compatibility_presets = []
        return {
            "enabled": True,
            "limits": {"max_file_bytes": MAX_FILE_BYTES, "max_rows": MAX_ROWS},
            "inputs": {
                "structured": sorted(STRUCTURED_SUFFIXES),
                "ocr": sorted(OCR_SUFFIXES),
                "knowledge_only": sorted(KNOWLEDGE_ONLY_SUFFIXES),
                "folder_upload": True,
            },
            "transforms": sorted(ALLOWED_TRANSFORMS),
            "targets": target_capabilities(),
            "compatibility_presets": compatibility_presets,
            "execution_policy": {
                "preview_required": True,
                "confirmation_required": True,
                "default_duplicate_action": "skip",
                "default_error_policy": "block_all",
            },
        }


def mark_interrupted_runs_on_startup(bind: Any) -> int:
    try:
        if not sa_inspect(bind).has_table("etl_runs"):
            return 0
        with bind.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE etl_runs
                    SET status = 'interrupted',
                        stage = 'interrupted',
                        error_code = 'ETL_EXECUTION_INTERRUPTED',
                        error_message = '上次处理被意外中断，请重新预演或重试',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE status IN ('queued', 'previewing', 'executing')
                    """
                )
            )
            return max(0, int(result.rowcount or 0))
    except Exception:  # noqa: BLE001
        logger.exception("Unable to mark interrupted ETL runs during startup")
        return 0


_SERVICE: EtlService | None = None
_SERVICE_LOCK = threading.Lock()


def get_etl_service() -> EtlService:
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            _SERVICE = EtlService()
        return _SERVICE
