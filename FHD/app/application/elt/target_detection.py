"""Conservative input-target detection for the ETL Center's automatic mode."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Iterable

from app.application.elt.parsers import KNOWLEDGE_ONLY_SUFFIXES
from app.application.shipment_excel_elt_security import open_elt_input_file
from app.utils.operational_errors import RECOVERABLE_ERRORS

_DELIVERY_RE = re.compile(r"(送货单|发货单|出货单|delivery)", re.I)
_PRODUCT_RE = re.compile(r"(产品名称|商品名称|货品名称|品名)")
_QUANTITY_RE = re.compile(r"(数量|桶数|件数|重量|规格)")
# 客户主数据必须出现明确的名称列；只有「客户」两个字（对账表、材料价目表的列名）
# 不足以判定为客户表，否则流水表会被当成主数据写出错误客户。
_CUSTOMER_NAME_HEADER_RE = re.compile(
    r"(购货单位|购买单位|客户名称|客户全称|客户姓名|单位名称|往来单位)"
)
# 采购/材料流水：日期 + 厂名 + 品名 + 单价 这类结构，不是客户或产品主数据。
_PURCHASE_LEDGER_RE = re.compile(r"(厂名|供货单位|供应商|厂商).{0,20}(品名|材料|规格|单价)")
_ATTENDANCE_RE = re.compile(r"(考勤|上班时间|下班时间|打卡)")
_PURCHASE_RE = re.compile(r"(采购订单|供应商|供货商)")
# 生产配方单：有「原材料编号/配方总量/工艺流程」等字样，但不是产品主数据。
_RECIPE_RE = re.compile(r"(原材料编号|配方总量|工艺流程|施工配比|固含|细度)")
# 财务/销售台账：逐笔流水，不能写进客户主数据表。
_LEDGER_RE = re.compile(r"(回款|应收|实收|欠款|下欠|对账|账龄|销售明细)")

# 同一文件里既有送货单页又有客户/产品页时，按业务语义优先级打破同分候选。
_TARGET_PRIORITY = {
    "shipment_records": 6,
    "attendance": 5,
    "purchase_orders": 4,
    "customer_products": 3,
    "products": 2,
    "customers": 1,
}


def _compact(text: str) -> str:
    """去掉空白后再匹配：表格标题常用「产 品 名 称」「数 量 / 件」这类字间距。"""
    return re.sub(r"\s+", "", text)


def _joined(values: Iterable[Any]) -> str:
    return " ".join(str(value).strip() for value in values if value not in (None, ""))[:4000]


def _classify(lines: list[str], *, suffix: str) -> dict[str, Any]:
    text = "\n".join(lines)
    compact = _compact(text)
    if (
        _DELIVERY_RE.search(compact)
        and _PRODUCT_RE.search(compact)
        and _QUANTITY_RE.search(compact)
    ):
        return {
            "target_type": "shipment_records",
            "document_type": "delivery_note_workbook",
            "confidence": 0.98,
            "reason": "delivery_title_and_product_table",
        }
    confirmed_sheets = any(name in text for name in ("每日统计", "打卡时间", "原始记录"))
    attendance_fields = (
        re.search(r"姓名", compact)
        and re.search(r"日期|workDate", text, re.I)
        and re.search(r"工号|userid|考勤组", text, re.I)
        and re.search(r"上班|下班|打卡", compact)
    )
    if confirmed_sheets or attendance_fields:
        return {
            "target_type": "attendance",
            "document_type": "attendance_table",
            "confidence": 0.95 if confirmed_sheets else 0.9,
            "reason": "attendance_sheet_names" if confirmed_sheets else "attendance_headers",
            "confirmed": True,
        }
    if _ATTENDANCE_RE.search(compact):
        return {
            "target_type": "abnormal",
            "document_type": "unconfirmed_template",
            "confidence": 0.4,
            "reason": "unconfirmed_attendance_headers",
            "confirmed": False,
        }
    if _PURCHASE_RE.search(compact) and _PRODUCT_RE.search(compact):
        return {
            "target_type": "purchase_orders",
            "document_type": "purchase_order_table",
            "confidence": 0.86,
            "reason": "purchase_and_product_headers",
        }
    # 配方单/台账都是逐行流水或工艺记录，强行套产品/客户主数据只会产生
    # 必填字段缺失或错误主数据；保持未确认，交由人工改选目标。
    if _RECIPE_RE.search(compact):
        return {
            "target_type": "abnormal",
            "document_type": "recipe_sheet",
            "confidence": 0.35,
            "reason": "recipe_sheet_not_master_data",
            "confirmed": False,
        }
    if _LEDGER_RE.search(compact):
        return {
            "target_type": "abnormal",
            "document_type": "finance_ledger",
            "confidence": 0.35,
            "reason": "finance_ledger_not_master_data",
            "confirmed": False,
        }
    if _PURCHASE_LEDGER_RE.search(compact):
        return {
            "target_type": "abnormal",
            "document_type": "purchase_ledger",
            "confidence": 0.35,
            "reason": "purchase_ledger_not_master_data",
            "confirmed": False,
        }
    if _CUSTOMER_NAME_HEADER_RE.search(compact) and _PRODUCT_RE.search(compact):
        return {
            "target_type": "customer_products",
            "document_type": "linked_customer_products",
            "confidence": 0.82,
            "reason": "customer_and_product_headers",
        }
    if _CUSTOMER_NAME_HEADER_RE.search(compact):
        return {
            "target_type": "customers",
            "document_type": "customer_table",
            "confidence": 0.74,
            "reason": "customer_headers",
        }
    if _PRODUCT_RE.search(compact):
        return {
            "target_type": "products",
            "document_type": "product_table",
            "confidence": 0.72,
            "reason": "product_headers",
        }
    return {
        "target_type": "abnormal",
        "document_type": "unconfirmed_template",
        "confidence": 0.0,
        "reason": f"unconfirmed_template:{suffix}",
        "confirmed": False,
    }


def _pick(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """按置信度优先、业务语义次优选择候选。"""
    return max(
        candidates,
        key=lambda item: (
            float(item.get("confidence") or 0),
            _TARGET_PRIORITY.get(str(item.get("target_type")), 0),
        ),
    )


# 无模型时，仅高置信规则结果可直接作为兼容预演候选。
_LLM_ESCALATION_THRESHOLD = 0.7
# 模型答案低于此置信度不采纳，仍按原判定（通常就是 knowledge 兜底）。
_LLM_ACCEPT_CONFIDENCE = 0.75
# 无模型时保留旧的非主数据安全退路，不把流水表强制写进主数据。
_NO_LLM_ESCALATION_REASONS = frozenset(
    {
        "recipe_sheet_not_master_data",
        "finance_ledger_not_master_data",
        "purchase_ledger_not_master_data",
    }
)
_KNOWN_TARGETS = frozenset(_TARGET_PRIORITY) | {"knowledge", "abnormal"}


def _llm_classification(lines: list[str]) -> dict[str, Any] | None:
    """Ask the existing advisory model before considering rule fallback."""
    # 测试默认关闭外部模型调用，避免用例依赖网络；需要覆盖时显式打开。
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("FHD_ELT_LLM_CLASSIFY_TESTS"):
        return None
    try:
        from app.application.elt.llm_assist import (
            advise_target_classification,
            elt_llm_enabled,
        )

        if not elt_llm_enabled():
            return None
        result = advise_target_classification("\n".join(lines)[:6000])
    except RECOVERABLE_ERRORS:
        return None
    if not result.used_llm or result.degraded:
        return None
    data = result.data if isinstance(result.data, dict) else {}
    target = str(data.get("target_type") or "").strip()
    try:
        confidence = float(data.get("confidence") or 0)
    except (TypeError, ValueError):
        return None
    if target not in _KNOWN_TARGETS or not 0.0 <= confidence <= 1.0:
        return None
    accepted = confidence >= _LLM_ACCEPT_CONFIDENCE
    return {
        "target_type": target if accepted else "abnormal",
        "document_type": "llm_classified",
        "confidence": confidence,
        "reason": f"llm:{str(data.get('reason') or '')[:180]}",
        "confirmed": accepted and target != "abnormal",
    }


def _escalate(
    detected: dict[str, Any],
    lines: list[str],
    row_sets: list[list[list[Any]]] | None = None,
) -> dict[str, Any]:
    """Prefer model interpretation; keep rule results explicitly as fallback evidence."""
    classified = _llm_classification(lines)
    rule = {**detected, "decision_source": "rule_fallback"}
    if classified is not None:
        # A workbook-level answer cannot inherit a sheet location from a rule.
        model = {**classified, "decision_source": "model", "rule_candidate": rule}
        if (
            model["target_type"] not in {"knowledge", "abnormal"}
            and float(model.get("confidence") or 0) >= _LLM_ACCEPT_CONFIDENCE
        ):
            return model
        dynamic = _infer_dynamic_schema(row_sets or [])
        if dynamic is not None:
            return _dynamic_result(model, dynamic, "ai_schema")
        if model["target_type"] == "knowledge" and _best_table_sample(row_sets or []) is None:
            return model
        return {
            **model,
            "target_type": "abnormal",
            "confirmed": False,
            "needs_review": True,
        }

    if (
        rule["target_type"] != "abnormal"
        and float(rule.get("confidence") or 0) >= _LLM_ESCALATION_THRESHOLD
    ) or rule.get("reason") in _NO_LLM_ESCALATION_REASONS:
        return rule
    dynamic = _infer_dynamic_schema(row_sets or [])
    if dynamic is not None:
        return _dynamic_result(rule, dynamic, "ai_schema")
    fallback = _fallback_dynamic_schema(row_sets or [])
    if fallback is not None:
        return _dynamic_result(rule, fallback, "header_fallback")
    return rule


def _dynamic_result(
    detected: dict[str, Any], dynamic: dict[str, Any], source: str
) -> dict[str, Any]:
    result = {
        "target_type": "dynamic_table",
        "document_type": "ai_inferred_table" if source == "ai_schema" else "header_table",
        "confidence": float(dynamic.get("confidence") or 0.0),
        "reason": f"{source}:{dynamic.get('table_name') or ''}",
        "confirmed": source == "ai_schema",
        "needs_review": source != "ai_schema",
        "decision_source": source,
        "prior_candidate": detected,
        "dynamic_schema": {
            "table_name": dynamic.get("table_name") or "",
            "columns": dynamic.get("columns") or [],
            "dedupe_keys": dynamic.get("dedupe_keys") or [],
            "headers": dynamic.get("headers") or [],
        },
    }
    return result


def _best_table_sample(
    row_sets: list[list[list[Any]]],
) -> tuple[Any, list[list[Any]]] | None:
    """挑列最多、带数据行的表头区，供 AI 与无模型兜底共用。"""
    from app.application.elt.parser_structure import detect_table_layout

    best: tuple[int, Any, list[list[Any]]] | None = None
    for rows in row_sets:
        layout = detect_table_layout(rows[:60])
        if layout is None:
            continue
        headers = [str(header) for header in layout.headers if str(header).strip()]
        if len(headers) < 2:
            continue
        data_rows = [
            list(row)
            for row in rows[layout.header_end + 1 : layout.header_end + 6]
            if any(value not in (None, "") for value in row)
        ]
        score = len(headers) * 10 + len(data_rows)
        if best is None or score > best[0]:
            best = (score, layout, data_rows)
    return None if best is None else (best[1], best[2])


def _fallback_dynamic_schema(
    row_sets: list[list[list[Any]]],
) -> dict[str, Any] | None:
    picked = _best_table_sample(row_sets)
    if picked is None:
        return None
    layout, _rows = picked
    headers = [str(header).strip() for header in layout.headers if str(header).strip()]
    if len(headers) < 2:
        return None
    return {
        "table_name": "",
        "columns": [
            {"source": header, "name": header, "type": "text", "role": "value"}
            for header in headers
        ],
        "dedupe_keys": [],
        "headers": headers,
        "confidence": 0.0,
    }


def _infer_dynamic_schema(
    row_sets: list[list[list[Any]]],
) -> dict[str, Any] | None:
    """AI-first schema inference for files that match no fixed business target.

    Structure detection stays deterministic (which rows are the header, where the
    data starts); the model only names the table and each column's meaning and
    type. Nothing is written here — the caller decides the target.
    """
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("FHD_ELT_LLM_CLASSIFY_TESTS"):
        return None
    try:
        from app.application.elt.llm_assist import advise_table_schema, elt_llm_enabled

        if not elt_llm_enabled():
            return None
        picked = _best_table_sample(row_sets)
        if picked is None:
            return None
        layout, data_rows = picked
        samples: dict[str, list[str]] = {}
        for index, header in enumerate(layout.headers):
            values: list[str] = []
            for row in data_rows:
                if index < len(row) and row[index] not in (None, ""):
                    text = str(row[index])[:160]
                    if text not in values:
                        values.append(text)
                    if len(values) >= 3:
                        break
            samples[str(header)] = values
        result = advise_table_schema(headers=[str(h) for h in layout.headers], samples=samples)
    except RECOVERABLE_ERRORS:
        return None
    if not result.used_llm or result.degraded:
        return None
    data = result.data if isinstance(result.data, dict) else {}
    if (
        not data.get("is_table")
        or not data.get("columns")
        or not _LLM_ACCEPT_CONFIDENCE <= float(data.get("confidence") or 0) <= 1.0
    ):
        return None
    return {
        "table_name": data.get("table_name") or "",
        "columns": data.get("columns") or [],
        "dedupe_keys": data.get("dedupe_keys") or [],
        "headers": [str(header) for header in layout.headers],
        "confidence": data.get("confidence") or 0.0,
    }


def detect_elt_target(
    path: str | Path, *, suffix: str = "", owner_user_id: int | None = None
) -> dict[str, Any]:
    if owner_user_id is None:
        return _detect_elt_target(path, suffix=suffix, owner_user_id=None)
    from app.application.elt.llm_session_provider import bind_elt_llm_owner, reset_elt_llm_owner

    token = bind_elt_llm_owner(owner_user_id)
    try:
        return _detect_elt_target(path, suffix=suffix, owner_user_id=owner_user_id)
    finally:
        reset_elt_llm_owner(token)


def _detect_elt_target(
    path: str | Path, *, suffix: str, owner_user_id: int | None
) -> dict[str, Any]:
    source = Path(path)
    ext = str(suffix or source.suffix).lower()
    if ext in KNOWLEDGE_ONLY_SUFFIXES:
        return {
            "target_type": "knowledge",
            "document_type": "knowledge_document",
            "confidence": 1.0,
            "reason": "knowledge_only_suffix",
        }
    if ext in {".csv", ".tsv"}:
        from app.infrastructure.document_parsing.delimited import delimited_reader
        from app.infrastructure.document_parsing.native import MAX_SOURCE_BYTES

        lines: list[str] = []
        rows: list[list[Any]] = []
        with open_elt_input_file(source, owner_user_id=owner_user_id) as stream:
            raw = stream.read(MAX_SOURCE_BYTES + 1)
        if len(raw) > MAX_SOURCE_BYTES:
            raise ValueError("CSV/TSV exceeds the source byte budget")
        handle, reader, _dialect = delimited_reader(raw, suffix=ext)
        with handle:
            scanned = 0
            for row in reader:
                scanned += 1
                if scanned > 500:
                    break
                values = list(row)
                # 表前的空行不参与判定，否则真实表头会被挤出采样窗口。
                if not rows and all(value in (None, "") for value in values):
                    continue
                rows.append(values)
                lines.append(_joined(values))
                if len(rows) >= 31:
                    break
        return {
            **_escalate(_classify(lines, suffix=ext), lines, [rows]),
            "evidence_scope": "bounded_csv_sample",
        }
    if ext in {".xlsx", ".xlsm"}:
        from openpyxl import load_workbook

        from app.application.elt.parser_structure import probe_sheet_rows

        with open_elt_input_file(source, owner_user_id=owner_user_id) as stream:
            workbook = load_workbook(stream, read_only=True, data_only=True, keep_links=False)
            candidates: list[dict[str, Any]] = []
            workbook_lines: list[str] = []
            row_sets: list[list[list[Any]]] = []
            try:
                visible = [sheet for sheet in workbook.worksheets if sheet.sheet_state == "visible"]
                for worksheet in visible[:30]:
                    sheet_rows, _first_row = probe_sheet_rows(worksheet, limit=60)
                    sheet_lines = [worksheet.title, *(_joined(row) for row in sheet_rows)]
                    row_sets.append(sheet_rows)
                    workbook_lines.extend(sheet_lines)
                    candidate = _classify(sheet_lines, suffix=ext)
                    if float(candidate.get("confidence") or 0) > 0:
                        candidate["sheet_name"] = worksheet.title
                        candidates.append(candidate)
            finally:
                workbook.close()
        # 先按工作表独立判定：多工作表文件里真正的业务页往往不是第一页，
        # 合并成一个文本块会被备注/合同文字带偏。
        best = _pick(candidates) if candidates else _classify(workbook_lines, suffix=ext)
        return {
            **_escalate(best, workbook_lines, row_sets),
            "evidence_scope": "bounded_visible_sheet_sample",
        }
    filename = source.name
    if _DELIVERY_RE.search(filename):
        return {
            "target_type": "shipment_records",
            "document_type": "delivery_note_ocr",
            "confidence": 0.68,
            "reason": "delivery_filename",
        }
    return {
        "target_type": "abnormal",
        "document_type": "unconfirmed_template",
        "confidence": 0.0,
        "reason": "manual_review_required",
        "confirmed": False,
    }


__all__ = ["detect_elt_target"]
