"""办公生成员纯文本结构化（heuristic + 可选 LLM）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from modstore_server.office_plaintext_generate import (
    build_pdf_spec_from_text,
    build_presentation_spec_from_text,
    build_table_spec_from_text,
    build_word_spec_from_text,
    is_pdf_structured,
    is_presentation_structured,
    is_table_structured,
    is_word_structured,
    parse_json_object_from_llm,
    resolve_generate_spec,
)


def test_heuristic_word_spec() -> None:
    spec = build_word_spec_from_text("标题\n\n第一段正文。\n\n第二段。")
    assert is_word_structured(spec)
    assert spec["plain_text"]
    assert len(spec["paragraphs"]) >= 2


def test_heuristic_table_spec_csv_like() -> None:
    text = "name,score\nAlice,90\nBob,85"
    spec = build_table_spec_from_text(text)
    assert is_table_structured(spec)
    assert spec["columns"] == ["name", "score"]
    assert len(spec["rows"]) == 2


def test_heuristic_presentation_spec() -> None:
    text = "产品 A\n\n亮点一\n亮点二\n\n产品 B\n\n说明"
    spec = build_presentation_spec_from_text(text)
    assert is_presentation_structured(spec)
    assert len(spec["slides"]) >= 2


def test_heuristic_pdf_spec() -> None:
    spec = build_pdf_spec_from_text("Page one\n\nPage two")
    assert is_pdf_structured(spec)
    assert len(spec["pages"]) == 2


def test_parse_json_from_llm_fence() -> None:
    raw = '说明\n```json\n{"plain_text": "hello", "paragraphs": [{"text": "hello"}]}\n```'
    data = parse_json_object_from_llm(raw)
    assert data is not None
    assert data.get("plain_text") == "hello"


@pytest.mark.asyncio
async def test_resolve_generate_spec_from_txt_file(tmp_path: Path) -> None:
    src = tmp_path / "input.txt"
    src.write_text("纯文本生成测试\n第二行", encoding="utf-8")
    spec, warnings = await resolve_generate_spec(
        "word",
        src,
        {"user_query": "", "skip_llm": True},
        {},
        {},
    )
    assert is_word_structured(spec)
    # skip_llm short-circuits to the heuristic path -> no degradation warnings.
    assert warnings == []
    # The plain text is carried through verbatim into the structured spec.
    assert "纯文本生成测试" in spec["plain_text"]


@pytest.mark.asyncio
async def test_resolve_generate_spec_from_json_file(tmp_path: Path) -> None:
    src = tmp_path / "data.json"
    src.write_text(
        json.dumps({"columns": ["a"], "rows": [{"a": "1"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    spec, _ = await resolve_generate_spec("csv", src, {"skip_llm": True}, {}, {})
    assert is_table_structured(spec)
    assert spec["rows"][0]["a"] == "1"


@pytest.mark.asyncio
async def test_resolve_with_mock_llm(tmp_path: Path) -> None:
    src = tmp_path / "prompt.json"
    src.write_text('{"user_query": "做两页PPT"}', encoding="utf-8")

    async def fake_llm(messages, **kwargs):
        return {
            "ok": True,
            "content": json.dumps(
                {
                    "title": "演示",
                    "slides": [
                        {"title": "第1页", "bullets": ["a"]},
                        {"title": "第2页", "bullets": ["b"]},
                    ],
                },
                ensure_ascii=False,
            ),
        }

    spec, _ = await resolve_generate_spec(
        "ppt",
        src,
        {"user_query": "做两页PPT", "use_llm_from_text": True},
        {"call_llm": fake_llm},
        {},
    )
    assert is_presentation_structured(spec)
    assert len(spec["slides"]) == 2
