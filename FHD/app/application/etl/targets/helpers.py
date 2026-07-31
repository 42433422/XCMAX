"""Shared deterministic validation and rollback helpers for ETL targets."""

from __future__ import annotations

import ipaddress
import os
import socket
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.application.etl.errors import EtlError
from app.application.etl.targets.base import TargetField, json_safe


def assert_safe_webhook_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise EtlError("ETL_WEBHOOK_URL_INVALID", "Webhook URL 必须是有效的 HTTP(S) 地址")
    if parsed.scheme != "https" and not truthy_env("FHD_ETL_ALLOW_HTTP_WEBHOOK"):
        raise EtlError("ETL_WEBHOOK_HTTPS_REQUIRED", "Webhook 默认只允许 HTTPS")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443)}
    except OSError as exc:
        raise EtlError("ETL_WEBHOOK_DNS_FAILED", "Webhook 域名无法解析") from exc
    if not truthy_env("FHD_ETL_ALLOW_PRIVATE_WEBHOOK"):
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
            ):
                raise EtlError("ETL_WEBHOOK_PRIVATE_ADDRESS_FORBIDDEN", "Webhook 禁止访问内网地址")


def issue(code: str, field: str, message: str) -> dict[str, Any]:
    return {"code": code, "field": field, "severity": "error", "message": message}


def optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def decimal_or_zero(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0").replace(",", ""))
    except Exception as exc:  # noqa: BLE001
        raise EtlError("ETL_NUMBER_INVALID", f"数字格式不正确: {value}") from exc


def parse_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise EtlError("ETL_DATE_INVALID", f"日期格式不正确: {value}") from exc


def model_values(obj: Any, fields: tuple[TargetField, ...]) -> dict[str, Any]:
    return json_safe({field.key: getattr(obj, field.key, None) for field in fields})


def _values_equal(current: Any, expected: Any) -> bool:
    if isinstance(current, Decimal):
        try:
            return current == Decimal(str(expected))
        except Exception:  # noqa: BLE001
            return False
    if isinstance(current, datetime):
        return current.isoformat() == str(expected)
    if isinstance(current, date):
        return current.isoformat() == str(expected)
    if current is None or expected is None:
        return current is None and expected is None
    return str(current) == str(expected)


def _changed_image_fields(
    before: dict[str, Any],
    after: dict[str, Any],
    fields: tuple[TargetField, ...],
) -> list[TargetField]:
    return [
        field
        for field in fields
        if field.key in before
        and field.key in after
        and not _values_equal(before.get(field.key), after.get(field.key))
    ]


def assert_rollback_image_matches(
    obj: Any,
    before: dict[str, Any],
    after: dict[str, Any],
    fields: tuple[TargetField, ...],
    label: str,
) -> None:
    for field in _changed_image_fields(before, after, fields):
        if not _values_equal(getattr(obj, field.key, None), after.get(field.key)):
            raise EtlError(
                "ETL_ROLLBACK_CONCURRENT_CHANGE",
                f"{label}在本次导入后又被修改，已停止撤销以避免覆盖新数据",
                status_code=409,
            )


def assert_created_row_unchanged(
    obj: Any,
    after: dict[str, Any],
    fields: tuple[TargetField, ...],
    label: str,
) -> None:
    for field in fields:
        if field.key not in after:
            continue
        if not _values_equal(getattr(obj, field.key, None), after.get(field.key)):
            raise EtlError(
                "ETL_ROLLBACK_CONCURRENT_CHANGE",
                f"{label}在本次导入后又被修改，已停止撤销以避免删除新数据",
                status_code=409,
            )


def assert_snapshot_unchanged(
    obj: Any,
    snapshot: dict[str, Any],
    label: str,
) -> None:
    for key, expected in snapshot.items():
        if key in {"id", "created_at", "updated_at"} or not hasattr(obj, key):
            continue
        if not _values_equal(getattr(obj, key), expected):
            raise EtlError(
                "ETL_ROLLBACK_CONCURRENT_CHANGE",
                f"{label}在本次导入后又被修改，已停止撤销以避免删除新数据",
                status_code=409,
            )


def is_uploaded_document_path(document_path: str, context: dict[str, Any]) -> bool:
    upload_path = str(context.get("upload_path") or "").strip()
    if not upload_path:
        return False
    try:
        return Path(document_path).expanduser().resolve() == Path(upload_path).resolve()
    except OSError:
        return False


def truthy_env(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}
