"""办公生成员：纯文本 / 结构化 JSON 双模式输入解析（供各 *-generate-employee runtime 复用）。"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

OfficeFormatKind = str  # word | excel | csv | ppt | pdf

_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def _brief_text(payload: Dict[str, Any]) -> str:
    for key in ("user_query", "plain_text", "task"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def read_text_from_src(src_path: Path) -> str:
    if not src_path.is_file():
        return ""
    suffix = src_path.suffix.lower()
    if suffix == ".txt":
        return src_path.read_text(encoding="utf-8", errors="replace").strip()
    if suffix == ".json":
        try:
            data = json.loads(src_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return ""
        if isinstance(data, dict):
            pt = data.get("plain_text")
            if isinstance(pt, str) and pt.strip():
                return pt.strip()
            uq = data.get("user_query")
            if isinstance(uq, str) and uq.strip():
                return uq.strip()
    return ""


def coerce_user_text(payload: Dict[str, Any], src_path: Optional[Path] = None) -> str:
    text = _brief_text(payload)
    if text:
        return text
    if src_path is not None:
        return read_text_from_src(src_path)
    return ""


def parse_json_object_from_llm(content: str) -> Optional[Dict[str, Any]]:
    raw = (content or "").strip()
    if not raw:
        return None
    fence = _JSON_FENCE.search(raw)
    if fence:
        raw = fence.group(1).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _should_use_llm(payload: Dict[str, Any], fmt: OfficeFormatKind) -> bool:
    if payload.get("skip_llm") or payload.get("use_llm_from_text") is False:
        return False
    if payload.get("use_llm_from_text") is True:
        return True
    return fmt in ("excel", "ppt")


# --- Heuristic builders ---


def build_word_spec_from_text(text: str) -> Dict[str, Any]:
    plain = (text or "").strip()
    paragraphs: List[Dict[str, Any]] = []
    for idx, block in enumerate(re.split(r"\n\s*\n", plain)):
        t = block.strip()
        if not t:
            continue
        is_heading = len(t) < 80 and (
            t.endswith("：") or t.endswith(":") or re.match(r"^第[一二三四五六七八九十\d]+", t)
        )
        paragraphs.append(
            {
                "index": idx,
                "text": t,
                "is_heading": is_heading,
                "heading_level": 1 if is_heading else None,
            }
        )
    if not paragraphs and plain:
        paragraphs = [{"index": 0, "text": plain}]
    return {"plain_text": plain, "paragraphs": paragraphs, "tables": [], "blocks": []}


def build_table_spec_from_text(text: str, *, sheet_name: str = "Sheet1") -> Dict[str, Any]:
    plain = (text or "").strip()
    lines = [ln for ln in plain.splitlines() if ln.strip()]
    if not lines:
        return {
            "columns": ["内容"],
            "rows": [{"内容": ""}],
            "sheets": [{"name": sheet_name, "columns": ["内容"], "rows": []}],
        }
    sample = lines[0]
    if "," in sample and sample.count(",") >= 1:
        reader = csv.reader(io.StringIO("\n".join(lines)))
        rows_raw = list(reader)
        if rows_raw:
            columns = [str(c).strip() or f"列{i+1}" for i, c in enumerate(rows_raw[0])]
            rows = []
            for r in rows_raw[1:]:
                row = {columns[i]: (r[i] if i < len(r) else "") for i in range(len(columns))}
                rows.append(row)
            if not rows and len(rows_raw) == 1:
                rows = [{columns[0]: rows_raw[0][0] if rows_raw[0] else ""}]
            return {
                "columns": columns,
                "rows": rows,
                "sheets": [{"name": sheet_name, "columns": columns, "rows": rows}],
            }
    if "\t" in sample:
        rows_raw = [ln.split("\t") for ln in lines]
        columns = [f"列{i+1}" for i in range(len(rows_raw[0]))]
        rows = [
            {columns[i]: (r[i] if i < len(r) else "") for i in range(len(columns))}
            for r in rows_raw
        ]
        return {
            "columns": columns,
            "rows": rows,
            "sheets": [{"name": sheet_name, "columns": columns, "rows": rows}],
        }
    rows = [{"内容": ln.strip()} for ln in lines]
    return {
        "columns": ["内容"],
        "rows": rows,
        "sheets": [{"name": sheet_name, "columns": ["内容"], "rows": rows}],
    }


def build_presentation_spec_from_text(text: str) -> Dict[str, Any]:
    plain = (text or "").strip()
    chunks = [c.strip() for c in re.split(r"\n\s*\n", plain) if c.strip()]
    if not chunks:
        chunks = [ln.strip() for ln in plain.splitlines() if ln.strip()]
    if not chunks:
        chunks = ["（空内容）"]
    title = chunks[0][:120] if chunks else "演示文稿"
    slides = []
    for i, chunk in enumerate(chunks[:30]):
        lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
        slide_title = lines[0][:120] if lines else f"第{i+1}页"
        bullets = lines[1:] if len(lines) > 1 else [chunk[:500]]
        slides.append({"title": slide_title, "bullets": bullets[:8]})
    return {"title": title, "slides": slides}


def build_pdf_spec_from_text(text: str) -> Dict[str, Any]:
    plain = (text or "").strip()
    pages = []
    chunks = re.split(r"\n\s*---+\s*\n|\f", plain)
    if len(chunks) <= 1 and "\n\n" in plain:
        chunks = re.split(r"\n\s*\n", plain)
    for idx, block in enumerate(chunks or [plain]):
        t = block.strip()
        if t:
            pages.append({"page": idx + 1, "text": t})
    if not pages:
        pages = [{"page": 1, "text": plain or " "}]
    return {"plain_text": plain, "pages": pages}


def is_word_structured(data: Dict[str, Any]) -> bool:
    return bool(data.get("paragraphs") or data.get("blocks") or data.get("plain_text"))


def is_table_structured(data: Dict[str, Any]) -> bool:
    if isinstance(data.get("sheets"), list) and data["sheets"]:
        return True
    return isinstance(data.get("columns"), list) and isinstance(data.get("rows"), list)


def is_presentation_structured(data: Dict[str, Any]) -> bool:
    slides = data.get("slides")
    return isinstance(slides, list) and len(slides) > 0


def is_pdf_structured(data: Dict[str, Any]) -> bool:
    if isinstance(data.get("pages"), list) and data["pages"]:
        return True
    return bool(str(data.get("plain_text") or "").strip())


def load_json_file(src_path: Path) -> Dict[str, Any]:
    data = json.loads(src_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON 根节点必须是对象")
    return data


async def _structure_via_llm(
    fmt: OfficeFormatKind,
    user_text: str,
    ctx: Dict[str, Any],
    payload: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    warnings: List[str] = []
    if not user_text.strip():
        return None, warnings
    if not _should_use_llm(payload, fmt):
        return None, warnings

    schema_hints = {
        "word": "JSON 对象，含 plain_text（string）与可选 paragraphs 数组（每项含 text、is_heading、heading_level）。",
        "excel": "JSON 对象，含 sheets 数组（每项 name、columns、rows）或 columns+rows。",
        "csv": "JSON 对象，含 columns（string[]）与 rows（对象数组）。",
        "ppt": "JSON 对象，含 title（string）与 slides（每项 title、bullets 字符串数组）。",
        "pdf": "JSON 对象，含 plain_text 与 pages（每项 page、text）。",
    }
    hint = schema_hints.get(fmt, schema_hints["word"])
    messages = [
        {
            "role": "system",
            "content": (
                "你是办公文档结构化助手。仅根据用户描述生成合法 JSON，不要 markdown 说明。"
                f"输出格式：{hint} 只输出一个 JSON 对象。"
            ),
        },
        {"role": "user", "content": user_text[:12000]},
    ]
    call_llm = ctx.get("call_llm")
    if not callable(call_llm):
        warnings.append("ctx.call_llm 不可用，使用规则降级结构化")
        return None, warnings
    try:
        res = await asyncio.wait_for(
            call_llm(messages, max_tokens=int(payload.get("max_tokens") or 8000), temperature=0.2),
            timeout=float(payload.get("llm_timeout_s") or 90.0),
        )
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"LLM 结构化失败: {exc}")
        return None, warnings
    if not isinstance(res, dict) or not res.get("ok"):
        warnings.append(str((res or {}).get("error") or "LLM 返回失败")[:400])
        return None, warnings
    parsed = parse_json_object_from_llm(str(res.get("content") or ""))
    if not parsed:
        warnings.append("LLM 未返回可解析 JSON")
    return parsed, warnings


def _heuristic_for_format(fmt: OfficeFormatKind, text: str) -> Dict[str, Any]:
    if fmt == "word":
        return build_word_spec_from_text(text)
    if fmt == "ppt":
        return build_presentation_spec_from_text(text)
    if fmt == "pdf":
        return build_pdf_spec_from_text(text)
    return build_table_spec_from_text(text)


def _validate_structured(fmt: OfficeFormatKind, data: Dict[str, Any]) -> bool:
    if fmt == "word":
        return is_word_structured(data)
    if fmt == "ppt":
        return is_presentation_structured(data)
    if fmt == "pdf":
        return is_pdf_structured(data)
    return is_table_structured(data)


async def resolve_generate_spec(
    fmt: OfficeFormatKind,
    src_path: Path,
    payload: Dict[str, Any],
    ctx: Dict[str, Any],
    rule_spec: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[str]]:
    """返回 canonical spec dict 与 warnings。"""
    del rule_spec
    warnings: List[str] = []
    suffix = src_path.suffix.lower() if src_path.is_file() else ""

    if suffix == ".json" and src_path.is_file():
        data = load_json_file(src_path)
        if _validate_structured(fmt, data):
            return data, warnings
        nested = (
            data.get("document_full") or data.get("presentation_full") or data.get("table_json")
        )
        if isinstance(nested, dict) and _validate_structured(fmt, nested):
            return nested, warnings

    user_text = coerce_user_text(payload, src_path)
    if suffix == ".txt" and not user_text:
        user_text = read_text_from_src(src_path)

    if user_text:
        llm_data, llm_warn = await _structure_via_llm(fmt, user_text, ctx, payload)
        warnings.extend(llm_warn)
        if llm_data and _validate_structured(fmt, llm_data):
            return llm_data, warnings
        spec = _heuristic_for_format(fmt, user_text)
        if _validate_structured(fmt, spec):
            if llm_warn:
                warnings.append("已使用规则降级结构化")
            return spec, warnings

    if suffix == ".json" and src_path.is_file():
        data = load_json_file(src_path)
        return data, warnings

    raise ValueError(
        "缺少可生成内容：请上传 .json（结构化中介）、.txt，或在 input_data 中提供 user_query/plain_text"
    )


async def resolve_word_document_spec(
    src_path: Path,
    payload: Dict[str, Any],
    ctx: Dict[str, Any],
    rule_spec: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[str]]:
    return await resolve_generate_spec("word", src_path, payload, ctx, rule_spec)


async def resolve_table_spec(
    src_path: Path,
    payload: Dict[str, Any],
    ctx: Dict[str, Any],
    rule_spec: Dict[str, Any],
    *,
    fmt: OfficeFormatKind = "excel",
) -> Tuple[Dict[str, Any], List[str]]:
    return await resolve_generate_spec(fmt, src_path, payload, ctx, rule_spec)


async def resolve_presentation_spec(
    src_path: Path,
    payload: Dict[str, Any],
    ctx: Dict[str, Any],
    rule_spec: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[str]]:
    return await resolve_generate_spec("ppt", src_path, payload, ctx, rule_spec)


async def resolve_pdf_document_spec(
    src_path: Path,
    payload: Dict[str, Any],
    ctx: Dict[str, Any],
    rule_spec: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[str]]:
    return await resolve_generate_spec("pdf", src_path, payload, ctx, rule_spec)


GENERATE_EMPLOYEE_IDS = frozenset(
    {
        "word-generate-employee",
        "excel-generate-employee",
        "csv-generate-employee",
        "pdf-generate-employee",
        "ppt-generate-employee",
    }
)


def suffix_allowed_for_generate_employee(employee_id: str, suffix: str) -> bool:
    if employee_id not in GENERATE_EMPLOYEE_IDS:
        return False
    if suffix in {".json", ".txt"}:
        return True
    if employee_id == "word-generate-employee" and suffix == ".docx":
        return True
    return False
