"""送货单 ETL LLM 辅助：仅补列映射 / 抬头 meta / sheet 类型。

规则优先；低置信时调用 structured output。失败静默降级。
数值明细仍由引擎确定性读单元格，LLM 不得编造数量/金额。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_FIELD_KEYS = (
    "model_number",
    "product_name",
    "quantity_tins",
    "tin_spec",
    "quantity_kg",
    "unit_price",
    "amount",
    "order_number",
    "order_date",
    "remark",
)

_ASSIST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["source_kind", "header_row", "columns", "meta"],
    "properties": {
        "source_kind": {
            "type": "string",
            "enum": ["delivery_note", "shipment_ledger", "ignore"],
        },
        "header_row": {"type": "integer"},
        "columns": {
            "type": "object",
            "properties": {k: {"type": "integer"} for k in _FIELD_KEYS},
            "additionalProperties": False,
        },
        "meta": {
            "type": "object",
            "properties": {
                "unit_name": {"type": "string"},
                "contact_person": {"type": "string"},
                "order_date": {"type": "string"},
                "order_number": {"type": "string"},
                "title": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "additionalProperties": False,
}


@dataclass
class SheetProbe:
    """喂给 LLM 的轻量探测包（禁止整表）。"""

    profile_id: str
    sheet_title: str
    probe_rows: list[dict[str, Any]]
    candidate_headers: list[dict[str, Any]]
    max_row: int
    max_col: int
    rule_hint: dict[str, Any] = field(default_factory=dict)


@dataclass
class AssistResult:
    used_llm: bool = False
    cache_hit: bool = False
    ok: bool = False
    source_kind: str = ""
    header_row: int | None = None
    columns: dict[str, int] = field(default_factory=dict)
    meta: dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0
    reason: str = ""
    error: str = ""

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "used_llm": self.used_llm,
            "cache_hit": self.cache_hit,
            "ok": self.ok,
            "confidence": self.confidence,
            "reason": self.reason or self.error,
            "source_kind": self.source_kind,
            "header_row": self.header_row,
        }


_CACHE_LOCK = threading.Lock()
_CACHE: OrderedDict[str, AssistResult] = OrderedDict()
_CACHE_MAX = 64


def llm_assist_mode() -> str:
    """返回 auto / on / off。"""
    raw = str(os.environ.get("FHD_SHIPMENT_ETL_LLM") or "auto").strip().lower()
    if raw in {"0", "false", "no", "off", "disabled"}:
        return "off"
    if raw in {"1", "true", "yes", "on", "enabled"}:
        return "on"
    return "auto"


def llm_timeout_seconds() -> float:
    raw = str(os.environ.get("FHD_SHIPMENT_ETL_LLM_TIMEOUT") or "12").strip()
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 12.0


def _has_llm_credentials() -> bool:
    try:
        from app.infrastructure.llm.providers.credentials import resolve_openai_env_credentials

        key, _base = resolve_openai_env_credentials()
        return bool(str(key or "").strip())
    except RECOVERABLE_ERRORS:
        return False


def llm_assist_enabled() -> bool:
    mode = llm_assist_mode()
    if mode == "off":
        return False
    if mode == "on":
        return True
    return _has_llm_credentials()


def clear_assist_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def _cache_key(probe: SheetProbe) -> str:
    payload = {
        "profile_id": probe.profile_id,
        "sheet_title": probe.sheet_title,
        "probe_rows": probe.probe_rows,
        "candidate_headers": probe.candidate_headers,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> AssistResult | None:
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit is None:
            return None
        _CACHE.move_to_end(key)
        # return a shallow copy so callers can mutate flags
        return AssistResult(
            used_llm=hit.used_llm,
            cache_hit=True,
            ok=hit.ok,
            source_kind=hit.source_kind,
            header_row=hit.header_row,
            columns=dict(hit.columns),
            meta=dict(hit.meta),
            confidence=hit.confidence,
            reason=hit.reason,
            error=hit.error,
        )


def _cache_put(key: str, result: AssistResult) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = AssistResult(
            used_llm=result.used_llm,
            cache_hit=False,
            ok=result.ok,
            source_kind=result.source_kind,
            header_row=result.header_row,
            columns=dict(result.columns),
            meta=dict(result.meta),
            confidence=result.confidence,
            reason=result.reason,
            error=result.error,
        )
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)


def _allowed_columns(probe: SheetProbe) -> set[int]:
    cols: set[int] = set()
    for header in probe.candidate_headers:
        for cell in header.get("cells") or []:
            try:
                cols.add(int(cell.get("col")))
            except (TypeError, ValueError):
                continue
    if not cols:
        cols = set(range(1, max(1, int(probe.max_col or 1)) + 1))
    return cols


def _validate_and_normalize(data: dict[str, Any], probe: SheetProbe) -> AssistResult:
    kind = str(data.get("source_kind") or "").strip()
    if kind not in {"delivery_note", "shipment_ledger", "ignore"}:
        return AssistResult(used_llm=True, ok=False, error="invalid source_kind")

    header_row_raw = data.get("header_row")
    try:
        header_row = int(header_row_raw) if header_row_raw is not None else None
    except (TypeError, ValueError):
        return AssistResult(used_llm=True, ok=False, error="invalid header_row")

    if kind != "ignore":
        if header_row is None or header_row < 1 or header_row > max(1, int(probe.max_row or 1)):
            return AssistResult(used_llm=True, ok=False, error="header_row out of range")

    allowed = _allowed_columns(probe)
    columns_in = data.get("columns") if isinstance(data.get("columns"), dict) else {}
    columns: dict[str, int] = {}
    for key in _FIELD_KEYS:
        if key not in columns_in:
            continue
        try:
            col = int(columns_in[key])
        except (TypeError, ValueError):
            continue
        if col in allowed:
            columns[key] = col

    if kind == "delivery_note" and "product_name" not in columns and "model_number" not in columns:
        return AssistResult(used_llm=True, ok=False, error="delivery missing name/model columns")
    if kind == "shipment_ledger" and "order_number" not in columns:
        return AssistResult(used_llm=True, ok=False, error="ledger missing order_number")

    meta_in = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    meta = {
        "unit_name": str(meta_in.get("unit_name") or "").strip(),
        "contact_person": str(meta_in.get("contact_person") or "").strip(),
        "order_date": str(meta_in.get("order_date") or "").strip(),
        "order_number": str(meta_in.get("order_number") or "").strip(),
        "title": str(meta_in.get("title") or "").strip(),
    }
    try:
        confidence = float(data.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    reason = str(data.get("reason") or "").strip()
    return AssistResult(
        used_llm=True,
        ok=True,
        source_kind=kind,
        header_row=header_row,
        columns=columns,
        meta=meta,
        confidence=confidence,
        reason=reason or "llm_assist",
    )


def _build_messages(probe: SheetProbe) -> list[dict[str, str]]:
    user_payload = {
        "task": "Map shipment Excel sheet layout to semantic fields",
        "profile_id": probe.profile_id,
        "sheet_title": probe.sheet_title,
        "probe_rows": probe.probe_rows,
        "candidate_headers": probe.candidate_headers,
        "rule_hint": probe.rule_hint,
        "rules": [
            "Only output JSON matching the schema",
            "source_kind must be delivery_note, shipment_ledger, or ignore",
            "header_row is 1-based Excel row index",
            "columns values are 1-based Excel column indexes that appear in candidate_headers",
            "Do not invent column indexes",
            "Leave unknown meta fields as empty strings",
            "Do not invent quantities or amounts",
        ],
        "field_keys": list(_FIELD_KEYS),
    }
    return [
        {
            "role": "system",
            "content": (
                "You are a spreadsheet layout mapper for delivery notes / shipment ledgers. "
                "Return only JSON. Never invent cell values."
            ),
        },
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]


def assist_sheet_layout(probe: SheetProbe) -> AssistResult:
    """低置信时调用 LLM；关闭/失败时返回 used_llm=False。"""
    if not llm_assist_enabled():
        return AssistResult(used_llm=False, ok=False, reason="llm_disabled")

    key = _cache_key(probe)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    try:
        from app.infrastructure.llm.structured_output import (
            StructuredOutputError,
            complete_structured_sync,
        )

        result = complete_structured_sync(
            _build_messages(probe),
            schema=_ASSIST_SCHEMA,
            temperature=0.0,
            max_tokens=800,
            max_repairs=1,
            timeout_seconds=llm_timeout_seconds(),
            profile="default",
        )
        normalized = _validate_and_normalize(result.data, probe)
        if normalized.ok:
            _cache_put(key, normalized)
        return normalized
    except StructuredOutputError as exc:
        logger.info("shipment etl llm assist structured failure: %s", exc)
        return AssistResult(used_llm=True, ok=False, error=str(exc))
    except RECOVERABLE_ERRORS as exc:
        logger.info("shipment etl llm assist failed: %s", exc)
        return AssistResult(used_llm=True, ok=False, error=str(exc))


def needs_llm_assist(
    *,
    delivery_score: int,
    ledger_score: int,
    min_score: int,
    header_row: int | None,
    mapping: dict[str, int],
    meta: dict[str, str] | None,
    prefer_kind: str | None = None,
) -> tuple[bool, str]:
    """判断是否进入灰色区间。"""
    gray_low = 40
    mode = llm_assist_mode()
    incomplete = header_row is None or (
        "product_name" not in (mapping or {}) and "model_number" not in (mapping or {})
    )
    if prefer_kind == "delivery_note" or delivery_score >= gray_low:
        if gray_low <= delivery_score < min_score:
            return True, "delivery_score_gray"
        if delivery_score >= min_score:
            if header_row is None:
                return True, "delivery_header_missing"
            if "product_name" not in mapping and "model_number" not in mapping:
                return True, "delivery_columns_incomplete"
            if meta is not None and not str(meta.get("unit_name") or "").strip():
                return True, "delivery_unit_missing"
    if prefer_kind == "shipment_ledger" or (
        delivery_score < min_score and ledger_score >= 40
    ):
        if header_row is None:
            return True, "ledger_header_missing"
        if "order_number" not in mapping:
            return True, "ledger_order_missing"
        if "product_name" not in mapping and "model_number" not in mapping:
            return True, "ledger_columns_incomplete"
    # 陌生表头：强制开，或 auto 模式下有候选内容但列未识别
    if incomplete and prefer_kind in {None, "delivery_note", "shipment_ledger"}:
        if mode == "on":
            return True, "forced_on_incomplete_layout"
        if mode == "auto" and (delivery_score >= 16 or ledger_score >= 16 or header_row is not None):
            return True, "auto_unknown_headers"
    if delivery_score < gray_low and ledger_score < 40:
        return False, "scores_too_low"
    return False, "rules_confident"


__all__ = [
    "AssistResult",
    "SheetProbe",
    "assist_sheet_layout",
    "clear_assist_cache",
    "llm_assist_enabled",
    "llm_assist_mode",
    "llm_timeout_seconds",
    "needs_llm_assist",
]
