"""Canonical bounded audit envelopes for reviewed Excel model calls."""

import hashlib
import json
from copy import deepcopy

from app.application.elt.errors import ReviewedExcelError

MAX_ARCHIVE_BYTES = 20_000_000


class ModelRequestNotSent(ReviewedExcelError):
    """Only local pre-send validation may raise this; never use for transport errors."""


def record_not_sent(state: dict, expected: str, reason: str) -> None:
    records = state.get("model_audit")
    if (
        not records
        or records[-1].get("request_sha256") != expected
        or records[-1].get("state") != "inflight"
    ):
        raise ReviewedExcelError("模型归档状态已改变，未解除请求锁")
    records[-1].update({"state": "not_sent", "reason": reason})
    state["analysis_checkpoint"]["phase"] = "ready"


def request_digest(request: dict) -> str:
    encoded = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def claim_request(
    state: dict,
    request: dict,
    *,
    source_sha256: str,
    version: str,
    classification_id: str,
    code_version: str,
    model: str,
    phase: str,
    provider: str | None = None,
) -> str:
    """Stage pre-send evidence in the same state as the caller's DB CAS claim.

    This only stages data: the caller must commit the owner-scoped CAS before
    sending and must not send if the CAS fails. Never accept headers or keys.
    """
    if set(request) != {"messages", "schema", "max_tokens"}:
        raise ReviewedExcelError("归档请求格式无效")
    if phase not in {"classification", "grouping"} or not all(
        (source_sha256, version, classification_id, code_version, model)
    ):
        raise ReviewedExcelError("归档身份信息不完整，未调用模型")
    from app.application.reviewed_excel_template import configured_template_llm_provider

    digest = request_digest(request)
    resolved_provider = provider or configured_template_llm_provider()
    record = {
        "phase": phase,
        "state": "inflight",
        "classification_id": classification_id,
        "classification_version": version,
        "source_sha256": source_sha256,
        "code_version": code_version,
        "provider": resolved_provider,
        "model": model,
        "temperature": 0.0,
        "request": deepcopy(request),
        "request_sha256": digest,
    }
    if resolved_provider == "mimo":
        record["thinking"] = {"type": "disabled"}
    existing = state.setdefault("model_audit", [])
    if not isinstance(existing, list) or len(existing) >= 100:
        raise ReviewedExcelError("模型归档次数超过安全预算，未调用模型")
    if len(json.dumps([*existing, record], ensure_ascii=False).encode("utf-8")) > MAX_ARCHIVE_BYTES:
        raise ReviewedExcelError("模型归档超过安全预算，未调用模型")
    existing.append(record)
    return digest


def verify_request(request: dict, expected: str) -> None:
    if request_digest(request) != expected:
        raise ReviewedExcelError("模型请求与已归档输入不一致，未调用模型")


from contextlib import contextmanager
from contextvars import ContextVar

_capture = ContextVar("reviewed_excel_response_capture", default=None)


@contextmanager
def capture_response(callback):
    token = _capture.set(callback)
    try:
        yield
    finally:
        _capture.reset(token)


def response_capture():
    return _capture.get()


def record_response(state: dict, expected: str, body: bytes, status: int, request_id: str | None):
    """Stage the original provider body before any parsing or validation."""
    import base64
    import re

    if len(body) > 2_000_000:
        raise ReviewedExcelError("模型响应超出归档预算，结果状态未知；不会自动重试")
    records = state.get("model_audit")
    if (
        not records
        or records[-1].get("request_sha256") != expected
        or records[-1].get("state") != "inflight"
    ):
        raise ReviewedExcelError("模型归档状态已改变，结果状态未知；不会自动重试")
    if request_id and not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", request_id):
        request_id = None
    try:
        parsed = json.loads(body)
        usage = parsed.get("usage") if isinstance(parsed, dict) else None
    except (ValueError, UnicodeDecodeError):
        usage = None
    entry = {
        **records[-1],
        "state": "response_received",
        "http_status": status,
        "request_id": request_id,
        "usage": usage,
        "response_base64": base64.b64encode(body).decode("ascii"),
        "response_sha256": hashlib.sha256(body).hexdigest(),
    }
    if (
        len(json.dumps([*records[:-1], entry], ensure_ascii=False).encode("utf-8"))
        > MAX_ARCHIVE_BYTES
    ):
        raise ReviewedExcelError("模型归档超过安全预算，结果状态未知；不会自动重试")
    records[-1] = entry
