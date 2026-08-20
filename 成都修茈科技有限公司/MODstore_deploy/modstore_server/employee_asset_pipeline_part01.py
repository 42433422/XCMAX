# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_asset_pipeline")


def _clean_brief_for_description(brief: str, max_len: int = 200) -> str:
    if not brief:
        return ""
    first_sentence = _facade().re.split("[。！？\\n]", brief)[0].strip()
    if (
        first_sentence
        and (not _facade()._LLM_CHAIN_MARKERS.search(first_sentence))
        and (not _facade()._LLM_CHAIN_BLOCK_START.search(first_sentence))
    ):
        return first_sentence[:max_len]
    lines = brief.splitlines()
    clean: list[str] = []
    in_chain_block = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _facade()._LLM_CHAIN_BLOCK_START.search(stripped):
            in_chain_block = True
            continue
        if _facade()._LLM_CHAIN_BLOCK_END.search(stripped):
            in_chain_block = False
            continue
        if in_chain_block:
            continue
        if _facade()._LLM_CHAIN_MARKERS.search(stripped):
            continue
        if _facade().re.match("^[-*]\\s", stripped) and len(stripped) < 15:
            continue
        if _facade().re.match("^\\d+\\.\\s", stripped) and len(stripped) < 20:
            continue
        clean.append(stripped)
    if not clean:
        for seg in _facade().re.split("[。！？]", brief):
            s = seg.strip()
            if (
                s
                and (not _facade()._LLM_CHAIN_MARKERS.search(s))
                and (not _facade()._LLM_CHAIN_BLOCK_START.search(s))
                and (len(s) > 5)
            ):
                return s[:max_len]
        for seg in _facade().re.split("[\\n,，;；]", brief):
            s = seg.strip()
            if (
                s
                and (not _facade()._LLM_CHAIN_MARKERS.search(s))
                and (not _facade()._LLM_CHAIN_BLOCK_START.search(s))
                and (len(s) > 3)
            ):
                return s[:max_len]
        return brief[:max_len].strip()
    return " ".join(clean)[:max_len]


def _safe_basename(name: str, fallback: str = "asset.bin") -> str:
    base = _facade().Path(name or "").name
    if not base or base in {".", ".."}:
        return fallback
    if ".." in base or "/" in base or "\\" in base:
        return fallback
    return base[:180]


def _classify_asset(filename: str) -> str:
    suffix = _facade().Path(filename).suffix.lower()
    if suffix in _facade().EXCEL_SUFFIXES:
        if any((k in filename for k in ("模板", "template", "样板"))):
            return "template"
        if any((k in filename for k in ("输出", "结果", "expected", "answer"))):
            return "expected_output"
        return "example_input"
    if suffix == ".py":
        return "reference_code"
    if suffix in _facade().TEXT_SUFFIXES:
        return "rules"
    return "asset"


def _runtime_module_name(pack_id: str) -> str:
    raw = _facade().re.sub("[^a-z0-9_]+", "_", (pack_id or "employee").lower()).strip("_")
    if not raw:
        raw = "employee"
    if raw[0].isdigit():
        raw = "e_" + raw
    return f"{raw}_runtime"


def _runtime_package_name(pack_id: str, employee_id: str = "") -> str:
    base = employee_id or pack_id
    raw = _facade().re.sub("[^a-z0-9_]+", "_", (base or "employee").lower()).strip("_")
    if not raw:
        raw = "employee"
    if raw.endswith("_employee"):
        raw = raw[: -len("_employee")] or raw
    if raw[0].isdigit():
        raw = "e_" + raw
    return raw
