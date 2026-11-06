"""Copy audit metadata without credentials or arbitrary object representations."""

from __future__ import annotations

import re
from typing import Any, cast

from app.security.log_redaction import redact_log_text

_CREDENTIAL_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "credential",
    "cookie",
    "sessionid",
    "sessionkey",
    "apikey",
    "accesskey",
    "privatekey",
    "licensekey",
    "databaseurl",
    "dburl",
    "connectionstring",
    "密码",
    "口令",
    "密钥",
    "令牌",
    "私钥",
)


def _safe_value(value: Any, depth: int) -> Any:
    if depth > 12:
        return "<omitted>"
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if not isinstance(key, str):
                continue
            normalized = re.sub(r"[\W_]+", "", key.casefold())
            if normalized == "pwd" or any(part in normalized for part in _CREDENTIAL_PARTS):
                continue
            cleaned[key] = _safe_value(item, depth + 1)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [_safe_value(item, depth + 1) for item in value]
    if isinstance(value, str):
        return redact_log_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return "<omitted>"


def sanitize_audit_record(record: dict[str, Any]) -> dict[str, Any]:
    """Preserve event and identity fields while stripping nested credential values."""
    return cast("dict[str, Any]", _safe_value(record, 0))
