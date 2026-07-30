"""Deterministic table-structure detection for business-file ETL.

The helpers in this module deliberately avoid model calls.  They identify a
small, auditable table layout that can be reviewed before any target adapter is
allowed to write business data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

_AUXILIARY_SHEET_RE = re.compile(
    r"(说明|须知|目录|封面|汇总|统计|图表|read[\s_-]*me|instruction|summary|cover)",
    re.I,
)
_TOTAL_RE = re.compile(r"^(合计|总计|小计|汇总)(?:\s|[:：]|$)", re.I)
_NOTE_RE = re.compile(r"^(备注|说明|制表|审核|签字|签名)(?:\s|[:：]|$)", re.I)
_NUMBER_RE = re.compile(
    r"^[\s￥¥$€£(（+-]*\d[\d\s,，]*(?:\.\d+)?[%元）)]*$",
    re.I,
)
_DATE_RE = re.compile(
    r"^(?:19|20)\d{2}(?:[-/.年月]\d{1,2}){1,2}(?:日)?(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?$"
)
_CONTEXT_NOISE_RE = re.compile(r"(基本信息|信息|资料|明细|数据|列表|表格|详情)")


def clean_cell_text(value: Any) -> str:
    """Return a stable comparison form without mutating the source value."""
    if value is None:
        return ""
    text = str(value).replace("\ufeff", "").replace("\u200b", "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def semantic_key(value: Any) -> str:
    return "".join(ch.casefold() for ch in clean_cell_text(value) if ch.isalnum())


def header_semantic_keys(header: str) -> tuple[str, ...]:
    """Return full, contextual and leaf keys for a composed header."""
    parts = [
        clean_cell_text(part) for part in re.split(r"[/／>|｜]", header) if clean_cell_text(part)
    ]
    values = [semantic_key(header)]
    if parts:
        values.append(semantic_key(parts[-1]))
        contextual = semantic_key("".join(parts))
        values.append(_CONTEXT_NOISE_RE.sub("", contextual))
    return tuple(dict.fromkeys(value for value in values if value))


def header_match_score(header: str, candidates: Iterable[str]) -> float:
    """Score a source header against a target field without fuzzy model output."""
    keys = header_semantic_keys(header)
    if not keys:
        return 0.0
    full_key = keys[0]
    leaf_key = keys[1] if len(keys) > 1 else full_key
    contextual_keys = set(keys[2:])
    best = 0.0
    for candidate in candidates:
        candidate_key = semantic_key(candidate)
        if not candidate_key:
            continue
        if full_key == candidate_key:
            best = max(best, 0.98)
        if candidate_key in contextual_keys:
            best = max(best, 0.95)
        if leaf_key == candidate_key:
            best = max(best, 0.84)
        if len(candidate_key) >= 2 and (candidate_key in full_key or full_key in candidate_key):
            best = max(best, 0.76)
    return best


@dataclass(frozen=True, slots=True)
class TableLayout:
    header_start: int
    header_end: int
    headers: list[str]
    confidence: float
    matched_hint_count: int
    reasons: tuple[str, ...]


def _row_values(row: Iterable[Any]) -> list[Any]:
    return list(row or [])


def _non_empty(row: Iterable[Any]) -> list[str]:
    return [text for value in row if (text := clean_cell_text(value))]


def _looks_like_data(text: str) -> bool:
    return bool(_NUMBER_RE.fullmatch(text) or _DATE_RE.fullmatch(text))


def _row_score(row: list[Any], row_index: int, hint_keys: set[str]) -> tuple[float, int]:
    cells = _non_empty(row)
    if not cells:
        return (-100.0, 0)
    keys = [semantic_key(cell) for cell in cells]
    matches = sum(
        1
        for key in keys
        if key
        and any(
            key == hint or (len(key) >= 2 and len(hint) >= 2 and (key in hint or hint in key))
            for hint in hint_keys
        )
    )
    if len(cells) == 1 and not matches:
        if not hint_keys and not _looks_like_data(cells[0]):
            return (1.0 - row_index * 0.12, 0)
        return (-100.0, 0)
    text_ratio = sum(not _looks_like_data(cell) for cell in cells) / len(cells)
    unique_ratio = len(set(keys)) / len(keys)
    score = matches * 8.0 + len(cells) * 0.45 + text_ratio * 2.2 + unique_ratio - row_index * 0.12
    if text_ratio < 0.5:
        score -= 4.0
    return score, matches


def _forward_fill(row: list[Any], width: int) -> list[str]:
    result: list[str] = []
    current = ""
    for index in range(width):
        text = clean_cell_text(row[index] if index < len(row) else "")
        if text:
            current = text
        result.append(current)
    return result


def _parent_rows(probe: list[list[Any]], leaf_index: int, leaf_width: int) -> list[int]:
    parents: list[int] = []
    for index in range(max(0, leaf_index - 2), leaf_index):
        cells = _non_empty(probe[index])
        if (
            len(cells) >= 2
            and len(cells) < max(3, leaf_width)
            and sum(not _looks_like_data(cell) for cell in cells) / len(cells) >= 0.8
        ):
            parents.append(index)
    # Only immediately contiguous rows can form a header band.
    contiguous: list[int] = []
    expected = leaf_index - 1
    for index in reversed(parents):
        if index == expected:
            contiguous.append(index)
            expected -= 1
        elif contiguous:
            break
    return list(reversed(contiguous))


def _compose_headers(
    probe: list[list[Any]],
    parent_indexes: list[int],
    leaf_index: int,
) -> list[str]:
    width = max(
        [len(probe[leaf_index])]
        + [len(probe[index]) for index in parent_indexes]
        + [
            max(
                (
                    index + 1
                    for row in probe[leaf_index + 1 :]
                    for index, value in enumerate(row)
                    if clean_cell_text(value)
                ),
                default=0,
            )
        ]
    )
    parent_rows = [_forward_fill(probe[index], width) for index in parent_indexes]
    leaf = [
        clean_cell_text(probe[leaf_index][index] if index < len(probe[leaf_index]) else "")
        for index in range(width)
    ]
    leaf_counts: dict[str, int] = {}
    for value in leaf:
        if value:
            leaf_counts[value] = leaf_counts.get(value, 0) + 1

    raw_headers: list[str] = []
    for column in range(width):
        parts = [row[column] for row in parent_rows if row[column]]
        leaf_value = leaf[column]
        if leaf_value:
            parts.append(leaf_value)
        if not parts:
            raw_headers.append(f"未命名列{column + 1}")
            continue
        needs_context = bool(parent_rows) and (
            not leaf_value
            or leaf_counts.get(leaf_value, 0) > 1
            or semantic_key(parts[-1])
            in {"名称", "name", "编号", "code", "日期", "date", "金额", "amount"}
        )
        raw_headers.append("/".join(dict.fromkeys(parts)) if needs_context else parts[-1])

    seen: dict[str, int] = {}
    headers: list[str] = []
    for index, raw in enumerate(raw_headers, start=1):
        base = clean_cell_text(raw)[:160] or f"未命名列{index}"
        seen[base] = seen.get(base, 0) + 1
        headers.append(base if seen[base] == 1 else f"{base}_{seen[base]}")
    return headers


def detect_table_layout(
    rows: Iterable[Iterable[Any]],
    *,
    header_hints: Iterable[str] = (),
) -> TableLayout | None:
    """Detect a one-to-three-row header in the supplied leading rows."""
    probe = [_row_values(row) for row in rows]
    if not probe:
        return None
    hint_keys = {semantic_key(value) for value in header_hints if semantic_key(value)}
    scored = [(*_row_score(row, index, hint_keys), index) for index, row in enumerate(probe)]
    score, matches, leaf_index = max(scored, key=lambda item: item[0])
    if score <= -50:
        return None
    leaf_width = max(1, len(_non_empty(probe[leaf_index])))
    parents = _parent_rows(probe, leaf_index, leaf_width)
    headers = _compose_headers(probe, parents, leaf_index)
    confidence = min(
        0.99,
        max(
            0.35,
            0.52 + min(matches, 4) * 0.1 + (0.06 if parents else 0) - min(leaf_index, 12) * 0.01,
        ),
    )
    reasons = ["target_header_match" if matches else "tabular_header_shape"]
    if leaf_index:
        reasons.append("leading_preamble_skipped")
    if parents:
        reasons.append("multi_row_header")
    return TableLayout(
        header_start=parents[0] if parents else leaf_index,
        header_end=leaf_index,
        headers=headers,
        confidence=round(confidence, 3),
        matched_hint_count=matches,
        reasons=tuple(reasons),
    )


def is_repeated_header(values: Iterable[Any], headers: list[str]) -> bool:
    cells = [clean_cell_text(value) for value in values]
    populated = [(index, value) for index, value in enumerate(cells) if value]
    if len(populated) < 2:
        return False
    matched = 0
    for index, value in populated:
        if index >= len(headers):
            continue
        if semantic_key(value) in header_semantic_keys(headers[index]):
            matched += 1
    return matched / len(populated) >= 0.7


def is_footer_or_note_row(values: Iterable[Any]) -> bool:
    cells = _non_empty(values)
    if not cells:
        return False
    if semantic_key(cells[0]) in {"合计", "总计", "小计", "汇总"}:
        return True
    first_two = " ".join(cells[:2])
    if _TOTAL_RE.match(first_two):
        return True
    return len(cells) <= 2 and bool(_NOTE_RE.match(first_two))


def is_auxiliary_sheet_name(name: str) -> bool:
    return bool(_AUXILIARY_SHEET_RE.search(clean_cell_text(name)))


__all__ = [
    "TableLayout",
    "clean_cell_text",
    "detect_table_layout",
    "header_match_score",
    "header_semantic_keys",
    "is_auxiliary_sheet_name",
    "is_footer_or_note_row",
    "is_repeated_header",
    "semantic_key",
]
