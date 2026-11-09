"""Canonical bounded audit envelopes for reviewed Excel model calls."""

import hashlib
import json
import os
import threading
from copy import deepcopy
from datetime import UTC
from typing import Any
from uuid import uuid4

from app.application.elt.errors import ModelRequestNotSent as ModelRequestNotSent
from app.application.elt.errors import ReviewedExcelError

MAX_ARCHIVE_BYTES = 20_000_000

# One record per model call. ``streaming`` means the provider body is archived and
# not yet judged; ``unknown`` keeps the analyze lock until recovery or the user.
CALL_STATES = frozenset(
    {
        "not_sent",
        "sent",
        "streaming",
        "answered_valid",
        "answered_invalid",
        "truncated",
        "rejected",
        "unknown",
        "recovered",
        "abandoned",
    }
)
_TRANSITIONS = {
    "sent": {"streaming", "recovered", "not_sent", "rejected", "unknown", "abandoned"},
    "streaming": {"answered_valid", "answered_invalid", "truncated", "rejected", "unknown"},
    "recovered": {"answered_valid", "answered_invalid", "truncated", "rejected", "unknown"},
    "unknown": {"sent", "abandoned"},
}
_LEGACY_OUTCOME_STATES = {"answered_invalid", "rejected", "unknown", "not_sent", "truncated"}
# A fresh token per backend process: a claim owned by another token has no live sender here.
PROCESS_BOOT = uuid4().hex


def call_state(record: dict) -> str:
    """Lifecycle state of one record, mapping pre-lifecycle archives lazily."""
    state = record.get("state")
    if isinstance(state, str) and state in CALL_STATES:
        return state
    if state == "inflight":
        return "unknown" if record.get("outcome") == "unknown" else "sent"
    if state == "unanswered":
        return "unknown"
    if state == "response_received":
        outcome = record.get("outcome")
        if isinstance(outcome, str) and outcome in _LEGACY_OUTCOME_STATES - {"not_sent"}:
            return outcome
        status = record.get("http_status")
        return "answered_valid" if isinstance(status, int) and 200 <= status < 300 else "unknown"
    raise ReviewedExcelError("模型归档状态无效，未调用模型")


def normalize_audit(state: dict) -> None:
    """Rewrite legacy record states in place; the original name stays as legacy_state."""
    for record in state.get("model_audit") or []:
        if isinstance(record, dict) and record.get("state") not in CALL_STATES:
            current = call_state(record)
            record["legacy_state"] = record.get("state")
            record["state"] = current


def transition(record: dict, target: str, **fields) -> dict:
    from datetime import datetime

    current = call_state(record)
    if current == target == "unknown":
        record.update(fields)
        return record
    if target not in _TRANSITIONS.get(current, set()):
        raise ReviewedExcelError("模型归档状态已改变，未解除请求锁")
    record.update(fields)
    record["state"] = target
    history = record.setdefault("transitions", [])
    history.append(
        {"from": current, "to": target, "at": datetime.now(UTC).isoformat(timespec="seconds")}
    )
    del history[:-12]
    return record


def owner_stamp() -> dict:
    """Liveness is by claim owner: another boot's unsettled claim died with that process."""
    return {"boot": PROCESS_BOOT, "pid": os.getpid()}


def owned_here(record: dict) -> bool:
    owner = record.get("owner")
    return isinstance(owner, dict) and owner.get("boot") == PROCESS_BOOT


_SETTLED_STATE = {
    "not_sent": "not_sent",
    "rejected": "rejected",
    "answered_invalid": "answered_invalid",
    "truncated": "truncated",
    "unknown": "unknown",
}


def settle_call(state: dict, expected: str, outcome: str, reason: str) -> dict:
    """Write a failed call's outcome as its lifecycle state; ``unknown`` keeps the lock."""
    records = state.get("model_audit")
    latest = records[-1] if records else {}
    if latest.get("request_sha256") != expected:
        raise ReviewedExcelError("模型归档状态已改变，未解除请求锁")
    stored = bool(latest.get("response_base64"))
    if stored and outcome == "not_sent":
        raise ReviewedExcelError("模型归档状态已改变，未解除请求锁")
    if not stored and outcome in {"answered_invalid", "truncated"}:
        # A validator saw an answer the transport did not archive (in-process replays).
        if call_state(latest) == "sent":
            transition(latest, "streaming")
    transition(latest, _SETTLED_STATE[outcome], outcome=outcome, reason=str(reason)[:300])
    return latest


def mark_answered(state: dict, expected: str) -> None:
    records = state.get("model_audit") or []
    if records and records[-1].get("request_sha256") == expected:
        if call_state(records[-1]) == "sent":
            transition(records[-1], "streaming")
        transition(records[-1], "answered_valid")


def abandon_call(state: dict, expected: str, *, authorized_by: str, note: str) -> dict:
    """Unlock an unknown call only on an explicit user decision that may cost twice."""
    from datetime import datetime

    records = state.get("model_audit") or []
    latest = records[-1] if records else {}
    if latest.get("request_sha256") != expected or call_state(latest) not in {"sent", "unknown"}:
        raise ReviewedExcelError("没有可放弃的未知结果请求")
    if is_live(expected) or (owned_here(latest) and call_state(latest) == "sent"):
        raise ReviewedExcelError("该请求仍在本进程处理中，不能放弃")
    transition(
        latest,
        "abandoned",
        abandoned_by=str(authorized_by)[:80],
        abandoned_note=str(note)[:300],
        abandoned_at=datetime.now(UTC).isoformat(timespec="seconds"),
        possible_duplicate_charge=True,
    )
    checkpoint = state.get("analysis_checkpoint")
    if isinstance(checkpoint, dict):
        checkpoint["phase"] = "ready"
        checkpoint.pop("recovery", None)
    return latest


def recovery_action(record: dict, lookup: dict | None) -> str:
    """resend, wait or locked for a call with no live sender in this process.

    Only a market that confirms idempotency for this call_id makes a resend safe:
    it starts a never-received request once or replays the stored answer.
    """
    if not record.get("call_id") or not isinstance(lookup, dict) or not lookup.get("supported"):
        return "locked"
    market_state = lookup.get("state")
    if market_state == "processing":
        return "wait"
    if market_state in {"not_found", "completed", "failed"}:
        return "resend"
    return "locked"


def resume_claim(state: dict, expected: str) -> None:
    """Reopen the same record for a same-key recovery resend."""
    records = state.get("model_audit") or []
    latest = records[-1] if records else {}
    if latest.get("request_sha256") != expected or call_state(latest) not in {"sent", "unknown"}:
        raise ReviewedExcelError("恢复请求与已归档请求不一致，未调用模型")
    if call_state(latest) == "unknown":
        transition(latest, "sent")
    latest["attempts"] = int(latest.get("attempts") or 1) + 1
    latest["owner"] = owner_stamp()


def record_not_sent(state: dict, expected: str, reason: str, *, outcome: str = "not_sent") -> None:
    settle_call(state, expected, outcome, reason)
    state["analysis_checkpoint"]["phase"] = "ready"


# A rejected answer gets this many more model rounds before the step fails closed.
REPAIR_ROUNDS = 2
_REPAIR_ANSWER_CHARS = 12_000


def _pack_id_repair_clause(
    primary_ids: list[str] | None, source_ids: list[str] | None
) -> str:
    """Force the repair turn to reuse only pack-whitelisted evidence identities."""
    if not primary_ids:
        return ""
    shown = list(primary_ids)[:80]
    extra = len(primary_ids) - len(shown)
    clause = (
        f" evidence_ids 与 primary_id 必须全部选自本批主体白名单（共 {len(primary_ids)} 个"
        f"{'，示例如下' if extra else ''}）：{', '.join(shown)}"
        + (" …其余见 output_schema.physical_regions.items.properties.evidence_ids。" if extra else "。")
        + " context_only 的 evidence_id 只能放进 dependency_ids，禁止写入 evidence_ids/primary_id；"
        "没有主体证据的空白区域请删除，不要编造白名单之外的编号。"
    )
    if source_ids and set(source_ids) - set(primary_ids):
        clause += " dependency_ids 可使用含 context_only 的本批全部 evidence_id，但仍不得编造未发送编号。"
    clause += (
        " 每条 evidence_ids 坐标必须落在同一 physical_region.range 内；"
        "可按 sheets[].pack_primary_outer_a1 / drawing_cluster_outer_a1 扩大矩形覆盖本批主体格，"
        "禁止发明未发送的 range 或 evidence_id。"
    )
    return clause


def repair_turn(
    answer: str,
    reason: str,
    *,
    primary_ids: list[str] | None = None,
    source_ids: list[str] | None = None,
) -> list[dict]:
    """Show the model its rejected answer and force pack-only evidence IDs on repair."""
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
                f"{_pack_id_repair_clause(primary_ids, source_ids)}"
            ),
        },
    ]


def pack_evidence_id_lists(schema: dict | None) -> tuple[list[str] | None, list[str] | None]:
    """Read primary / full evidence_id enums from an identify provider schema."""
    if not isinstance(schema, dict):
        return None, None
    try:
        props = schema["properties"]["physical_regions"]["items"]["properties"]
    except (KeyError, TypeError):
        return None, None
    primary = props.get("primary_id", {}).get("enum") or props.get("evidence_ids", {}).get(
        "items", {}
    ).get("enum")
    source = props.get("dependency_ids", {}).get("items", {}).get("enum") or primary
    if not isinstance(primary, list) or not primary:
        return None, None
    if not isinstance(source, list) or not source:
        source = primary
    return [str(x) for x in primary], [str(x) for x in source]


def ask_until_valid(ask, messages: list[dict], judge, *, rounds: int = REPAIR_ROUNDS):
    """``judge(ask(messages))`` with bounded repair rounds for rejected answers only.

    A validator error raised by ``judge`` means an answer arrived. Every failure
    before an answer propagates unchanged, so an unknown outcome is never resent.
    After the bound the last rejection is raised. A truncated answer is raised at
    once: the same prompt would stop at the same limit.
    """
    from app.application.elt.errors import ModelAnswerRejected, ModelAnswerTruncated

    primary_ids = source_ids = None
    try:
        payload = json.loads(messages[1]["content"]) if len(messages) > 1 else {}
        primary_ids, source_ids = pack_evidence_id_lists(
            payload.get("output_schema") if isinstance(payload, dict) else None
        )
    except (TypeError, ValueError, json.JSONDecodeError, IndexError, KeyError):
        primary_ids = source_ids = None

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
            if round_index == rounds or isinstance(exc, ModelAnswerTruncated):
                raise
            turn = repair_turn(
                exc.answer,
                exc.public_message,
                primary_ids=primary_ids,
                source_ids=source_ids,
            )
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
    from datetime import datetime

    from app.application.reviewed_excel_template import configured_template_llm_provider

    digest = request_digest(request)
    checkpoint = state.get("analysis_checkpoint")
    recovery = checkpoint.pop("recovery", None) if isinstance(checkpoint, dict) else None
    if recovery:
        if recovery.get("request_sha256") != digest:
            raise ReviewedExcelError("恢复请求与已归档请求不一致，未调用模型")
        resume_claim(state, digest)
        return digest
    resolved_provider = provider or configured_template_llm_provider()
    record = {
        "phase": phase,
        "state": "sent",
        "call_id": uuid4().hex,
        "owner": owner_stamp(),
        "sent_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "attempts": 1,
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

_capture: ContextVar[Any] = ContextVar("reviewed_excel_response_capture", default=None)


_answer: ContextVar[Any] = ContextVar("reviewed_excel_answer_text", default=None)
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


_call_id: ContextVar[str | None] = ContextVar("reviewed_excel_call_id", default=None)


@contextmanager
def capture_response(callback, *, call_id: str | None = None):
    """Yield a box that receives the model's raw answer text for a repair round."""
    box: dict = {}
    token = _capture.set(callback)
    answer_token = _answer.set(box)
    call_token = _call_id.set(call_id)
    try:
        yield box
    finally:
        _call_id.reset(call_token)
        _answer.reset(answer_token)
        _capture.reset(token)


@contextmanager
def call_key(call_id: str | None):
    token = _call_id.set(call_id)
    try:
        yield
    finally:
        _call_id.reset(token)


def response_capture():
    return _capture.get()


def current_call_id() -> str | None:
    """The idempotency key the market sees for the call being sent."""
    return _call_id.get()


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
        or call_state(records[-1]) != "sent"
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
    entry = transition(
        deepcopy(records[-1]),
        "recovered" if re.search(rb'"replayed"\s*:\s*true', body) else "streaming",
    )
    entry = {
        **entry,
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
