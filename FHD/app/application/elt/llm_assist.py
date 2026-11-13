"""Software-LLM assistance for general ETL.

The model may classify bounded workbook probes, suggest field mappings, and
explain deterministic row decisions.  It never receives authority to write
business data or to override target-adapter actions.
"""

from __future__ import annotations

import contextvars
import json
import logging
import threading
import time
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from app.application.elt import llm_assist_runtime as _runtime
from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class EltAssistTimeout(TimeoutError):
    """Provider call exceeded its deadline while its tracked worker is still active."""

    def __init__(self, worker: threading.Thread):
        super().__init__("ETL LLM assist timed out")
        self.worker = worker


_REGION_ROLES = frozenset(
    {
        "delivery_note",
        "shipment_ledger",
        "product_catalog",
        "customer_directory",
        "finance",
        "ignore",
    }
)
_ROW_ACTIONS = frozenset({"new", "update", "skip"})
_SAFE_MAPPING_TRANSFORMS = frozenset({"trim", "number", "date"})
_BUSINESS_DEADLINE: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "elt_business_deadline", default=None
)
_CALL_AUDITOR: contextvars.ContextVar[Any | None] = contextvars.ContextVar(
    "elt_intake_call_auditor", default=None
)


@contextmanager
def audit_intake_calls(callback):
    token = _CALL_AUDITOR.set(callback)
    try:
        yield
    finally:
        _CALL_AUDITOR.reset(token)


# ETL assistance is advisory.  A provider outage must never turn a preview
# into a sequence of long, duplicate calls (especially when an auto-detected
# delivery workbook creates the linked customer/product preview at the same
# time).  Keep this process-local on purpose: account credentials and quota
# state are not ETL business data and are never persisted with a run.
LlmAssistResult = _runtime.LlmAssistResult
clear_elt_llm_circuit = _runtime.clear_elt_llm_circuit
elt_llm_mode = _runtime.elt_llm_mode
elt_llm_timeout_seconds = _runtime.elt_llm_timeout_seconds
elt_row_advice_limit = _runtime.elt_row_advice_limit
_circuit_cooldown_seconds = _runtime.circuit_cooldown_seconds
_circuit_degradation = _runtime.circuit_degradation
_circuit_key = _runtime.circuit_key
_degradation_code = _runtime.degradation_code
_open_circuit = _runtime.open_circuit
_owner_call_lock = _runtime.owner_call_lock


def _bounded_structured_completion(
    messages: list[dict[str, str]],
    *,
    schema: dict[str, Any],
    max_tokens: int,
    timeout_seconds: float,
    conversation_service: Any | None,
    provider: Any | None,
    max_repairs: int = 0,
):
    """Run one structured LLM call without letting a worker thread stall.

    ``complete_structured_sync`` applies its timeout only when it detects an
    existing event loop.  Preview workers intentionally do not own one, so an
    outer daemon-thread deadline is required here.  A timed-out provider call
    may finish in the background, but the preview returns immediately and the
    ETL circuit prevents another advisory call while it is unhealthy.
    """

    from app.infrastructure.llm.structured_output import complete_structured_sync

    box: dict[str, Any] = {}

    def invoke() -> None:
        try:
            box["result"] = complete_structured_sync(
                messages,
                schema=schema,
                temperature=0.0,
                max_tokens=max_tokens,
                # A schema repair is another provider request.  ETL remains
                # deterministic without it, so never retry advisory output.
                max_repairs=max_repairs,
                timeout_seconds=timeout_seconds,
                profile="elt",
                conversation_service=conversation_service,
                provider=provider,
            )
        except BOUNDARY_ERRORS as exc:
            box["error"] = exc

    worker = threading.Thread(
        target=contextvars.copy_context().run,
        args=(invoke,),
        name="elt-llm-assist",
        daemon=True,
    )
    worker.start()
    worker.join(timeout=timeout_seconds)
    if worker.is_alive():
        raise EltAssistTimeout(worker)
    if "error" in box:
        raise box["error"]
    if "result" not in box:
        raise RuntimeError("ETL LLM assist returned no result")
    return box["result"]


def _active_software_llm(
    timeout_seconds: float | None = None,
) -> tuple[bool, Any | None, Any | None]:
    """Resolve the current user's software-account LLM, then app-wide providers."""
    try:
        from app.application.elt.llm_session_provider import current_owner_market_provider

        market_provider = current_owner_market_provider(
            timeout_seconds=(
                elt_llm_timeout_seconds() if timeout_seconds is None else timeout_seconds
            )
        )
        if market_provider is not None:
            return True, None, market_provider
        from app.infrastructure.llm.providers.registry import get_active_provider

        if get_active_provider(profile="elt") is not None:
            return True, None, None
        from app.domain.shared_services.ai_conversation_service import get_ai_conversation_service

        service = get_ai_conversation_service()
        if get_active_provider(conversation_service=service, profile="elt") is not None:
            return True, service, None
        return False, None, None
    except RECOVERABLE_ERRORS:
        return False, None, None


def elt_llm_enabled() -> bool:
    mode = elt_llm_mode()
    if mode == "off":
        return False
    configured, _service, _provider = _active_software_llm()
    return configured if mode == "auto" else True


def _complete(
    messages: list[dict[str, str]],
    *,
    schema: dict[str, Any],
    max_tokens: int,
    lane: str = "",
    max_repairs: int = 0,
    timeout_seconds: float | None = None,
) -> LlmAssistResult:
    mode = elt_llm_mode()
    if mode == "off":
        return LlmAssistResult()
    circuit_key = _circuit_key(lane)
    circuit_degradation = _circuit_degradation(circuit_key)
    if circuit_degradation:
        return LlmAssistResult(
            used_llm=False,
            degraded=True,
            degradation_code=circuit_degradation,
        )

    # Include account queueing in the same deadline as the provider call.
    budget = (
        timeout_seconds
        if timeout_seconds is not None
        else elt_llm_timeout_seconds() * (1 + max(0, max_repairs))
    )
    business_deadline = _BUSINESS_DEADLINE.get()
    if business_deadline is not None:
        budget = min(budget, business_deadline - time.monotonic())
        if budget <= 0:
            return LlmAssistResult(
                used_llm=False, degraded=True, degradation_code="ELT_LLM_BUDGET_EXHAUSTED"
            )
    deadline = time.monotonic() + max(0.0, budget)
    lock = _owner_call_lock(circuit_key)
    if not lock.acquire(timeout=max(0.0, budget)):
        return LlmAssistResult(
            used_llm=False, degraded=True, degradation_code="ELT_LLM_QUEUE_TIMEOUT"
        )
    release_on_exit = True
    try:
        circuit_degradation = _circuit_degradation(circuit_key)
        if circuit_degradation:
            return LlmAssistResult(
                used_llm=False,
                degraded=True,
                degradation_code=circuit_degradation,
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return LlmAssistResult(
                used_llm=False, degraded=True, degradation_code="ELT_LLM_QUEUE_TIMEOUT"
            )
        configured, conversation_service, provider = _active_software_llm(remaining)
        if not configured:
            return LlmAssistResult(
                used_llm=False,
                degraded=mode == "on",
                degradation_code="ELT_LLM_UNAVAILABLE" if mode == "on" else "",
            )
        budget = deadline - time.monotonic()
        if budget <= 0:
            return LlmAssistResult(
                used_llm=False, degraded=True, degradation_code="ELT_LLM_QUEUE_TIMEOUT"
            )
        called = False
        try:
            from app.application.reviewed_excel_audit import call_key

            auditor = _CALL_AUDITOR.get()
            call_id = uuid4().hex if auditor else None
            if auditor:
                auditor(call_id, lane, "sent")
            with call_key(call_id):
                called = True
                result = _bounded_structured_completion(
                    messages,
                    schema=schema,
                    max_tokens=max_tokens,
                    timeout_seconds=budget,
                    conversation_service=conversation_service,
                    provider=provider,
                    max_repairs=max_repairs,
                )
            if auditor:
                auditor(call_id, lane, "answered")
            return LlmAssistResult(
                used_llm=True,
                model=str(result.model or ""),
                billing=dict(result.billing or {}),
                data=dict(result.data),
            )
        except SQLAlchemyError:
            # A failed audit/database write is not a model outage. Let the
            # intake boundary record an uncertain attempt rather than opening
            # the provider circuit and silently offering a degraded result.
            raise
        except BOUNDARY_ERRORS as exc:  # Advisory-provider boundary: preserve deterministic ETL.
            from app.infrastructure.llm.structured_output import StructuredOutputError

            if isinstance(exc, StructuredOutputError) and exc.last_raw:
                if auditor:
                    auditor(call_id, lane, "answered_invalid")
                return LlmAssistResult(
                    used_llm=True,
                    degraded=True,
                    degradation_code="ELT_LLM_OUTPUT_INVALID",
                    answer=exc.last_raw,
                )
            degradation_code = _degradation_code(exc)
            _open_circuit(circuit_key, degradation_code)
            worker = getattr(exc, "worker", None)
            if isinstance(worker, threading.Thread):

                def release_after_worker() -> None:
                    worker.join()
                    lock.release()

                threading.Thread(
                    target=release_after_worker, name="elt-llm-lock-release", daemon=True
                ).start()
                release_on_exit = False
            _runtime.log_elt_llm_degradation(logger, code=degradation_code, lane=lane, exc=exc)
            return LlmAssistResult(
                used_llm=called,
                degraded=True,
                degradation_code=degradation_code,
            )

    finally:
        if release_on_exit:
            lock.release()


_REGION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["regions"],
    "properties": {
        "regions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["region_id", "role", "confidence", "reason"],
                "properties": {
                    "region_id": {"type": "string"},
                    "role": {"type": "string"},
                    "customer_name": {"type": "string"},
                    "contact_person": {"type": "string"},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "additionalProperties": False,
            },
        }
    },
    "additionalProperties": False,
}


def advise_workbook_regions(probes: list[dict[str, Any]]) -> LlmAssistResult:
    """Classify only deterministic candidate region IDs; never invent coordinates."""
    if not probes:
        return LlmAssistResult()
    bounded = []
    for probe in probes[:40]:
        bounded.append(
            {
                "region_id": str(probe.get("region_id") or "")[:120],
                "sheet": str(probe.get("sheet") or "")[:120],
                "header_row": int(probe.get("header_row") or 0),
                "headers": [str(item)[:120] for item in list(probe.get("headers") or [])[:24]],
                "context_rows": [
                    {
                        "row": int(item.get("row") or 0),
                        "text": str(item.get("text") or "")[:600],
                    }
                    for item in list(probe.get("context_rows") or [])[:5]
                    if isinstance(item, dict)
                ],
                "deterministic_role": str(probe.get("deterministic_role") or "")[:40],
                "explicit_customer": str(probe.get("explicit_customer") or "")[:160],
            }
        )
    messages = [
        {
            "role": "system",
            "content": (
                "You classify spreadsheet regions for enterprise ETL. Return JSON only. "
                "Use only supplied region_id values and source text. Never invent cells, "
                "customers, quantities, prices, or write actions."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "classify_workbook_regions",
                    "allowed_roles": sorted(_REGION_ROLES),
                    "rules": [
                        "delivery_note requires explicit buyer or customer evidence",
                        "finance, payment, reconciliation and balance tables are finance",
                        "a price list or color-code list is product_catalog",
                        "sheet or filename text alone is not sufficient customer identity",
                    ],
                    "regions": bounded,
                },
                ensure_ascii=False,
            ),
        },
    ]
    result = _complete(messages, schema=_REGION_SCHEMA, max_tokens=1800, lane="template")
    allowed_ids = {item["region_id"] for item in bounded if item["region_id"]}
    normalized: list[dict[str, Any]] = []
    for item in list(result.data.get("regions") or []):
        if not isinstance(item, dict):
            continue
        region_id = str(item.get("region_id") or "")
        role = str(item.get("role") or "")
        if region_id not in allowed_ids or role not in _REGION_ROLES:
            continue
        try:
            confidence = min(1.0, max(0.0, float(item.get("confidence") or 0.0)))
        except (TypeError, ValueError):
            confidence = 0.0
        normalized.append(
            {
                "region_id": region_id,
                "role": role,
                "customer_name": str(item.get("customer_name") or "")[:160],
                "contact_person": str(item.get("contact_person") or "")[:160],
                "confidence": confidence,
                "reason": str(item.get("reason") or "")[:300],
            }
        )
    result.data = {"regions": normalized}
    return result


_MAPPING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["mappings"],
    "properties": {
        "mappings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["source", "target", "confidence", "reason"],
                "properties": {
                    "source": {"type": "string"},
                    "target": {"type": "string"},
                    "transform": {"type": "string"},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "additionalProperties": False,
            },
        }
    },
    "additionalProperties": False,
}


def advise_field_mappings(
    *,
    headers: list[str],
    samples: dict[str, list[str]],
    target_fields: list[dict[str, Any]],
) -> LlmAssistResult:
    if not headers or not target_fields:
        return LlmAssistResult()
    messages = [
        {
            "role": "system",
            "content": (
                "You suggest spreadsheet field mappings. Return JSON only. Choose source "
                "and target names exclusively from the supplied lists. Never invent values. "
                "Allowed transforms are empty, trim, number, and date."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "suggest_elt_field_mappings",
                    "headers": [str(item)[:160] for item in headers[:100]],
                    "samples": {
                        str(key)[:160]: [str(value)[:160] for value in values[:3]]
                        for key, values in list(samples.items())[:100]
                    },
                    "target_fields": target_fields[:80],
                },
                ensure_ascii=False,
            ),
        },
    ]
    result = _complete(messages, schema=_MAPPING_SCHEMA, max_tokens=1600, lane="database")
    allowed_sources = set(headers)
    allowed_targets = {str(field.get("key") or "") for field in target_fields}
    normalized: list[dict[str, Any]] = []
    for item in list(result.data.get("mappings") or []):
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "")
        target = str(item.get("target") or "")
        transform = str(item.get("transform") or "")
        if source not in allowed_sources or target not in allowed_targets:
            continue
        if transform and transform not in _SAFE_MAPPING_TRANSFORMS:
            transform = ""
        try:
            confidence = min(1.0, max(0.0, float(item.get("confidence") or 0.0)))
        except (TypeError, ValueError):
            confidence = 0.0
        normalized.append(
            {
                "source": source,
                "target": target,
                "transform": transform,
                "confidence": confidence,
                "reason": str(item.get("reason") or "")[:300],
            }
        )
    result.data = {"mappings": normalized}
    return result


_ROW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["index", "action", "reason"],
                "properties": {
                    "index": {"type": "integer"},
                    "action": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "additionalProperties": False,
            },
        }
    },
    "additionalProperties": False,
}


def advise_row_decisions(payloads: list[dict[str, Any]]) -> LlmAssistResult:
    """Explain a bounded set of adapter decisions in one model call."""
    if not payloads:
        return LlmAssistResult()
    bounded = [
        {
            "index": index,
            "allowed_actions": sorted(_ROW_ACTIONS),
            "deterministic_action": str(item.get("deterministic_action") or ""),
            "deterministic_reason": str(item.get("deterministic_reason") or "")[:300],
            "normalized": item.get("normalized") or {},
            "before": item.get("before") or {},
            "after": item.get("after") or {},
        }
        for index, item in enumerate(payloads[: elt_row_advice_limit()])
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "You explain deterministic ETL preview decisions. Return JSON only. "
                "You may recommend new, update, or skip, but your answer is advisory and "
                "must not claim that a database write occurred."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "advise_elt_row_decisions",
                    "rules": [
                        "Prefer skip for duplicates",
                        "Update requires a visible before/after difference",
                        "Do not invent missing business values",
                    ],
                    "items": bounded,
                },
                ensure_ascii=False,
            ),
        },
    ]
    result = _complete(messages, schema=_ROW_SCHEMA, max_tokens=1600, lane="database")
    normalized: list[dict[str, Any]] = []
    for item in list(result.data.get("items") or []):
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index") or 0)
        except (TypeError, ValueError):
            continue
        action = str(item.get("action") or "")
        if index < 0 or index >= len(bounded) or action not in _ROW_ACTIONS:
            continue
        normalized.append(
            {
                "index": index,
                "action": action,
                "reason": str(item.get("reason") or "")[:300],
            }
        )
    result.data = {"items": normalized}
    return result


_BUSINESS_IMPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["rows"],
    "properties": {"rows": {"type": "array", "items": {"type": "object"}}},
}
_KNOWLEDGE_IMPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["content"],
    "properties": {"title": {"type": "string"}, "content": {"type": "string"}},
}


def _cell(value: Any) -> str:
    return str(value or "").strip()[:160]


_BUSINESS_ROW_KEYS = (
    "customer_name",
    "purchase_unit",
    "product_name",
    "quantity",
    "unit_price",
    "amount",
    "model",
    "source_sheet",
    "source_row",
    "source_range",
)


def _sheet_line_index(text: str) -> dict[tuple[str, str], set[str]]:
    """Cells under each ``# sheet:`` and ``R`` label. Hidden sheets are already omitted."""
    sheet = ""
    found: dict[tuple[str, str], set[str]] = {}
    for line in text.splitlines():
        if line.startswith("# sheet:"):
            sheet = line.removeprefix("# sheet:")
            continue
        if not sheet or not line.startswith("R"):
            continue
        token = line.split(" ", 1)[0][1:]
        if not token.isdigit():
            continue
        cells = {
            part.strip()
            for part in (line.split("|", 1)[1] if "|" in line else "").split("|")
            if part.strip()
        }
        found[(sheet, token)] = cells
    return found


def _business_rows(data: dict, cited: set[tuple[str, str]]) -> list[dict]:
    rows = []
    for item in list(data.get("rows") or [])[:100]:
        if not isinstance(item, dict):
            continue
        row = {key: _cell(item.get(key)) for key in _BUSINESS_ROW_KEYS}
        if (row["source_sheet"], row["source_row"]) not in cited:
            row["source_sheet"] = ""
            row["source_row"] = ""
            row["source_range"] = ""
        rows.append(row)
    return rows


def _coordinate_missing(row: dict) -> bool:
    return bool(row.get("product_name") or row.get("quantity")) and not (
        row.get("source_sheet") and str(row.get("source_row") or "").isdigit()
    )


def _uncited_sheets(lines: dict[tuple[str, str], set[str]], rows: list[dict]) -> list[str]:
    """Sheet labels present in the text and absent from the model's rows."""
    cited = {row.get("source_sheet") for row in rows if row.get("source_sheet")}
    sheets: list[str] = []
    for sheet, _row in lines:
        if sheet not in sheets:
            sheets.append(sheet)
    return [sheet for sheet in sheets if sheet not in cited]


def _unit_untraceable(row: dict, lines: dict[tuple[str, str], set[str]]) -> bool:
    """A purchase unit the model did not copy from the cited sheet.

    The dataset falls back to customer_name when purchase_unit is empty, so the
    value checked is the one that would be written.
    """
    from app.application.elt.candidate_table import _sheet_customer

    unit = row.get("purchase_unit") or row.get("customer_name") or ""
    sheet = row.get("source_sheet") or ""
    if not unit or not sheet:
        return False
    if unit == _sheet_customer(sheet):
        return False
    pool: set[str] = set()
    for (label, _row), cells in lines.items():
        if label == sheet:
            pool.update(cells)
    return not any(unit == item or unit in item for item in pool)


MODEL_WINDOW_CHARS = 20_000
# Each unit's answer must fit the 8192-token output in one call.
MAX_BUSINESS_UNITS = 8
_UNIT_ROWS = 60
_PREFERRED_UNIT_ROWS = 30
_UNIT_CONTEXT_ROWS = 8


def business_units(source: str) -> list[str]:
    """Bounded model inputs cut at row boundaries; nothing is dropped.

    A unit that starts inside a sheet repeats that sheet's heading and first rows
    as context, so the header customer stays visible. Rows are never split.
    """
    units: list[str] = []
    # Smaller units bound the model's response, while retaining the previous
    # eight-unit capacity for larger workbooks instead of rejecting them early.
    row_count = sum(1 for line in source.splitlines() if not line.startswith("# sheet:"))
    target_rows = min(
        _UNIT_ROWS,
        max(_PREFERRED_UNIT_ROWS, (row_count + MAX_BUSINESS_UNITS - 1) // MAX_BUSINESS_UNITS),
    )
    current: list[str] = []
    size = 0
    fresh = 0
    sheet_head: list[str] = []
    for line in source.splitlines():
        if line.startswith("# sheet:"):
            sheet_head = [line]
        elif len(sheet_head) <= _UNIT_CONTEXT_ROWS:
            sheet_head.append(line)
        if current and (size + len(line) + 1 > MODEL_WINDOW_CHARS - 2_000 or fresh >= target_rows):
            units.append("\n".join(current))
            current = list(sheet_head) if not line.startswith("# sheet:") else []
            if current and current[-1] == line:
                current.pop()
            size = sum(len(item) + 1 for item in current)
            fresh = 0
        current.append(line)
        size += len(line) + 1
        fresh += not line.startswith("# sheet:")
    if current:
        units.append("\n".join(current))
    return units


def advise_business_import(sheet_text: str) -> LlmAssistResult:
    """Import archived sheet rows on the database line, one bounded unit at a time.

    Rows from every unit are merged by source coordinate. If any unit is degraded
    the whole answer is degraded: a partial table is never offered as complete.
    """
    source = str(sheet_text or "").strip()
    if not source:
        return LlmAssistResult()
    units = business_units(source)
    if len(units) > MAX_BUSINESS_UNITS:
        return LlmAssistResult(degraded=True, degradation_code="ELT_DATABASE_INPUT_EXCEEDS_UNITS")
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    result = LlmAssistResult()
    for unit in units:
        # Repairs share this unit's budget; earlier units must not consume the
        # entire deadline before later parts of the same workbook are sent.
        deadline_token = _BUSINESS_DEADLINE.set(
            time.monotonic() + elt_llm_timeout_seconds(full_sheet=True)
        )
        try:
            result = _advise_business_unit(unit)
        finally:
            _BUSINESS_DEADLINE.reset(deadline_token)
        if not result.used_llm or result.degraded:
            return result
        for row in result.data.get("rows") or []:
            key = (
                str(row.get("source_sheet") or ""),
                str(row.get("source_row") or ""),
                str(row.get("product_name") or ""),
            )
            if key[0] and key[1] and key in seen:
                continue
            seen.add(key)
            merged.append(row)
    result.data = {"rows": merged, "units": len(units)}
    return result


def _advise_business_unit(source: str) -> LlmAssistResult:
    lines = _sheet_line_index(source)
    cited = set(lines)
    messages = [
        {
            "role": "system",
            "content": (
                "你把归档原表导入业务数据库。只返回 JSON。"
                "rows 的字段只能是 customer_name、purchase_unit、product_name、quantity、"
                "unit_price、amount、model、source_sheet、source_row、source_range。"
                "只放货品明细。表头、合计、空行不要放入。"
                "购买单位用这一张表正文里的客户，不要用列名，也不要借用其他工作表的客户。"
                "每一张表都要扫，这一本有几张就扫几张，每一行货品单独成一条，不要在第一张送货单结束后停止。"
                "行内没有购买单位时，用这一张表表头上的客户；表头也没有就留空。"
                "合计、表头、协议文字不要放入。"
                "借还台账和测算表不要导入，除非明确要求。"
                "source_sheet 必须等于某一行 # sheet: 后面的名称，source_row 必须等于该行 R 标签的整数。"
                "source_range 只在你能指出该行矩形时填写，不能就留空。对不上标签就让坐标为空，不要猜。"
                "JSON 必须是单个对象、以 rows 开头、不要 markdown 代码块、不要解释文字。"
            ),
        },
        {"role": "user", "content": source},
    ]
    call: dict[str, Any] = {
        "schema": _BUSINESS_IMPORT_SCHEMA,
        "max_tokens": 8192,
        "lane": "database",
        # A schema repair would share this call's budget and could be cut off after
        # sending; an invalid answer is a definite failure instead.
        "max_repairs": 0,
        "timeout_seconds": elt_llm_timeout_seconds(full_sheet=True),
    }
    result = _complete(messages, **call)
    rows = _business_rows(result.data, cited) if result.used_llm and not result.degraded else []
    # Up to four stored rounds. A degraded or unknown call stops; it is not sent again.
    for _round in range(3):
        if not result.used_llm or result.degraded:
            break
        missing = any(_coordinate_missing(row) for row in rows)
        borrowed = any(_unit_untraceable(row, lines) for row in rows)
        skipped = _uncited_sheets(lines, rows)
        if not missing and not borrowed and not skipped:
            break
        notes = []
        if missing:
            notes.append(
                "有货品行缺少原表坐标。只根据上文 # sheet: 和 R 标签补 source_sheet 与 source_row。"
                "对不上就留空，不要猜行号。"
            )
        if borrowed:
            notes.append(
                "有购买单位不在该行所在工作表的正文里，也不等于该表名称。"
                "改成这一张表正文里的客户，或留空。不要借用其他工作表的客户。"
            )
        if skipped:
            names = "、".join(skipped[:12])
            notes.append(
                f"这些工作表在正文里，但 rows 没有引用：{names}。"
                "是货品明细就按该表的 R 标签补上，是借还台账或测算就不要补，不要编造正文里没有的行。"
            )
        follow = [
            *messages,
            {
                "role": "assistant",
                "content": json.dumps({"rows": rows}, ensure_ascii=False)[:12_000],
            },
            {"role": "user", "content": "".join(notes) + "仍然只返回 rows。"},
        ]
        nxt = _complete(follow, **call)
        if not nxt.used_llm or nxt.degraded:
            return nxt
        fresh = _business_rows(nxt.data, cited)
        if not fresh:
            break
        result = nxt
        rows = fresh
    for row in rows:
        if _unit_untraceable(row, lines):
            row["unit_in_source"] = "0"
    if result.used_llm and not result.degraded:
        result.data = {"rows": rows}
    return result


def advise_knowledge_import(document_text: str) -> LlmAssistResult:
    """Import one archived sheet on the knowledge line only."""
    source = str(document_text or "").strip()
    if not source:
        return LlmAssistResult()
    if len(source) > MODEL_WINDOW_CHARS:
        # A summary of a prefix would read as the whole workbook; keep the archive text.
        return LlmAssistResult(degraded=True, degradation_code="ELT_KNOWLEDGE_INPUT_EXCEEDS_WINDOW")
    messages = [
        {
            "role": "system",
            "content": (
                "为归档原表生成简洁的知识检索摘要。只返回 JSON，包含 title 和 content。"
                "content 概述文档用途、工作表、客户、货品和日期等可见信息；不要编造。"
                "原始表格全部行会由系统另附，摘要不需要逐行复制、逐项列举数量或金额。"
                "摘要不超过 1500 字，避免输出过长。"
            ),
        },
        {"role": "user", "content": source},
    ]
    deadline = time.monotonic() + elt_llm_timeout_seconds(full_sheet=True)
    result = _complete(
        messages,
        schema=_KNOWLEDGE_IMPORT_SCHEMA,
        max_tokens=2048,
        lane="knowledge",
        max_repairs=0,
        timeout_seconds=deadline - time.monotonic(),
    )
    if (
        result.degradation_code == "ELT_LLM_OUTPUT_INVALID"
        and result.answer
        and time.monotonic() < deadline
    ):
        # A complete but malformed answer is a definite response, so one new
        # independently audited repair call is safe. Never retry unknown output.
        result = _complete(
            [
                *messages,
                {"role": "assistant", "content": result.answer[:4000]},
                {
                    "role": "user",
                    "content": "上次回答不是有效 JSON。请只返回一个对象，包含字符串 title 和 content，不要输出解释或 Markdown。",
                },
            ],
            schema=_KNOWLEDGE_IMPORT_SCHEMA,
            max_tokens=2048,
            lane="knowledge",
            max_repairs=0,
            timeout_seconds=max(0.0, deadline - time.monotonic()),
        )
    result.data = {
        "title": _cell(result.data.get("title")),
        "content": str(result.data.get("content") or "").strip(),
    }
    return result


__all__ = [
    "LlmAssistResult",
    "advise_business_import",
    "advise_field_mappings",
    "advise_knowledge_import",
    "advise_row_decisions",
    "advise_workbook_regions",
    "clear_elt_llm_circuit",
    "elt_llm_enabled",
    "elt_llm_mode",
    "elt_llm_timeout_seconds",
    "elt_row_advice_limit",
]
