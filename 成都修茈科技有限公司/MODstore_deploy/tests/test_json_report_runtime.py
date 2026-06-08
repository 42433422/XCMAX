"""JSON 量化报告 runtime 单元测试。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest


def test_json_report_routing_keywords():
    from modstore_server.employee_pipeline_routing import resolve_employee_runtime_kind
    from modstore_server.json_report_runtime import is_json_quant_report

    brief = "员工包 ID：json-report-employee\nJSON 量化报告员\n生成 HTML 量化报告"
    assert is_json_quant_report(brief)
    assert resolve_employee_runtime_kind(brief) == "json_quant_report"
    assert not is_json_quant_report("word-full-read-employee 全量读取 docx")


def test_normalize_document_payload_minimal():
    from modstore_server.json_report_runtime import normalize_document_payload
    from modstore_server.word_generate_runtime import minimal_document_full_json

    doc = minimal_document_full_json()
    assert normalize_document_payload(doc) is doc
    wrapped = {"document_full": doc}
    assert normalize_document_payload(wrapped)["paragraphs"] == doc["paragraphs"]


def test_build_quant_summary():
    from modstore_server.json_report_runtime import build_quant_summary
    from modstore_server.word_generate_runtime import minimal_document_full_json

    summary = build_quant_summary(minimal_document_full_json())
    assert summary["paragraph_count"] >= 1
    assert "title" in summary


@pytest.mark.asyncio
async def test_convert_file_writes_html(tmp_path: Path):
    from modstore_server.json_report_runtime import (
        build_json_quant_report_rule_spec,
        convert_file,
    )
    from modstore_server.word_generate_runtime import minimal_document_full_json

    src = tmp_path / "document_full.json"
    src.write_text(json.dumps(minimal_document_full_json(), ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "outputs" / "quantitative_report.html"
    rule_spec = build_json_quant_report_rule_spec("json-report-employee")

    async def mock_call_llm(messages, max_tokens=10000, temperature=0.2):  # noqa: ARG001
        return {
            "ok": True,
            "content": "<!DOCTYPE html><html><head><meta charset='UTF-8'/></head><body><h1>测试报告</h1></body></html>",
        }

    result = await convert_file(
        src,
        out,
        template_path=None,
        payload={"task": "单元测试"},
        ctx={"call_llm": mock_call_llm},
        rule_spec=rule_spec,
    )
    assert out.is_file()
    html = out.read_text(encoding="utf-8")
    assert "<html" in html.lower()
    assert result.get("report_html_path")
    assert result.get("paragraph_count", 0) >= 1


def test_convert_file_sync_wrapper(tmp_path: Path):
    from modstore_server.json_report_runtime import (
        build_json_quant_report_rule_spec,
        convert_file,
        render_json_report_convert_module,
    )
    from modstore_server.word_generate_runtime import minimal_document_full_json

    code = render_json_report_convert_module()
    ns: dict = {}
    exec(code, ns)  # noqa: S102
    convert_mod = ns["convert_file"]

    src = tmp_path / "in.json"
    src.write_text(json.dumps(minimal_document_full_json()), encoding="utf-8")
    out = tmp_path / "outputs" / "quantitative_report.html"
    rule_spec = build_json_quant_report_rule_spec("json report")

    async def mock_call_llm(messages, max_tokens=10000, temperature=0.2):  # noqa: ARG001
        return {"ok": True, "content": "<!DOCTYPE html><html><body>ok</body></html>"}

    asyncio.run(
        convert_mod(
            src,
            out,
            template_path=None,
            payload={},
            ctx={"call_llm": mock_call_llm},
            rule_spec=rule_spec,
        )
    )
    assert out.is_file()
