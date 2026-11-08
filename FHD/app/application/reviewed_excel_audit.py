"""Canonical bounded audit envelopes for reviewed Excel model calls."""

import hashlib
import json
import threading
from copy import deepcopy

from app.application.elt.errors import ModelRequestNotSent as ModelRequestNotSent
from app.application.elt.errors import ReviewedExcelError

MAX_ARCHIVE_BYTES = 20_000_000

# A live template call is at most 180s. Past this, an inflight claim with no
# stored provider body is a dead request, not a call still in flight.
UNANSWERED_INFLIGHT_SECONDS = 900


def release_unanswered_inflight(state: dict, updated_at) -> bool:
    """Let analyze continue when a claimed call stored no response and has gone stale.

    A response body keeps the lock. A recent claim keeps the lock so a live call
    is not sent twice.
    """
    from datetime import datetime, timezone

    checkpoint = state.get("analysis_checkpoint")
    records = state.get("model_audit")
    if not isinstance(checkpoint, dict) or checkpoint.get("phase") != "inflight":
        return False
    if not isinstance(records, list) or not records or not isinstance(records[-1], dict):
        return False
    latest = records[-1]
    if latest.get("state") != "inflight" or latest.get("response_base64"):
        return False
    if not isinstance(updated_at, datetime):
        return False
    moment = updated_at if updated_at.tzinfo else updated_at.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - moment).total_seconds()
    if age < UNANSWERED_INFLIGHT_SECONDS:
        return False
    latest["state"] = "unanswered"
    latest["reason"] = "no provider response stored before the analyze claim expired"
    checkpoint["phase"] = "ready"
    return True


def settle_call(state: dict, expected: str, outcome: str, reason: str) -> dict:
    """Write a failed call's outcome onto its audit record; ``unknown`` keeps the lock."""
    records = state.get("model_audit")
    latest = records[-1] if records else {}
    stored = latest.get("state") == "response_received"
    if latest.get("request_sha256") != expected or not (
        latest.get("state") == "inflight" or (stored and outcome != "not_sent")
    ):
        raise ReviewedExcelError("模型归档状态已改变，未解除请求锁")
    latest.update({"outcome": outcome, "reason": str(reason)[:300]})
    if not stored and outcome in {"not_sent", "rejected"}:
        latest["state"] = outcome
    return latest


def record_not_sent(state: dict, expected: str, reason: str, *, outcome: str = "not_sent") -> None:
    settle_call(state, expected, outcome, reason)
    state["analysis_checkpoint"]["phase"] = "ready"


# A rejected answer gets this many more model rounds before the step fails closed.
REPAIR_ROUNDS = 2
_REPAIR_ANSWER_CHARS = 12_000


def repair_turn(answer: str, reason: str) -> list[dict]:
    """Show the model its own rejected answer and the validator's cell-free reason."""
    return [
        {
            "role": "assistant",
            "content": str(answer or "")[:_REPAIR_ANSWER_CHARS] or "（上一轮没有可读答案）",
        },
        {
            "role": "user",
            "content": (
                f"上一轮答案未通过校验：{str(reason)[:300]}。"
                "只用已发送的内容和坐标修正这一处，不要编造坐标、范围或数据；"
                "仍按 output_schema 返回完整 JSON。"
            ),
        },
    ]


def ask_until_valid(ask, messages: list[dict], judge, *, rounds: int = REPAIR_ROUNDS):
    """``judge(ask(messages))`` with bounded repair rounds for rejected answers only.

    A validator error raised by ``judge`` means an answer arrived. Every failure
    before an answer propagates unchanged, so an unknown outcome is never resent.
    After the bound the last rejection is raised.
    """
    from app.application.elt.errors import ModelAnswerRejected

    turn: list[dict] = []
    for round_index in range(rounds + 1):
        try:
            result = ask([*messages, *turn])
            try:
                return judge(result)
            except ModelAnswerRejected:
                raise
            except ReviewedExcelError as exc:
                answer = getattr(result, "answer", "")
                raise ModelAnswerRejected(exc.public_message, answer=answer) from exc
        except ModelAnswerRejected as exc:
            if round_index == rounds:
                raise
            turn = repair_turn(exc.answer, exc.public_message)
    raise AssertionError("unreachable")


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


_answer = ContextVar("reviewed_excel_answer_text", default=None)
_request_claims = ContextVar("reviewed_excel_request_claims", default=None)
_LIVE_CLAIMS: set[str] = set()
_LIVE_LOCK = threading.Lock()


@contextmanager
def live_claims():
    """Claims made inside one request read as in progress until that request ends."""
    owned: list[str] = []
    token = _request_claims.set(owned)
    try:
        yield
    finally:
        _request_claims.reset(token)
        with _LIVE_LOCK:
            _LIVE_CLAIMS.difference_update(owned)


def mark_live(request_sha: str) -> None:
    owned = _request_claims.get()
    if owned is not None:
        with _LIVE_LOCK:
            _LIVE_CLAIMS.add(request_sha)
        owned.append(request_sha)


def is_live(request_sha: str | None) -> bool:
    with _LIVE_LOCK:
        return bool(request_sha) and request_sha in _LIVE_CLAIMS


@contextmanager
def capture_response(callback):
    """Yield a box that receives the model's raw answer text for a repair round."""
    box: dict = {}
    token = _capture.set(callback)
    answer_token = _answer.set(box)
    try:
        yield box
    finally:
        _answer.reset(answer_token)
        _capture.reset(token)


def response_capture():
    return _capture.get()


def note_answer(text: str) -> None:
    box = _answer.get()
    if box is not None:
        box["text"] = text


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
        parsed = None
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
    if isinstance(parsed, dict):
        for key in ("model", "provider"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                entry[key] = value.strip()[:160]
        failover_from = parsed.get("failover_from")
        if isinstance(failover_from, str) and failover_from.strip():
            entry["failover_from"] = failover_from.strip()[:160]
    if (
        len(json.dumps([*records[:-1], entry], ensure_ascii=False).encode("utf-8"))
        > MAX_ARCHIVE_BYTES
    ):
        raise ReviewedExcelError("模型归档超过安全预算，结果状态未知；不会自动重试")
    records[-1] = entry
