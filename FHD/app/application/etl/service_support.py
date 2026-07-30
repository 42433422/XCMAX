"""Shared state and deterministic helpers for the ETL service mixins."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.application.etl.errors import EtlError
from app.application.etl.targets import json_safe

logger = logging.getLogger(__name__)

MAX_FILE_MIB = 100
MAX_FILE_BYTES = MAX_FILE_MIB * 1024 * 1024
# A delivery layout is a private printing resource, not an ETL field-mapping
# template. It shares owner-scoped ETL persistence so document resolution can
# enforce tenant + owner isolation, but it must not be selectable for import.
ETL_SHIPMENT_DOCUMENT_TEMPLATE_DESCRIPTION = "ETL_SHIPMENT_DOCUMENT_TEMPLATE"
EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="fhd-etl")
SUBMITTED: set[str] = set()
SUBMITTED_LOCK = threading.Lock()
DOCUMENT_ROUTE_LOCK = threading.Lock()
SENSITIVE_WEBHOOK_HEADER_PARTS = (
    "authorization",
    "cookie",
    "token",
    "secret",
    "api-key",
)
ALLOWED_VALIDATION_OPS = frozenset({"required", "enum", "min", "max", "min_length", "max_length"})


def dump_json(value: Any) -> str:
    return json.dumps(json_safe(value), ensure_ascii=False, sort_keys=True, default=str)


def load_json(raw: str | None, default: Any) -> Any:
    try:
        return json.loads(raw or "")
    except (TypeError, ValueError):
        return default


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_session():
    # Keep the historical service.SessionLocal seam patchable for desktop tests
    # and embedders while implementation lives in focused mixin modules.
    from app.application.etl import service

    return service.SessionLocal()


def clean_filename(value: str) -> str:
    name = Path(str(value or "upload")).name.replace("\x00", "")
    return (name[:240] or "upload").strip()


def clean_relative_path(value: str | None, file_name: str) -> str:
    parts = [
        part
        for part in str(value or file_name).replace("\\", "/").split("/")
        if part not in {"", ".", ".."}
    ]
    cleaned = "/".join(parts).replace("\x00", "")
    return (cleaned[:500] or clean_filename(file_name)).strip()


def clean_batch_id(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return str(uuid.UUID(raw))
    except ValueError as exc:
        raise EtlError("ETL_BATCH_ID_INVALID", "文件夹批次标识无效") from exc


def mapping_key(value: str) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def safe_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, EtlError):
        return exc.code, exc.message
    logger.exception("ETL operation failed")
    return "ETL_INTERNAL_ERROR", "ETL 处理失败，请检查文件或稍后重试"


def sanitize_webhook_headers(headers: dict[str, Any]) -> dict[str, str]:
    if len(headers) > 40:
        raise EtlError("ETL_WEBHOOK_HEADERS_INVALID", "Webhook 请求头数量不能超过 40")
    cleaned: dict[str, str] = {}
    for raw_name, raw_value in headers.items():
        name = str(raw_name or "").strip()
        value = str(raw_value or "").strip()
        lowered = name.casefold()
        if (
            not name
            or len(name) > 128
            or len(value) > 2048
            or "\r" in name
            or "\n" in name
            or "\r" in value
            or "\n" in value
        ):
            raise EtlError("ETL_WEBHOOK_HEADERS_INVALID", "Webhook 请求头格式无效")
        if any(part in lowered for part in SENSITIVE_WEBHOOK_HEADER_PARTS):
            raise EtlError(
                "ETL_WEBHOOK_SECRET_HEADER_FORBIDDEN",
                "敏感请求头必须通过系统凭据管理器配置",
            )
        cleaned[name] = value
    return cleaned


def apply_validation_rules(
    data: dict[str, Any], rules: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for rule in rules:
        field = str(rule.get("field") or "").strip()
        op = str(rule.get("op") or "").strip().lower()
        value = data.get(field)
        expected = rule.get("value")
        failed = False
        if op == "required":
            failed = value in (None, "")
        elif op == "enum":
            failed = not isinstance(expected, list) or value not in expected
        elif op in {"min", "max"}:
            try:
                actual_number = float(value)
                expected_number = float(expected)
                failed = (
                    actual_number < expected_number
                    if op == "min"
                    else actual_number > expected_number
                )
            except (TypeError, ValueError):
                failed = True
        elif op in {"min_length", "max_length"}:
            try:
                actual_length = len(str(value or ""))
                expected_length = int(expected)
                failed = (
                    actual_length < expected_length
                    if op == "min_length"
                    else actual_length > expected_length
                )
            except (TypeError, ValueError):
                failed = True
        if failed:
            issues.append(
                {
                    "code": "ETL_VALIDATION_RULE_FAILED",
                    "severity": "error",
                    "field": field,
                    "message": str(rule.get("message") or f"{field} 未通过 {op} 校验")[:300],
                }
            )
    return issues


def has_blocking_issues(issues: list[dict[str, Any]]) -> bool:
    return any(
        isinstance(issue, dict)
        and str(issue.get("severity") or "error").strip().lower() == "error"
        for issue in issues
    )
