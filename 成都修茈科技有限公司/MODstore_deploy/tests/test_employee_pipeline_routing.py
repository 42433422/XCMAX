"""Tests for make-employee pipeline routing (productivity, no utilization switches)."""

from modstore_server.employee_pipeline_routing import (
    confident_word_full_extract_routing,
    is_ambiguous_employee_brief,
    is_direct_python_template_runtime,
    resolve_deterministic_orchestration_plan,
    skip_employee_plan_llm,
)
from modstore_server.workbench_api import _contains_uploaded_docx


def test_confident_word_extract_document_full_json():
    brief = (
        "参考 word-full-read-employee，输出 document_full.json + document_full.txt，"
        "handlers direct_python，上传 docx"
    )
    assert confident_word_full_extract_routing(brief)


def test_skip_employee_plan_with_pack_and_runtime():
    brief = "员工包 ID：my-word-emp\nruntime_kind: word_full_extract\n全量提取 docx"
    assert skip_employee_plan_llm({"brief": brief}, brief)


def test_deterministic_plan_word_extract():
    brief = "Word 全量提取 docx，输出 document_full.json，禁止编造"
    plan = resolve_deterministic_orchestration_plan(brief, {"brief": brief})
    assert plan and "employee_brief" in plan


def test_ambiguous_brief_short():
    assert is_ambiguous_employee_brief("做个员工")


def test_template_runtime_kinds():
    assert is_direct_python_template_runtime("word_full_extract")
    assert is_direct_python_template_runtime("json_quant_report")
    assert not is_direct_python_template_runtime("contract_doc_review")


def test_uploaded_docx_detection_uses_normalized_file_names():
    assert _contains_uploaded_docx([{"filename": "合同.DOCX", "content": b"docx"}])
    assert not _contains_uploaded_docx([{"filename": "合同.pdf", "content": b"pdf"}])
