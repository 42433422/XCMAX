"""PPTX/PDF → 模版库解析桥接 + VLM 路由测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.application.office_template_media_bridge import (
    build_pdf_template_analysis,
    build_pptx_template_analysis,
    extract_placeholder_tokens,
)
from app.infrastructure.llm.vlm_route import list_configured_vlm_candidates, resolve_vlm_route


def test_extract_placeholder_tokens() -> None:
    text = "客户 {{buyer}} 单号 ${order_no} 其它 [[sku]]"
    tokens = extract_placeholder_tokens(text)
    assert tokens == ["buyer", "order_no", "sku"]


def test_build_pptx_template_analysis(tmp_path: Path) -> None:
    import zipfile

    # 最小 OOXML pptx：slide1.xml 含占位符文本（不依赖 python-pptx）
    slide_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree>
    <p:sp><p:txBody><a:p><a:r><a:t>报价单 {{product_name}} 数量 ${qty}</a:t></a:r></a:p></p:txBody></p:sp>
  </p:spTree></p:cSld>
</p:sld>
"""
    content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
</Types>
"""
    path = tmp_path / "quote.pptx"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("ppt/slides/slide1.xml", slide_xml)

    analyzed = build_pptx_template_analysis(str(path), template_name="报价PPT")
    assert analyzed["success"] is True
    assert analyzed["template_type"] == "pptx"
    labels = [f["label"] for f in analyzed["fields"]]
    assert "product_name" in labels
    assert "qty" in labels
    assert analyzed["preview_data"]["file_path"] == str(path)


def test_build_pdf_template_analysis_from_text(tmp_path: Path) -> None:
    from pypdf import PdfWriter

    pdf_path = tmp_path / "tpl.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with pdf_path.open("wb") as f:
        writer.write(f)

    with patch(
        "app.application.office_template_media_bridge.extract_pdf_document_text",
        return_value={
            "text": "送货单 {{customer}} 货号 [[sku]]",
            "page_count": 1,
            "engine": "stub",
            "char_count": 30,
        },
    ):
        analyzed = build_pdf_template_analysis(str(pdf_path), template_name="送货PDF")

    assert analyzed["success"] is True
    assert analyzed["template_type"] == "pdf"
    labels = [f["label"] for f in analyzed["fields"]]
    assert "customer" in labels
    assert "sku" in labels


def test_resolve_vlm_route_explicit(monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_EMPLOYEE_VLM_PROVIDER", "openai")
    monkeypatch.setenv("XCAGI_EMPLOYEE_VLM_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    route = resolve_vlm_route()
    assert route["ok"] is True
    assert route["provider"] == "openai"
    assert route["model"] == "gpt-4o-mini"
    assert route["source"] == "env_explicit"


def test_list_vlm_candidates_and_ops_tools(monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_EMPLOYEE_VLM_PROVIDER", "qwen")
    monkeypatch.setenv("XCAGI_EMPLOYEE_VLM_MODEL", "qwen-vl-plus")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-qwen")
    rows = list_configured_vlm_candidates()
    assert any(r["model"] == "qwen-vl-plus" for r in rows)

    from app.mod_sdk.employee_specialized_tools import (
        EMPLOYEE_TOOLS,
        TOOL_REGISTRY,
        handle_specialized,
    )

    assert "list_vlm_models" in EMPLOYEE_TOOLS["llm-ops-engineer"]
    assert "get_vlm_route" in EMPLOYEE_TOOLS["llm-ops-engineer"]
    assert "list_vlm_models" in TOOL_REGISTRY
    assert "get_vlm_route" in TOOL_REGISTRY

    import asyncio

    listed = asyncio.run(
        handle_specialized("llm-ops-engineer", {"tool": "list_vlm_models", "params": {}}, {})
    )
    assert listed.get("ok") is True
    assert listed.get("active_route", {}).get("model") == "qwen-vl-plus"

    got = asyncio.run(
        handle_specialized("llm-ops-engineer", {"tool": "get_vlm_route", "params": {}}, {})
    )
    assert got.get("ok") is True


def test_ingest_category_pptx() -> None:
    from app.application.office_template_ingest_app_service import (
        _build_create_payload_from_analyze,
        _category_from_filename,
    )

    assert _category_from_filename("a.pptx", "pptx") == "pptx"
    assert _category_from_filename("a.pdf", "pdf") == "pdf"
    payload = _build_create_payload_from_analyze(
        {
            "template_type": "pptx",
            "template_name": "演示",
            "fields": [{"label": "title", "value": "", "type": "dynamic"}],
            "preview_data": {"file_path": "/tmp/a.pptx"},
        },
        filename="a.pptx",
        source="unit",
    )
    assert payload["category"] == "pptx"
    assert payload["template_type"] == "PPTX"
