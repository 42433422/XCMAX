"""Portable deterministic document specs for bundled office employees.

The desktop package must not depend on MODstore's server source tree.  These
helpers accept an existing structured JSON document when present; otherwise
they turn a plain-language request into a safe local baseline that the five
direct-python document generators can write without an LLM round trip.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _text_from_request(src_path: Path, payload: dict[str, Any]) -> str:
    for key in ("user_query", "plain_text", "user_request", "task", "text", "content"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if src_path.suffix.lower() == ".txt" and src_path.is_file():
        try:
            return src_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return ""
    data = _load_json(src_path) if src_path.suffix.lower() == ".json" else {}
    for key in ("plain_text", "user_query", "user_request", "text", "content"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _structured(fmt: str, data: dict[str, Any]) -> dict[str, Any] | None:
    nested_keys = ("document_full", "presentation_full", "table_json")
    candidates = [data] + [
        value for key in nested_keys if isinstance((value := data.get(key)), dict)
    ]
    for candidate in candidates:
        if fmt == "word" and (
            candidate.get("paragraphs") or candidate.get("blocks") or candidate.get("plain_text")
        ):
            return candidate
        if fmt in {"excel", "csv"} and (
            candidate.get("sheets")
            or (
                isinstance(candidate.get("columns"), list)
                and isinstance(candidate.get("rows"), list)
            )
        ):
            return candidate
        if fmt == "ppt" and isinstance(candidate.get("slides"), list) and candidate["slides"]:
            return candidate
        if fmt == "pdf" and (candidate.get("pages") or candidate.get("plain_text")):
            return candidate
    return None


def _lines(text: str) -> list[str]:
    return [line.strip() for line in re.split(r"\r?\n", text) if line.strip()] or [text.strip()]


def _word_spec(text: str) -> dict[str, Any]:
    lines = _lines(text)
    return {
        "plain_text": text,
        "paragraphs": [
            {
                "index": idx,
                "text": line,
                "is_heading": idx == 0,
                "heading_level": 1 if idx == 0 else None,
            }
            for idx, line in enumerate(lines)
        ],
        "tables": [],
        "blocks": [],
    }


def _table_spec(text: str) -> dict[str, Any]:
    lines = _lines(text)
    delimiter = "\t" if any("\t" in line for line in lines) else ","
    matrix = [[cell.strip() for cell in line.split(delimiter)] for line in lines]
    if len(matrix) >= 2 and len(matrix[0]) > 1:
        columns = [cell or f"列{idx + 1}" for idx, cell in enumerate(matrix[0])]
        rows = [dict(zip(columns, row, strict=False)) for row in matrix[1:]]
    else:
        columns = ["内容"]
        rows = [{"内容": line} for line in lines]
    return {
        "columns": columns,
        "rows": rows,
        "sheets": [{"name": "Sheet1", "columns": columns, "rows": rows}],
    }


def _ppt_spec(text: str) -> dict[str, Any]:
    chunks = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()] or [text]
    slides = []
    for idx, chunk in enumerate(chunks):
        lines = _lines(chunk)
        slides.append(
            {"title": lines[0] if lines else f"幻灯片 {idx + 1}", "bullets": lines[1:] or lines[:1]}
        )
    return {"title": slides[0]["title"] if slides else "演示文稿", "slides": slides}


def _pdf_spec(text: str) -> dict[str, Any]:
    lines = _lines(text)
    return {"plain_text": text, "pages": [{"page": 1, "text": "\n".join(lines)}]}


async def resolve_generate_spec(
    fmt: str,
    src_path: Path,
    payload: dict[str, Any],
    ctx: dict[str, Any],
    rule_spec: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Resolve uploaded structured data or a deterministic local document baseline."""
    del ctx, rule_spec
    data = _load_json(src_path) if src_path.suffix.lower() == ".json" else {}
    structured = _structured(fmt, data)
    if structured is not None:
        return structured, []
    text = _text_from_request(src_path, payload)
    if not text:
        raise ValueError("缺少可生成内容：请上传 .json、.txt，或提供 user_request/plain_text")
    if fmt == "word":
        return _word_spec(text), ["已使用本地规则结构化"]
    if fmt in {"excel", "csv"}:
        return _table_spec(text), ["已使用本地规则结构化"]
    if fmt == "ppt":
        return _ppt_spec(text), ["已使用本地规则结构化"]
    if fmt == "pdf":
        return _pdf_spec(text), ["已使用本地规则结构化"]
    raise ValueError(f"unsupported office format: {fmt}")


async def resolve_word_document_spec(
    src_path: Path, payload: dict[str, Any], ctx: dict[str, Any], rule_spec: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    return await resolve_generate_spec("word", src_path, payload, ctx, rule_spec)


async def resolve_table_spec(
    src_path: Path,
    payload: dict[str, Any],
    ctx: dict[str, Any],
    rule_spec: dict[str, Any],
    *,
    fmt: str = "excel",
) -> tuple[dict[str, Any], list[str]]:
    return await resolve_generate_spec(fmt, src_path, payload, ctx, rule_spec)


async def resolve_presentation_spec(
    src_path: Path, payload: dict[str, Any], ctx: dict[str, Any], rule_spec: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    return await resolve_generate_spec("ppt", src_path, payload, ctx, rule_spec)


async def resolve_pdf_document_spec(
    src_path: Path, payload: dict[str, Any], ctx: dict[str, Any], rule_spec: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    return await resolve_generate_spec("pdf", src_path, payload, ctx, rule_spec)


__all__ = [
    "resolve_generate_spec",
    "resolve_pdf_document_spec",
    "resolve_presentation_spec",
    "resolve_table_spec",
    "resolve_word_document_spec",
]
