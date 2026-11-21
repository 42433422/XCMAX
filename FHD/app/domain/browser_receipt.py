"""Keep incomplete evidence delivery distinct from the observed browser outcome."""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any


def evidence_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def assertion_value(kind: str, value: Any) -> Any:
    if kind == "text":
        return re.sub(r"\s+", " ", str(value or "")).strip()
    if kind == "visible" and value in {"true", "false"}:
        return value == "true"
    return value


def observed_assertion(check: dict, actual: Any) -> dict:
    """Retain the actual host observation, without copying private field values."""
    kind = check["kind"]
    expected = assertion_value(kind, check.get("expected"))
    actual = assertion_value(kind, actual)
    return {
        "kind": kind,
        "status": "passed" if type(actual) is type(expected) and actual == expected else "failed",
        "assertion_sha256": evidence_hash(check),
        "expected_sha256": evidence_hash(expected),
        "observed_sha256": evidence_hash(actual),
        "observed_at": time.time(),
    }


def mark_delivery_incomplete(result: dict, error_code: str) -> None:
    if "execution_outcome" not in result:
        result["execution_outcome"] = result.get("outcome", "unknown")
        if result.get("error_code"):
            result["execution_error_code"] = result["error_code"]
    result.update(
        success=False,
        outcome="unknown",
        retryable=False,
        reconciliation_required=True,
        delivery_status="incomplete",
        error_code=error_code,
        message="浏览器证据未完整保存；请核对原执行和核验记录，勿重复提交原操作。",
    )
