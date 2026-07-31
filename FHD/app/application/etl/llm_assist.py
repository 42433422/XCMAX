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
        marker in lowered for marker in ("no total", "not present", "no explicit", "missing")
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
    if text and _CHINESE_TEXT_RE.search(text) and len(re.findall(r"[A-Za-z]{3,}", text)) < 3:
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


from app.application.etl.llm_runtime import (
    _cache_document_result,
    _cached_document_result,
    _circuit_cooldown_seconds,
    _circuit_degradation,
    _circuit_key,
    _degradation_code,
    _document_cache_key,
    _document_flight_lock,
    _open_circuit,
    _owner_call_lock,
    clear_etl_llm_circuit,
    etl_document_timeout_seconds,
    etl_llm_mode,
    etl_llm_timeout_seconds,
    etl_row_advice_limit,
)


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


from app.application.etl.llm_document_advice import (
    _advise_document_understanding_uncached,
    _merged_file_structure,
    advise_document_understanding,
)
from app.application.etl.llm_document_evidence import (
    _DOCUMENT_SCHEMA,
    _compact_document_evidence,
    _document_evidence_batches,
    _document_prompt_messages,
    _resolved_inline_value,
)
from app.application.etl.llm_tabular_advice import (
    advise_field_mappings,
    advise_row_decisions,
    advise_workbook_regions,
)

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
