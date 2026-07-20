from __future__ import annotations

import asyncio
import importlib
import json
import sys

from app.services.office_plaintext_generate import (
    install_modstore_office_compat_alias,
    resolve_pdf_document_spec,
    resolve_table_spec,
    resolve_word_document_spec,
    suffix_allowed_for_generate_employee,
)


def test_installs_legacy_modstore_import_alias(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "modstore_server.office_plaintext_generate", raising=False)
    monkeypatch.delitem(sys.modules, "modstore_server", raising=False)

    installed = install_modstore_office_compat_alias()
    legacy = importlib.import_module("modstore_server.office_plaintext_generate")

    assert callable(legacy.resolve_word_document_spec)
    if installed:
        assert legacy.resolve_word_document_spec is resolve_word_document_spec


def test_resolves_structured_word_json(tmp_path) -> None:
    source = tmp_path / "document_full.json"
    source.write_text(
        json.dumps(
            {
                "paragraphs": [{"index": 0, "text": "桌面 Word 兼容验证"}],
                "tables": [],
                "blocks": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    spec, warnings = asyncio.run(resolve_word_document_spec(source, {}, {}, {}))

    assert warnings == []
    assert spec["paragraphs"][0]["text"] == "桌面 Word 兼容验证"


def test_text_fallbacks_cover_table_and_pdf(tmp_path) -> None:
    source = tmp_path / "input.txt"
    source.write_text("名称,数量\n样品,2", encoding="utf-8")

    table, table_warnings = asyncio.run(
        resolve_table_spec(source, {"skip_llm": True}, {}, {}, fmt="excel")
    )
    pdf, pdf_warnings = asyncio.run(resolve_pdf_document_spec(source, {}, {}, {}))

    assert table_warnings == []
    assert table["rows"] == [{"名称": "样品", "数量": "2"}]
    assert pdf_warnings == []
    assert pdf["pages"][0]["text"].startswith("名称,数量")


def test_generate_employee_suffix_contract() -> None:
    assert suffix_allowed_for_generate_employee("word-generate-employee", ".docx") is True
    assert suffix_allowed_for_generate_employee("excel-generate-employee", ".json") is True
    assert suffix_allowed_for_generate_employee("pdf-generate-employee", ".exe") is False
