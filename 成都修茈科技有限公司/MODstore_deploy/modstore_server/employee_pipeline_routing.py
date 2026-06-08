"""做员工流水线路由：确定性快路径 vs 需 LLM 规划的模糊 brief（无开关，默认行为）。"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

# direct_python 管线 runtime_kind 集合（vibecoding 默认由 LLM 写 convert）
DIRECT_PYTHON_TEMPLATE_RUNTIMES = frozenset(
    {
        "word_full_extract",
        "word_generate",
        "txt_full_read",
        "txt_generate",
        "pdf_full_read",
        "pdf_generate",
        "csv_full_read",
        "csv_generate",
        "excel_full_read",
        "excel_generate",
        "ppt_full_read",
        "ppt_generate",
        "json_quant_report",
    }
)

_PACK_ID_MARKERS = re.compile(
    r"员工包\s*id|员工包id|pack_id|pack\s*id|员工包：",
    re.I,
)
_RUNTIME_KIND_INLINE = re.compile(r"runtime_kind\s*[:：]\s*([\w_]+)", re.I)


def is_direct_python_template_runtime(runtime_kind: str) -> bool:
    return (runtime_kind or "").strip() in DIRECT_PYTHON_TEMPLATE_RUNTIMES


def confident_word_full_extract_routing(brief: str) -> bool:
    """Brief 含 document_full.json + Word 信号但缺「提取」关键词时，仍走 word_full_extract（省误判 generate）。"""
    from modstore_server.word_extract_runtime import is_word_full_extract

    if is_word_full_extract(brief):
        return True
    bl = (brief or "").lower()
    if "document_full.json" not in bl:
        return False
    if "generated_document" in bl or "word_generate" in bl:
        return False
    if not any(k in bl for k in ("word", "docx", ".doc", "文档")):
        return False
    if (
        any(k in bl for k in ("生成", "写入", "write", "generate", "重建", "render"))
        and "提取" not in bl
    ):
        return False
    return True


def _inline_runtime_kind(brief: str) -> str:
    m = _RUNTIME_KIND_INLINE.search(brief or "")
    return (m.group(1).strip().lower() if m else "") or ""


def is_ambiguous_employee_brief(routing_brief: str) -> bool:
    """模糊 brief 才值得 spec/employee_plan 走 LLM 结构化（减少规划轮次）。"""
    rb = (routing_brief or "").strip()
    if len(rb) < 10:
        return True
    bl = rb.lower()
    signals = 0
    if any(k in bl for k in ("word", "docx", "excel", "xlsx", "pdf", "txt", "csv", "ppt")):
        signals += 1
    if any(
        k in bl
        for k in ("提取", "读取", "生成", "写入", "审核", "转换", "extract", "read", "generate")
    ):
        signals += 1
    if _inline_runtime_kind(rb):
        return False
    if resolve_deterministic_orchestration_plan(rb, {}) is not None:
        return signals < 2
    return True


def skip_employee_plan_llm(payload: Optional[Dict[str, Any]], routing_brief: str) -> bool:
    """brief 已含 pack id + runtime_kind，或确定性管线且非模糊 → 跳过规划 LLM。"""
    rb = (routing_brief or "").strip()
    if not rb:
        return False
    bl = rb.lower()
    rk_inline = _inline_runtime_kind(rb)
    has_pack = bool(_PACK_ID_MARKERS.search(rb))
    if has_pack and rk_inline and is_direct_python_template_runtime(rk_inline):
        return True
    if resolve_deterministic_orchestration_plan(
        rb, payload or {}
    ) and not is_ambiguous_employee_brief(rb):
        return True
    return False


def resolve_deterministic_orchestration_plan(
    routing_brief: str,
    payload: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """无 LLM 的一站式规划（与 workbench _build_employee_orchestration_plan 快路径一致）。"""
    from modstore_server.csv_tabular_runtime import (
        is_csv_full_read,
        is_csv_generate,
        resolve_csv_orchestration_plan,
    )
    from modstore_server.excel_tabular_runtime import (
        is_excel_full_read,
        is_excel_generate,
        resolve_excel_orchestration_plan,
    )
    from modstore_server.pdf_extract_runtime import (
        is_pdf_full_read,
        is_pdf_generate,
        resolve_pdf_orchestration_plan,
    )
    from modstore_server.txt_extract_runtime import (
        is_txt_full_read,
        is_txt_generate,
        resolve_txt_orchestration_plan,
    )
    from modstore_server.word_extract_runtime import (
        is_word_full_extract,
        word_extract_orchestration_plan,
    )
    from modstore_server.word_generate_runtime import (
        is_word_generate,
        word_generate_orchestration_plan,
    )

    rb = (routing_brief or "").strip()
    if is_csv_full_read(rb) or is_csv_generate(rb):
        return resolve_csv_orchestration_plan(rb, payload)
    if is_excel_full_read(rb) or is_excel_generate(rb):
        return resolve_excel_orchestration_plan(rb, payload)
    if is_txt_full_read(rb) or is_txt_generate(rb):
        return resolve_txt_orchestration_plan(rb, payload)
    if is_pdf_full_read(rb) or is_pdf_generate(rb):
        return resolve_pdf_orchestration_plan(rb, payload)
    if is_word_generate(rb):
        return word_generate_orchestration_plan(rb, payload)
    if confident_word_full_extract_routing(rb) or is_word_full_extract(rb):
        return word_extract_orchestration_plan(rb, payload)
    return None


def resolve_employee_runtime_kind(
    routing_brief: str, asset_manifest: Optional[Dict[str, Any]] = None
) -> str:
    """单一真相：brief -> rule_spec.runtime_kind（与 build_rule_spec 顺序一致）。"""
    from modstore_server.employee_asset_pipeline import build_rule_spec

    am = asset_manifest if isinstance(asset_manifest, dict) else {}
    spec = build_rule_spec((routing_brief or "").strip(), am)
    return str(spec.get("runtime_kind") or "").strip()


def pipeline_label_for_runtime_kind(runtime_kind: str) -> str:
    rk = (runtime_kind or "").strip()
    if rk == "word_full_extract":
        return "word_full_extract"
    if rk == "word_generate":
        return "word_generate"
    if rk in ("txt_full_read", "txt_generate"):
        return rk
    if rk in ("pdf_full_read", "pdf_generate"):
        return rk
    if rk in (
        "excel_full_read",
        "excel_generate",
        "csv_full_read",
        "csv_generate",
        "ppt_full_read",
        "ppt_generate",
        "json_quant_report",
    ):
        return "asset" if rk.startswith(("excel_", "csv_", "ppt_", "json_")) else rk
    return "llm_scaffold"


def validate_runtime_pipeline_consistency(
    *,
    routing_brief: str,
    pipeline_label: str,
    rule_spec: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """rule_spec.runtime_kind 与 classify 的 pipeline_label 须一致。"""
    rk = ""
    if isinstance(rule_spec, dict):
        rk = str(rule_spec.get("runtime_kind") or "").strip()
    if not rk:
        rk = resolve_employee_runtime_kind(routing_brief)
    expected = pipeline_label_for_runtime_kind(rk)
    if rk in DIRECT_PYTHON_TEMPLATE_RUNTIMES and pipeline_label == "asset":
        if rk.startswith(("excel_", "csv_", "ppt_")):
            return True, ""
    if expected == pipeline_label:
        return True, ""
    if pipeline_label == "word_full_extract" and rk == "word_full_extract":
        return True, ""
    return False, f"runtime_kind={rk} 与 pipeline_label={pipeline_label} 不一致（期望 {expected}）"


def classify_employee_pipeline(
    routing_brief: str,
    *,
    employee_files: Optional[list] = None,
    needs_llm_reasoning: bool = False,
    contract_doc_with_docx: bool = False,
) -> Tuple[str, bool, bool, bool]:
    """
    返回 (pipeline_label, use_word_extract, use_txt, use_pdf, use_asset).
    pipeline_label: word_full_extract | txt_* | pdf_* | asset | llm_scaffold
    """
    from modstore_server.employee_brief_utils import is_contract_doc_review_brief
    from modstore_server.pdf_extract_runtime import is_pdf_full_read, is_pdf_generate
    from modstore_server.txt_extract_runtime import is_txt_full_read, is_txt_generate

    rb = (routing_brief or "").strip()
    bl = rb.lower()
    files = employee_files or []
    uploaded_docx = any(
        str(f.get("filename") or f.get("name") or "")
        .lower()
        .endswith((".docx", ".doc", ".pdf", ".rtf"))
        for f in files
        if isinstance(f, dict)
    )
    uploaded_excel = any(
        str(f.get("filename") or f.get("name") or "").lower().endswith((".xlsx", ".xls", ".csv"))
        for f in files
        if isinstance(f, dict)
    )
    brief_wants_asset = any(
        k in bl for k in ("excel", "xlsx", "表格", "考勤", "direct_python", "资产驱动")
    )
    use_txt = is_txt_full_read(rb) or is_txt_generate(rb)
    use_pdf = is_pdf_full_read(rb) or is_pdf_generate(rb)
    from modstore_server.word_extract_runtime import is_word_full_extract

    use_word = (
        not use_txt
        and not use_pdf
        and (confident_word_full_extract_routing(rb) or is_word_full_extract(rb))
        and not (is_contract_doc_review_brief(rb) and uploaded_docx)
    )
    use_asset = (
        use_txt
        or use_pdf
        or use_word
        or (
            bool(files)
            and uploaded_excel
            and brief_wants_asset
            and not (needs_llm_reasoning and uploaded_docx)
            and not any(k in bl for k in ("word", "docx", "txt", "文本提取", "文档提取"))
        )
        or (needs_llm_reasoning and uploaded_docx)
    )
    if use_txt:
        label = "txt_generate" if is_txt_generate(rb) else "txt_full_read"
    elif use_pdf:
        from modstore_server.pdf_extract_runtime import is_pdf_generate

        label = "pdf_generate" if is_pdf_generate(rb) else "pdf_full_read"
    elif use_word:
        label = "word_full_extract"
    elif use_asset:
        label = "asset"
    else:
        label = "llm_scaffold"
    return label, use_word, use_txt, use_pdf, use_asset
