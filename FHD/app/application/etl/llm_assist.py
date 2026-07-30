"""Software-LLM understanding and assistance for general ETL.

The model is the primary semantic engine for evidence-bound document structure
and may also suggest field mappings and explain deterministic row decisions.
It never receives authority to write business data or override target-adapter
actions.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from app.application.etl.document_field_values import normalize_header_role_value
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

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
_DOCUMENT_TYPES = frozenset(
    {
        "purchase_order",
        "delivery_note",
        "quotation",
        "invoice",
        "packing_list",
        "attendance",
        "customer_directory",
        "product_catalog",
        "shipment_ledger",
        "generic_table",
        "ignore",
    }
)
_FILE_STRUCTURES = frozenset(
    {
        "single_document",
        "one_per_sheet",
        "multiple_sections",
        "mixed_workbook",
        "summary",
        "unknown",
    }
)
_HEADER_FIELD_ROLES = frozenset(
    {
        "document_number",
        "date",
        "supplier",
        "customer",
        "currency",
        "contact",
        "address",
        "phone",
        "tax_number",
        "total_amount",
        "remark",
        "other",
    }
)
_COLUMN_ROLES = frozenset(
    {
        "line_number",
        "product_code",
        "product_name",
        "product_model",
        "specification",
        "quantity",
        "unit",
        "unit_price",
        "amount",
        "tax_rate",
        "tax_amount",
        "employee_name",
        "employee_id",
        "department",
        "attendance_date",
        "clock_in",
        "clock_out",
        "remark",
        "other",
    }
)

# ETL assistance is advisory.  A provider outage must never turn a preview
# into a sequence of long, duplicate calls (especially when an auto-detected
# delivery workbook creates the linked customer/product preview at the same
# time).  Keep this process-local on purpose: account credentials and quota
# state are not ETL business data and are never persisted with a run.
_CIRCUIT_LOCK = threading.Lock()
_CIRCUIT_OPEN_UNTIL: dict[str, tuple[float, str]] = {}
_OWNER_CALL_LOCKS: dict[str, threading.Lock] = {}
_DOCUMENT_CACHE_LOCK = threading.Lock()
_DOCUMENT_CACHE: dict[str, tuple[float, LlmAssistResult]] = {}
_DOCUMENT_FLIGHT_LOCKS: dict[str, threading.Lock] = {}
_DOCUMENT_CACHE_TTL_SECONDS = 300.0
_CHINESE_TEXT_RE = re.compile(r"[\u3400-\u9fff]")
_DOCUMENT_TYPE_LABELS = {
    "purchase_order": "采购订单",
    "delivery_note": "送货单",
    "quotation": "报价单",
    "invoice": "发票",
    "packing_list": "装箱单",
    "attendance": "考勤表",
    "customer_directory": "客户表",
    "product_catalog": "产品表",
    "shipment_ledger": "出货明细",
    "generic_table": "通用表格",
    "ignore": "不导入内容",
}


def _localized_model_text(value: Any, fallback: str) -> str:
    """Keep model-authored prose useful without exposing untranslated output."""

    text = str(value or "").strip()
    if not text:
        return fallback
    lowered = text.lower()
    if "total" in lowered and any(
        marker in lowered
        for marker in ("no total", "not present", "no explicit", "missing")
    ):
        amount_match = re.search(
            r"(?:would\s+be|equals?|is)\s*(?:[A-Z]{3}\s*)?([0-9][0-9,]*(?:\.[0-9]+)?)",
            text,
            re.I,
        )
        amount = amount_match.group(1) if amount_match else ""
        calculated = f"；按明细金额计算合计为 {amount}" if amount else ""
        return f"单据中未找到明确的合计金额单元格{calculated}，请人工核对。"
    if "complete normalized record" in lowered and "new insert" in lowered:
        return "字段完整且未发现重复记录，模型建议新增；最终仍以主数据校验结果为准。"
    if _CHINESE_TEXT_RE.search(text) and len(re.findall(r"[A-Za-z]{3,}", text)) < 3:
        return text
    return fallback


def _document_summary_text(
    value: Any,
    documents: list[dict[str, Any]],
) -> str:
    text = str(value or "").strip()
    if (
        text
        and _CHINESE_TEXT_RE.search(text)
        and len(re.findall(r"[A-Za-z]{3,}", text)) < 3
    ):
        return text[:1000]
    if not documents:
        return "未识别到可确认的业务单据，请人工检查文件结构。"
    labels = []
    for document in documents:
        label = _DOCUMENT_TYPE_LABELS.get(
            str(document.get("document_type") or ""),
            "业务单据",
        )
        if label not in labels:
            labels.append(label)
    table_count = sum(len(document.get("tables") or []) for document in documents)
    return (
        f"识别为{'、'.join(labels)}，共 {len(documents)} 张单；"
        f"已定位单据头和 {table_count} 个明细表，等待人工确认。"
    )


@dataclass(slots=True)
class LlmAssistResult:
    used_llm: bool = False
    degraded: bool = False
    degradation_code: str = ""
    model: str = ""
    billing: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)

    def public_metadata(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "used_llm": self.used_llm,
            "advisory_only": True,
            "degraded": self.degraded,
        }
        if self.degradation_code:
            result["degradation_code"] = self.degradation_code
        if self.model:
            result["model"] = self.model
        if self.billing:
            result["billing"] = dict(self.billing)
        return result


def etl_llm_mode() -> str:
    raw = str(os.environ.get("FHD_ETL_LLM") or "auto").strip().lower()
    if raw in {"0", "false", "no", "off", "disabled"}:
        return "off"
    if raw in {"1", "true", "yes", "on", "enabled"}:
        return "on"
    return "auto"


def etl_llm_timeout_seconds() -> float:
    """Return the hard latency budget for evidence-bound ETL understanding.

    Account-backed model routing includes remote route resolution, billing and
    structured generation.  A six-second budget is shorter than a normal
    successful account request, so it silently removes the semantic stage from
    real previews.  Keep the budget bounded and configurable while allowing the
    primary document-understanding request enough time to finish.
    """

    raw = str(os.environ.get("FHD_ETL_LLM_TIMEOUT") or "30").strip()
    try:
        return min(90.0, max(3.0, float(raw)))
    except ValueError:
        return 30.0


def etl_document_timeout_seconds(evidence: dict[str, Any]) -> float:
    """Return a bounded budget for one workbook-understanding batch.

    Account-backed routing has a material fixed latency before generation
    starts.  A sheet-count-only budget made a compact four-sheet batch time out
    sooner than the previous whole-workbook request even though the batch was
    healthy.  Keep a production-observed floor, then add bounded evidence cost.
    """

    sheets = len(evidence.get("sheets") or [])
    cells = len(evidence.get("cell_index") or {})
    computed = min(
        180.0,
        max(
            120.0,
            105.0 + max(0, sheets - 1) * 5.0 + min(30.0, cells / 75.0),
        ),
    )
    raw = str(os.environ.get("FHD_ETL_LLM_DOCUMENT_TIMEOUT") or computed).strip()
    try:
        return min(180.0, max(10.0, float(raw)))
    except ValueError:
        return computed


def etl_row_advice_limit() -> int:
    raw = str(os.environ.get("FHD_ETL_LLM_ROW_ADVICE_LIMIT") or "20").strip()
    try:
        return min(100, max(0, int(raw)))
    except ValueError:
        return 20


def _degradation_code(exc: BaseException) -> str:
    if type(exc).__name__ == "StructuredOutputError":
        return "ETL_LLM_OUTPUT_INVALID"
    message = str(exc).lower()
    if "quota exhausted" in message or "额度" in message or "429" in message:
        return "ETL_LLM_QUOTA_EXHAUSTED"
    return "ETL_LLM_UNAVAILABLE"


def _circuit_key() -> str:
    """Scope degradation to the current software-account owner when present."""

    try:
        from app.application.etl.llm_session_provider import current_etl_llm_owner

        owner_user_id = current_etl_llm_owner()
    except Exception:  # noqa: BLE001 - assist scoping must not block preview
        owner_user_id = None
    return f"owner:{owner_user_id}" if owner_user_id is not None else "process"


def _circuit_cooldown_seconds(degradation_code: str) -> float:
    """Use a longer owner cooldown for a confirmed quota exhaustion."""

    env_name = (
        "FHD_ETL_LLM_QUOTA_COOLDOWN_SECONDS"
        if degradation_code == "ETL_LLM_QUOTA_EXHAUSTED"
        else "FHD_ETL_LLM_FAILURE_COOLDOWN_SECONDS"
    )
    default = 300.0 if degradation_code == "ETL_LLM_QUOTA_EXHAUSTED" else 5.0
    raw = str(os.environ.get(env_name) or default).strip()
    try:
        return min(3600.0, max(1.0, float(raw)))
    except ValueError:
        return default


def _circuit_degradation(key: str) -> str:
    now = time.monotonic()
    with _CIRCUIT_LOCK:
        state = _CIRCUIT_OPEN_UNTIL.get(key)
        if state is None:
            return ""
        expires_at, degradation_code = state
        if expires_at <= now:
            _CIRCUIT_OPEN_UNTIL.pop(key, None)
            return ""
        return degradation_code


def _open_circuit(key: str, degradation_code: str) -> None:
    with _CIRCUIT_LOCK:
        _CIRCUIT_OPEN_UNTIL[key] = (
            time.monotonic() + _circuit_cooldown_seconds(degradation_code),
            degradation_code,
        )


def _owner_call_lock(key: str) -> threading.Lock:
    with _CIRCUIT_LOCK:
        lock = _OWNER_CALL_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _OWNER_CALL_LOCKS[key] = lock
        return lock


def _document_cache_key(evidence: dict[str, Any]) -> str:
    evidence_hash = str(evidence.get("evidence_hash") or "").strip()
    if not evidence_hash:
        evidence_hash = hashlib.sha256(
            json.dumps(
                evidence,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
    return f"{_circuit_key()}|{evidence_hash}"


def _document_flight_lock(key: str) -> threading.Lock:
    now = time.monotonic()
    with _DOCUMENT_CACHE_LOCK:
        for expired_key, (expires_at, _result) in list(_DOCUMENT_CACHE.items()):
            if expires_at <= now:
                _DOCUMENT_CACHE.pop(expired_key, None)
                stale_lock = _DOCUMENT_FLIGHT_LOCKS.get(expired_key)
                if stale_lock is not None and not stale_lock.locked():
                    _DOCUMENT_FLIGHT_LOCKS.pop(expired_key, None)
        lock = _DOCUMENT_FLIGHT_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _DOCUMENT_FLIGHT_LOCKS[key] = lock
        return lock


def _cached_document_result(key: str) -> LlmAssistResult | None:
    with _DOCUMENT_CACHE_LOCK:
        cached = _DOCUMENT_CACHE.get(key)
        if cached is None:
            return None
        expires_at, result = cached
        if expires_at <= time.monotonic():
            _DOCUMENT_CACHE.pop(key, None)
            return None
        reused = copy.deepcopy(result)
    reused.billing = {**reused.billing, "reused": True}
    return reused


def _cache_document_result(key: str, result: LlmAssistResult) -> None:
    with _DOCUMENT_CACHE_LOCK:
        _DOCUMENT_CACHE[key] = (
            time.monotonic() + _DOCUMENT_CACHE_TTL_SECONDS,
            copy.deepcopy(result),
        )


def clear_etl_llm_circuit(*, owner_user_id: int | None = None) -> None:
    """Clear transient assist degradation state (primarily for lifecycle/tests).

    This contains only process-local timing/error codes.  It never clears an
    ETL run, a template, an upload, or any account credential.
    """

    with _CIRCUIT_LOCK:
        if owner_user_id is None:
            _CIRCUIT_OPEN_UNTIL.clear()
        else:
            _CIRCUIT_OPEN_UNTIL.pop(f"owner:{int(owner_user_id)}", None)
    cache_prefix = None if owner_user_id is None else f"owner:{int(owner_user_id)}|"
    with _DOCUMENT_CACHE_LOCK:
        if cache_prefix is None:
            _DOCUMENT_CACHE.clear()
            for key, lock in list(_DOCUMENT_FLIGHT_LOCKS.items()):
                if not lock.locked():
                    _DOCUMENT_FLIGHT_LOCKS.pop(key, None)
        else:
            for key in list(_DOCUMENT_CACHE):
                if key.startswith(cache_prefix):
                    _DOCUMENT_CACHE.pop(key, None)
            for key, lock in list(_DOCUMENT_FLIGHT_LOCKS.items()):
                if key.startswith(cache_prefix) and not lock.locked():
                    _DOCUMENT_FLIGHT_LOCKS.pop(key, None)


def _bounded_structured_completion(
    messages: list[dict[str, str]],
    *,
    schema: dict[str, Any],
    max_tokens: int,
    timeout_seconds: float,
    conversation_service: Any | None,
    provider: Any | None,
    max_repairs: int,
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
                max_repairs=max_repairs,
                timeout_seconds=timeout_seconds,
                profile="etl",
                conversation_service=conversation_service,
                provider=provider,
            )
        except BaseException as exc:  # noqa: BLE001 - transported to preview fallback
            box["error"] = exc

    worker = threading.Thread(
        target=invoke,
        name="etl-llm-assist",
        daemon=True,
    )
    worker.start()
    # ``complete_structured_sync`` owns cooperative asyncio cancellation.  The
    # short grace lets httpx close sockets before this outer safety deadline.
    cancellation_grace = min(1.0, max(0.05, timeout_seconds * 0.05))
    worker.join(timeout=timeout_seconds + cancellation_grace)
    if worker.is_alive():
        raise TimeoutError("ETL LLM assist timed out")
    if "error" in box:
        raise box["error"]
    if "result" not in box:
        raise RuntimeError("ETL LLM assist returned no result")
    return box["result"]


def _active_software_llm() -> tuple[bool, Any | None, Any | None]:
    """Resolve the current user's software-account LLM, then app-wide providers."""
    try:
        from app.application.etl.llm_session_provider import current_owner_market_provider

        market_provider = current_owner_market_provider(timeout_seconds=etl_llm_timeout_seconds())
        if market_provider is not None:
            return True, None, market_provider
        from app.infrastructure.llm.providers.registry import get_active_provider

        if get_active_provider(profile="etl") is not None:
            return True, None, None
        from app.services.ai_conversation_service import get_ai_conversation_service

        service = get_ai_conversation_service()
        if get_active_provider(conversation_service=service, profile="etl") is not None:
            return True, service, None
        return False, None, None
    except RECOVERABLE_ERRORS:
        return False, None, None


def etl_llm_enabled() -> bool:
    mode = etl_llm_mode()
    if mode == "off":
        return False
    configured, _service, _provider = _active_software_llm()
    return configured if mode == "auto" else True


def _complete(
    messages: list[dict[str, str]],
    *,
    schema: dict[str, Any],
    max_tokens: int,
    timeout_seconds: float | None = None,
    max_repairs: int = 0,
) -> LlmAssistResult:
    mode = etl_llm_mode()
    if mode == "off":
        return LlmAssistResult()
    circuit_key = _circuit_key()
    circuit_degradation = _circuit_degradation(circuit_key)
    if circuit_degradation:
        return LlmAssistResult(
            used_llm=False,
            degraded=True,
            degradation_code=circuit_degradation,
        )

    # The auto shipment preview can spawn a linked customer/product preview.
    # Serializing calls for one software account lets the first observed quota
    # or timeout stop every later advisory stage instead of multiplying it.
    with _owner_call_lock(circuit_key):
        circuit_degradation = _circuit_degradation(circuit_key)
        if circuit_degradation:
            return LlmAssistResult(
                used_llm=False,
                degraded=True,
                degradation_code=circuit_degradation,
            )
        configured, conversation_service, provider = _active_software_llm()
        if not configured:
            return LlmAssistResult(
                used_llm=False,
                degraded=mode == "on",
                degradation_code="ETL_LLM_UNAVAILABLE" if mode == "on" else "",
            )
        timeout_seconds = (
            etl_llm_timeout_seconds() if timeout_seconds is None else float(timeout_seconds)
        )
        if provider is not None and hasattr(provider, "with_timeout"):
            provider = provider.with_timeout(timeout_seconds)
        try:
            result = _bounded_structured_completion(
                messages,
                schema=schema,
                max_tokens=max_tokens,
                timeout_seconds=timeout_seconds,
                conversation_service=conversation_service,
                provider=provider,
                max_repairs=max_repairs,
            )
            return LlmAssistResult(
                used_llm=True,
                model=str(result.model or ""),
                billing=dict(result.billing or {}),
                data=dict(result.data),
            )
        except Exception as exc:  # noqa: BLE001 - LLM failure must never own ETL execution
            degradation_code = _degradation_code(exc)
            _open_circuit(circuit_key, degradation_code)
            logger.info(
                "general etl llm assist degraded (%s): %s details=%s",
                degradation_code,
                type(exc).__name__,
                list(getattr(exc, "last_errors", []) or [])[:3],
            )
            return LlmAssistResult(
                used_llm=True,
                degraded=True,
                degradation_code=degradation_code,
            )


_DOCUMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["file_structure", "summary", "documents"],
    "properties": {
        "file_structure": {"type": "string"},
        "summary": {"type": "string"},
        "documents": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "document_id",
                    "document_type",
                    "sheet",
                    "title_cell_ids",
                    "header_fields",
                    "tables",
                    "total_amount_cell_id",
                    "confidence",
                    "requires_review",
                    "issues",
                ],
                "properties": {
                    "document_id": {"type": "string"},
                    "document_type": {"type": "string"},
                    "sheet": {"type": "string"},
                    "title_cell_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "header_fields": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": [
                                "role",
                                "label_cell_id",
                                "value_cell_id",
                                "reason",
                            ],
                            "properties": {
                                "role": {"type": "string"},
                                "label_cell_id": {"type": "string"},
                                "value_cell_id": {"type": "string"},
                                "reason": {"type": "string"},
                            },
                            "additionalProperties": False,
                        },
                    },
                    "tables": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": [
                                "header_start_row",
                                "header_end_row",
                                "data_start_row",
                                "data_end_row",
                                "first_column",
                                "last_column",
                                "columns",
                            ],
                            "properties": {
                                "header_start_row": {"type": "integer"},
                                "header_end_row": {"type": "integer"},
                                "data_start_row": {"type": "integer"},
                                "data_end_row": {"type": "integer"},
                                "first_column": {"type": "integer"},
                                "last_column": {"type": "integer"},
                                "columns": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "required": [
                                            "column",
                                            "role",
                                            "header_cell_id",
                                            "reason",
                                        ],
                                        "properties": {
                                            "column": {"type": "integer"},
                                            "role": {"type": "string"},
                                            "header_cell_id": {"type": "string"},
                                            "reason": {"type": "string"},
                                        },
                                        "additionalProperties": False,
                                    },
                                },
                            },
                            "additionalProperties": False,
                        },
                    },
                    "total_amount_cell_id": {"type": "string"},
                    "confidence": {"type": "number"},
                    "requires_review": {"type": "boolean"},
                    "issues": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
}


def _resolved_inline_value(
    label_item: dict[str, Any],
    value_item: dict[str, Any],
    *,
    role: str = "",
) -> Any:
    value = value_item.get("value")
    if label_item.get("id") != value_item.get("id"):
        return normalize_header_role_value(
            role,
            value,
            label=label_item.get("text"),
        )
    text = str(value_item.get("text") or "")
    return normalize_header_role_value(role, value, label=text)


def _compact_document_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Keep every sheet visible while removing prompt-shape duplication."""

    sheets = list(evidence.get("sheets") or [])
    if not sheets:
        return {"cell_legend": ["cell_id", "text", "value_type"], "sheets": []}
    global_cell_budget = 960
    per_sheet_budget = min(160, max(48, global_cell_budget // len(sheets)))
    table_by_sheet = {
        str(item.get("sheet") or ""): item
        for item in evidence.get("table_candidates") or []
        if isinstance(item, dict)
    }
    compact_sheets: list[dict[str, Any]] = []
    supplied_cell_ids: set[str] = set()
    for sheet in sheets:
        sheet_name = str(sheet.get("name") or "")[:160]
        rows = list(sheet.get("rows") or [])
        candidate = table_by_sheet.get(sheet_name) or {}
        header_end = int(candidate.get("header_end_row") or 0)
        data_start = int(candidate.get("data_start_row") or header_end + 1)
        priority_rows: list[int] = []
        priority_rows.extend(
            int(row.get("row") or 0)
            for row in rows
            if int(row.get("row") or 0) <= max(header_end, 6)
        )
        priority_rows.extend(range(data_start, data_start + 3))
        priority_rows.extend(
            int(row.get("row") or 0)
            for row in rows
            if any(
                marker in " ".join(
                    str(cell.get("text") or "").lower()
                    for cell in row.get("cells") or []
                )
                for marker in ("合计", "总计", "小计", "备注", "total", "subtotal", "remark")
            )
        )
        priority_rows.extend(
            int(row.get("row") or 0)
            for row in rows[-2:]
        )
        priority_rows.extend(int(row.get("row") or 0) for row in rows)
        row_by_number = {int(row.get("row") or 0): row for row in rows}
        selected_rows: dict[int, list[list[str]]] = {}
        used_cells = 0
        for row_number in dict.fromkeys(priority_rows):
            row = row_by_number.get(row_number)
            if row is None or used_cells >= per_sheet_budget:
                continue
            compact_cells: list[list[str]] = []
            for cell in row.get("cells") or []:
                if used_cells >= per_sheet_budget:
                    break
                cell_id = str(cell.get("id") or "")
                if not cell_id:
                    continue
                compact_cells.append(
                    [
                        cell_id,
                        str(cell.get("text") or "")[:300],
                        str(cell.get("value_type") or ""),
                    ]
                )
                supplied_cell_ids.add(cell_id)
                used_cells += 1
            if compact_cells:
                selected_rows[row_number] = compact_cells
        compact_sheets.append(
            {
                "name": sheet_name,
                "size": [
                    int(sheet.get("max_row") or 0),
                    int(sheet.get("max_column") or 0),
                ],
                "rows": [
                    [row_number, selected_rows[row_number]]
                    for row_number in sorted(selected_rows)
                ],
            }
        )

    compact_tables = [
        [
            str(item.get("candidate_id") or ""),
            str(item.get("sheet") or ""),
            int(item.get("header_start_row") or 0),
            int(item.get("header_end_row") or 0),
            int(item.get("data_start_row") or 0),
            int(item.get("data_end_row") or 0),
            int(item.get("first_column") or 0),
            int(item.get("last_column") or 0),
            list(item.get("headers") or []),
            round(float(item.get("confidence") or 0.0), 3),
        ]
        for item in evidence.get("table_candidates") or []
        if isinstance(item, dict)
    ]
    key_value_counts: dict[str, int] = {}
    compact_key_values = []
    for item in evidence.get("key_value_candidates") or []:
        if not isinstance(item, dict):
            continue
        sheet_name = str(item.get("sheet") or "")
        if key_value_counts.get(sheet_name, 0) >= 16:
            continue
        label_id = str(item.get("label_cell_id") or "")
        value_id = str(item.get("value_cell_id") or "")
        # Candidate IDs are evidence too; prefer those also visible in the
        # compact row sample and keep a small per-sheet allowance otherwise.
        if (
            label_id not in supplied_cell_ids
            and value_id not in supplied_cell_ids
            and key_value_counts.get(sheet_name, 0) >= 8
        ):
            continue
        compact_key_values.append(
            [
                sheet_name,
                str(item.get("label") or "")[:120],
                item.get("value"),
                label_id,
                value_id,
            ]
        )
        key_value_counts[sheet_name] = key_value_counts.get(sheet_name, 0) + 1
    return {
        "cell_legend": ["cell_id", "text", "value_type"],
        "sheet_legend": ["row_number", "cells"],
        "table_candidate_legend": [
            "candidate_id",
            "sheet",
            "header_start",
            "header_end",
            "data_start",
            "data_end",
            "first_column",
            "last_column",
            "headers",
            "confidence",
        ],
        "key_value_legend": ["sheet", "label", "value", "label_cell_id", "value_cell_id"],
        "sheets": compact_sheets,
        "table_candidates": compact_tables,
        "key_value_candidates": compact_key_values,
    }


def _document_evidence_batches(
    evidence: dict[str, Any],
    *,
    batch_size: int = 4,
) -> list[dict[str, Any]]:
    """Split large workbooks by sheet so model output cannot truncate globally."""

    sheets = list(evidence.get("sheets") or [])
    if len(sheets) <= batch_size:
        return [evidence]
    batches: list[dict[str, Any]] = []
    for offset in range(0, len(sheets), batch_size):
        batch_sheets = sheets[offset : offset + batch_size]
        sheet_names = {str(sheet.get("name") or "") for sheet in batch_sheets}
        batches.append(
            {
                **evidence,
                "sheets": batch_sheets,
                "cell_index": {
                    cell_id: item
                    for cell_id, item in (evidence.get("cell_index") or {}).items()
                    if str(item.get("sheet") or "") in sheet_names
                },
                "table_candidates": [
                    item
                    for item in evidence.get("table_candidates") or []
                    if str(item.get("sheet") or "") in sheet_names
                ],
                "key_value_candidates": [
                    item
                    for item in evidence.get("key_value_candidates") or []
                    if str(item.get("sheet") or "") in sheet_names
                ],
            }
        )
    return batches


def _document_prompt_messages(
    evidence: dict[str, Any],
    *,
    batch_index: int,
    batch_count: int,
) -> list[dict[str, str]]:
    compact_evidence = _compact_document_evidence(evidence)
    return [
        {
            "role": "system",
            "content": (
                "You are the primary semantic document-understanding stage of an enterprise ETL. "
                "Analyze every supplied sheet as a human operator would: identify business objects, "
                "count separate documents, locate document headers, detail-table boundaries, totals "
                "and notes, and assign semantic column roles using labels, types, examples, positions "
                "and relationships. Return JSON only. Every cell reference must be an exact supplied "
                "cell ID. Never invent a cell, value, document, row range or database match. Mark "
                "ambiguity and mixed meanings as requires_review. For ignore or summary-only sheets, "
                "use empty header_fields and tables instead of describing every column. All "
                "human-readable summary, issue and reason fields must use Simplified Chinese; enum "
                "identifiers and cell IDs must retain their allowed values."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "understand_business_workbook_batch",
                    "file_name": str(evidence.get("file_name") or "")[:240],
                    "batch": {"index": batch_index, "count": batch_count},
                    "allowed_file_structures": sorted(_FILE_STRUCTURES),
                    "allowed_document_types": sorted(_DOCUMENT_TYPES),
                    "allowed_header_roles": sorted(_HEADER_FIELD_ROLES),
                    "allowed_column_roles": sorted(_COLUMN_ROLES),
                    "rules": [
                        "Find every independent document, including multiple sections on one sheet.",
                        "A summary sheet is not a line-item document unless it contains its own records.",
                        "Separate document header fields from detail-table columns.",
                        "Exclude totals, signatures and notes from data row ranges when possible.",
                        "Use requires_review when business type, boundary or field meaning is ambiguous.",
                        "Do not decide database writes or master-data matches.",
                    ],
                    "evidence_format": (
                        "Compact arrays use the supplied legends. Cell IDs encode sheet, row "
                        "and column; use those exact IDs in every output reference."
                    ),
                    "workbook_evidence": compact_evidence,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        },
    ]


def _merged_file_structure(
    structures: list[str],
    *,
    sheet_count: int,
    document_count: int,
) -> str:
    if "mixed_workbook" in structures:
        return "mixed_workbook"
    if document_count == 1:
        return "single_document"
    if document_count == sheet_count and sheet_count > 1:
        return "one_per_sheet"
    if document_count > sheet_count:
        return "multiple_sections"
    if document_count > 1:
        return "mixed_workbook"
    return "unknown"


def _advise_document_understanding_uncached(
    evidence: dict[str, Any],
    *,
    progress_callback: Callable[[int, int], None] | None = None,
) -> LlmAssistResult:
    """Build a business-document plan whose references are all server-verifiable."""

    sheets = list(evidence.get("sheets") or [])
    cell_index = evidence.get("cell_index") or {}
    if not sheets or not cell_index:
        return LlmAssistResult()
    batches = _document_evidence_batches(evidence)
    batch_results: list[LlmAssistResult] = []
    raw_documents: list[dict[str, Any]] = []
    batch_structures: list[str] = []
    for batch_index, batch in enumerate(batches, start=1):
        logger.info(
            "general etl document understanding batch %s/%s sheets=%s",
            batch_index,
            len(batches),
            len(batch.get("sheets") or []),
        )
        batch_result = _complete(
            _document_prompt_messages(
                batch,
                batch_index=batch_index,
                batch_count=len(batches),
            ),
            schema=_DOCUMENT_SCHEMA,
            max_tokens=5000,
            timeout_seconds=etl_document_timeout_seconds(batch),
            # Document structure is the semantic primary stage. A single
            # schema-repair attempt is cheaper and safer than degrading every
            # Sheet because one model response missed the contract.
            max_repairs=1,
        )
        batch_results.append(batch_result)
        if not batch_result.degraded:
            raw_documents.extend(
                item
                for item in list(batch_result.data.get("documents") or [])
                if isinstance(item, dict)
            )
            batch_structures.append(str(batch_result.data.get("file_structure") or ""))
        if progress_callback is not None:
            progress_callback(batch_index, len(batches))
    result = LlmAssistResult(
        used_llm=any(item.used_llm for item in batch_results),
        degraded=any(item.degraded for item in batch_results),
        degradation_code=next(
            (
                item.degradation_code
                for item in batch_results
                if item.degradation_code
            ),
            "",
        ),
        model=next((item.model for item in batch_results if item.model), ""),
        billing={
            "batch_count": len(batch_results),
            "batches": [item.billing for item in batch_results if item.billing],
        },
        data={
            "file_structure": _merged_file_structure(
                batch_structures,
                sheet_count=len(sheets),
                document_count=len(raw_documents),
            ),
            "summary": "",
            "documents": raw_documents,
        },
    )
    valid_sheets = {str(sheet.get("name") or ""): sheet for sheet in evidence.get("sheets") or []}
    normalized_documents: list[dict[str, Any]] = []
    seen_document_ids: set[str] = set()
    for raw_document in list(result.data.get("documents") or [])[:80]:
        if not isinstance(raw_document, dict):
            continue
        document_id = str(raw_document.get("document_id") or "")[:120]
        document_type = str(raw_document.get("document_type") or "")
        sheet_name = str(raw_document.get("sheet") or "")
        if (
            not document_id
            or document_type not in _DOCUMENT_TYPES
            or sheet_name not in valid_sheets
        ):
            continue
        if document_id in seen_document_ids:
            document_id = f"{sheet_name}:{document_id}"[:120]
        if document_id in seen_document_ids:
            continue
        seen_document_ids.add(document_id)
        sheet = valid_sheets[sheet_name]
        max_row = int(sheet.get("max_row") or 0)
        max_column = int(sheet.get("max_column") or 0)
        title_cells = [
            cell_index[cell_id]
            for cell_id in list(raw_document.get("title_cell_ids") or [])[:10]
            if cell_id in cell_index and cell_index[cell_id].get("sheet") == sheet_name
        ]
        header_fields = []
        for raw_field in list(raw_document.get("header_fields") or [])[:80]:
            if not isinstance(raw_field, dict):
                continue
            role = str(raw_field.get("role") or "")
            label_id = str(raw_field.get("label_cell_id") or "")
            value_id = str(raw_field.get("value_cell_id") or "")
            label_item = cell_index.get(label_id)
            value_item = cell_index.get(value_id)
            if (
                role not in _HEADER_FIELD_ROLES
                or not label_item
                or not value_item
                or label_item.get("sheet") != sheet_name
                or value_item.get("sheet") != sheet_name
            ):
                continue
            header_fields.append(
                {
                    "role": role,
                    "label": str(label_item.get("text") or "")[:160],
                    "value": _resolved_inline_value(
                        label_item,
                        value_item,
                        role=role,
                    ),
                    "label_cell_id": label_id,
                    "value_cell_id": value_id,
                    "label_coordinate": label_item.get("coordinate"),
                    "value_coordinate": value_item.get("coordinate"),
                    "reason": _localized_model_text(
                        raw_field.get("reason"),
                        "模型根据单元格标签、位置和样例判定该字段。",
                    )[:300],
                }
            )
        inferred_roles = (
            "document_number",
            "date",
            "supplier",
            "customer",
            "currency",
            "contact",
            "phone",
        )
        existing_roles = {
            str(item.get("role") or "")
            for item in header_fields
            if isinstance(item, dict)
        }
        referenced_items = []
        seen_item_ids = set()
        for item in header_fields:
            for key in ("label_cell_id", "value_cell_id"):
                cell_id = str(item.get(key) or "")
                cell_item = cell_index.get(cell_id)
                if (
                    cell_item
                    and cell_item.get("sheet") == sheet_name
                    and cell_id not in seen_item_ids
                ):
                    seen_item_ids.add(cell_id)
                    referenced_items.append(cell_item)
        for inferred_role in inferred_roles:
            if inferred_role in existing_roles:
                continue
            for cell_item in referenced_items:
                cell_text = str(cell_item.get("text") or "")
                inferred_value = normalize_header_role_value(
                    inferred_role,
                    cell_item.get("value"),
                    label=cell_text,
                )
                if (
                    inferred_value in (None, "")
                    or str(inferred_value).strip() == str(cell_item.get("value") or "").strip()
                ):
                    continue
                header_fields.append(
                    {
                        "role": inferred_role,
                        "label": cell_text[:160],
                        "value": inferred_value,
                        "label_cell_id": cell_item.get("id"),
                        "value_cell_id": cell_item.get("id"),
                        "label_coordinate": cell_item.get("coordinate"),
                        "value_coordinate": cell_item.get("coordinate"),
                        "reason": "由同一单据头单元格中的明确标签确定性补全。",
                    }
                )
                existing_roles.add(inferred_role)
                break
        tables = []
        for raw_table in list(raw_document.get("tables") or [])[:20]:
            if not isinstance(raw_table, dict):
                continue
            try:
                header_start = int(raw_table.get("header_start_row"))
                header_end = int(raw_table.get("header_end_row"))
                data_start = int(raw_table.get("data_start_row"))
                data_end = int(raw_table.get("data_end_row"))
                first_column = int(raw_table.get("first_column"))
                last_column = int(raw_table.get("last_column"))
            except (TypeError, ValueError):
                continue
            if not (
                1 <= header_start <= header_end < data_start <= data_end <= max_row
                and 1 <= first_column <= last_column <= max_column
            ):
                continue
            columns = []
            for raw_column in list(raw_table.get("columns") or [])[:80]:
                if not isinstance(raw_column, dict):
                    continue
                try:
                    column = int(raw_column.get("column"))
                except (TypeError, ValueError):
                    continue
                role = str(raw_column.get("role") or "")
                header_id = str(raw_column.get("header_cell_id") or "")
                header_item = cell_index.get(header_id)
                if (
                    role not in _COLUMN_ROLES
                    or column < first_column
                    or column > last_column
                    or not header_item
                    or header_item.get("sheet") != sheet_name
                    or int(header_item.get("row") or 0) < header_start
                    or int(header_item.get("row") or 0) > header_end
                    or int(header_item.get("column") or 0) != column
                ):
                    continue
                columns.append(
                    {
                        "column": column,
                        "role": role,
                        "header": str(header_item.get("text") or "")[:160],
                        "header_cell_id": header_id,
                        "header_coordinate": header_item.get("coordinate"),
                        "reason": _localized_model_text(
                            raw_column.get("reason"),
                            "模型根据表头、数据类型和列值关系判定该字段。",
                        )[:300],
                    }
                )
            tables.append(
                {
                    "header_start_row": header_start,
                    "header_end_row": header_end,
                    "data_start_row": data_start,
                    "data_end_row": data_end,
                    "first_column": first_column,
                    "last_column": last_column,
                    "columns": columns,
                }
            )
        total_id = str(raw_document.get("total_amount_cell_id") or "")
        total_item = cell_index.get(total_id)
        if not total_item or total_item.get("sheet") != sheet_name:
            total_id = ""
            total_item = {}
        try:
            confidence = min(1.0, max(0.0, float(raw_document.get("confidence") or 0.0)))
        except (TypeError, ValueError):
            confidence = 0.0
        normalized_documents.append(
            {
                "document_id": document_id,
                "document_type": document_type,
                "sheet": sheet_name,
                "title_cells": [
                    {
                        "cell_id": item.get("id"),
                        "coordinate": item.get("coordinate"),
                        "text": item.get("text"),
                    }
                    for item in title_cells
                ],
                "header_fields": header_fields,
                "tables": tables,
                "total_amount_cell_id": total_id,
                "total_amount_coordinate": total_item.get("coordinate", ""),
                "total_amount": total_item.get("value"),
                "confidence": confidence,
                "requires_review": bool(raw_document.get("requires_review")) or not tables,
                "issues": [
                    {
                        "code": "ETL_DOCUMENT_UNDERSTANDING_REVIEW",
                        "message": _localized_model_text(
                            issue,
                            "模型发现单据结构存在需要人工确认的问题，请结合来源单元格复核。",
                        )[:500],
                    }
                    for issue in list(raw_document.get("issues") or [])[:20]
                    if str(issue).strip()
                ],
            }
        )
    file_structure = str(result.data.get("file_structure") or "")
    result.data = {
        "file_structure": file_structure if file_structure in _FILE_STRUCTURES else "unknown",
        "summary": _document_summary_text(
            result.data.get("summary"),
            normalized_documents,
        ),
        "documents": normalized_documents,
    }
    return result


def advise_document_understanding(
    evidence: dict[str, Any],
    *,
    progress_callback: Callable[[int, int], None] | None = None,
) -> LlmAssistResult:
    """Share one successful semantic analysis across linked target previews."""

    if not evidence.get("sheets") or not evidence.get("cell_index"):
        return LlmAssistResult()
    cache_key = _document_cache_key(evidence)
    cached = _cached_document_result(cache_key)
    if cached is not None:
        if progress_callback is not None:
            batch_count = max(1, int(cached.billing.get("batch_count") or 1))
            progress_callback(batch_count, batch_count)
        logger.info(
            "general etl document understanding cache hit evidence=%s",
            cache_key.rsplit("|", 1)[-1][:12],
        )
        return cached
    with _document_flight_lock(cache_key):
        cached = _cached_document_result(cache_key)
        if cached is not None:
            if progress_callback is not None:
                batch_count = max(1, int(cached.billing.get("batch_count") or 1))
                progress_callback(batch_count, batch_count)
            logger.info(
                "general etl document understanding shared result evidence=%s",
                cache_key.rsplit("|", 1)[-1][:12],
            )
            return cached
        result = _advise_document_understanding_uncached(
            evidence,
            progress_callback=progress_callback,
        )
        if result.used_llm and not result.degraded and result.data.get("documents"):
            _cache_document_result(cache_key, result)
        return result


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
    result = _complete(messages, schema=_REGION_SCHEMA, max_tokens=1800)
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
                "Allowed transforms are empty, trim, number, and date. Write every "
                "human-readable reason in Simplified Chinese."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "suggest_etl_field_mappings",
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
    result = _complete(messages, schema=_MAPPING_SCHEMA, max_tokens=1600)
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
                "reason": _localized_model_text(
                    item.get("reason"),
                    "模型根据列名、样例值和目标字段语义建议此映射。",
                )[:300],
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
        for index, item in enumerate(payloads[: etl_row_advice_limit()])
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "You explain deterministic ETL preview decisions. Return JSON only. "
                "You may recommend new, update, or skip, but your answer is advisory and "
                "must not claim that a database write occurred. Write every human-readable "
                "reason in Simplified Chinese."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "advise_etl_row_decisions",
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
    result = _complete(messages, schema=_ROW_SCHEMA, max_tokens=1600)
    normalized: list[dict[str, Any]] = []
    for item in list(result.data.get("items") or []):
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        action = str(item.get("action") or "")
        if index < 0 or index >= len(bounded) or action not in _ROW_ACTIONS:
            continue
        normalized.append(
            {
                "index": index,
                "action": action,
                "reason": _localized_model_text(
                    item.get("reason"),
                    {
                        "new": "模型建议新增；最终仍以主数据和重复数据校验结果为准。",
                        "update": "模型建议更新；最终仍以变更差异和允许更新字段为准。",
                        "skip": "模型建议跳过；最终仍以重复数据和业务规则校验结果为准。",
                    }[action],
                )[:300],
            }
        )
    result.data = {"items": normalized}
    return result


__all__ = [
    "LlmAssistResult",
    "advise_document_understanding",
    "advise_field_mappings",
    "advise_row_decisions",
    "advise_workbook_regions",
    "clear_etl_llm_circuit",
    "etl_document_timeout_seconds",
    "etl_llm_enabled",
    "etl_llm_mode",
    "etl_llm_timeout_seconds",
    "etl_row_advice_limit",
]
