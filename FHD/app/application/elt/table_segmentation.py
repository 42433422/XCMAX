"""Deterministic sheet segmentation into tables with an explicit fate per cell.

A sheet is split into column bands (blank columns, side annotations), then into
row segments (title, form info, parent/leaf header, body, summary and notes),
then side-by-side tables that repeat one header group are split by columns.
Every non-empty cell is assigned to a table role or to an exclusion with a
reason, so callers can prove that nothing was silently dropped.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.application.elt.parser_structure import clean_cell_text, semantic_key

Grid = dict[tuple[int, int], Any]
Merge = tuple[int, int, int, int]  # min_row, min_col, max_row, max_col

_NUMBER_RE = re.compile(r"^[\s￥¥$€£(（+-]*\d[\d\s,，]*(?:\.\d+)?[%元）)]*$")
_DATE_RE = re.compile(
    r"^(?:19|20)?\d{2}(?:[-/.年月]\d{1,2}){1,2}(?:日)?(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?$"
)
_TOTAL_RE = re.compile(r"^(合计|总计|小计|汇总|共计|累计)(?:\s|[:：]|$)")
_NOTE_RE = re.compile(r"^(备注|说明|注[:：]|注意|制表|审核|签字|签名|条款|附注)")
_WEEKDAYS = {
    *"日一二三四五六天",
    *(f"周{d}" for d in "日一二三四五六天"),
    *(f"星期{d}" for d in "日一二三四五六天"),
    "mon",
    "tue",
    "wed",
    "thu",
    "fri",
    "sat",
    "sun",
}
_MONTH_RE = re.compile(r"((?:19|20)\d{2})\s*年\s*(\d{1,2})\s*月")

ROLE_REASONS = {
    "title": "标题行，不是业务记录",
    "form_info": "表单信息行（字段：值），不是表格记录",
    "preamble": "位于表头之前的说明或汇总行，不是业务记录",
    "parent_header": "上级表头",
    "header": "表头",
    "repeated_header": "重复表头，不是业务记录",
    "summary": "合计/小计/汇总行，不纳入普通业务记录",
    "note": "备注、说明或条款文字，不纳入普通业务记录",
    "side_annotation": "表头范围之外的旁注，不纳入业务记录",
    "out_of_schema": "缺少表格主列的值，按汇总或说明行排除",
    "data": "业务记录",
}
EXCLUDED_ROLES = frozenset(ROLE_REASONS) - {"data", "header", "parent_header"}


@dataclass(slots=True)
class SegmentedTable:
    table_id: str
    min_col: int
    max_col: int
    title_rows: list[int]
    header_rows: list[int]
    leaf_row: int
    headers: list[str]
    header_paths: list[list[str]]
    data_rows: list[int] = field(default_factory=list)
    end_row: int = 0
    kind: str = "table"
    title: str = ""
    group: str = ""
    repeated: bool = False

    @property
    def signature(self) -> str:
        keys = [semantic_key(path[-1]) if path else "" for path in self.header_paths]
        if self.kind == "calendar":
            return "calendar"
        return "|".join(keys)

    def range_ref(self) -> str:
        from openpyxl.utils import get_column_letter

        start = self.header_rows[0] if self.header_rows else self.leaf_row
        return f"{get_column_letter(self.min_col)}{start}:{get_column_letter(self.max_col)}{self.end_row}"

    def period(self) -> str:
        match = _MONTH_RE.search(self.title)
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}" if match else ""

    def public(self) -> dict[str, Any]:
        return {
            "table_id": self.table_id,
            "kind": self.kind,
            "range": self.range_ref(),
            "title": self.title,
            "title_rows": self.title_rows,
            "header_rows": self.header_rows,
            "headers": self.headers,
            "header_paths": self.header_paths,
            "data_rows": len(self.data_rows),
            "group": self.group,
            "repeated_header": self.repeated,
        }


@dataclass(slots=True)
class SheetSegmentation:
    sheet: str
    tables: list[SegmentedTable]
    cells: dict[tuple[int, int], tuple[str, str]]
    row_roles: list[dict[str, Any]]

    def groups(self) -> dict[str, list[SegmentedTable]]:
        result: dict[str, list[SegmentedTable]] = {}
        for table in self.tables:
            result.setdefault(table.group, []).append(table)
        return result

    def dominant_group(self) -> list[SegmentedTable]:
        scored = [
            (sum(len(t.data_rows) for t in tables), len(tables[0].headers), tables)
            for tables in self.groups().values()
            if any(t.data_rows for t in tables)
        ]
        return max(scored, key=lambda item: (item[0], item[1]))[2] if scored else []

    def coverage(self) -> dict[str, Any]:
        counts = Counter(role for role, _ in self.cells.values())
        return {
            "nonempty_cells": len(self.cells),
            "assigned_cells": sum(counts.values()),
            "unassigned_cells": 0,
            "by_role": dict(sorted(counts.items())),
        }

    def public(self) -> dict[str, Any]:
        return {
            "sheet": self.sheet,
            "tables": [table.public() for table in self.tables],
            "coverage": self.coverage(),
            "excluded_rows": [item for item in self.row_roles if item["role"] in EXCLUDED_ROLES],
        }


def _text(value: Any) -> str:
    return clean_cell_text(value)


def _is_data_like(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float, datetime, date)):
        return True
    text = _text(value)
    return bool(text.startswith("=") or _NUMBER_RE.fullmatch(text) or _DATE_RE.fullmatch(text))


def _is_label(value: Any) -> bool:
    text = _text(value)
    return (
        bool(text)
        and not _is_data_like(value)
        and len(text) <= 24
        and bool(re.search(r"[\u4e00-\u9fffA-Za-z]", text))
    )


def _day_number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int):
        return value if 1 <= value <= 31 else None
    text = _text(value)
    return int(text) if text.isdigit() and 1 <= int(text) <= 31 else None


class _Sheet:
    def __init__(self, cells: Grid, merges: list[Merge]) -> None:
        self.cells = {key: value for key, value in cells.items() if _text(value)}
        self.merges = merges
        self.anchor_span: dict[tuple[int, int], Merge] = {}
        self.covered: dict[tuple[int, int], tuple[int, int]] = {}
        for merge in merges:
            r1, c1, r2, c2 = merge
            self.anchor_span[(r1, c1)] = merge
            if (r2 - r1 + 1) * (c2 - c1 + 1) <= 20_000:
                for r in range(r1, r2 + 1):
                    for c in range(c1, c2 + 1):
                        if (r, c) != (r1, c1):
                            self.covered[(r, c)] = (r1, c1)
        self.by_row: dict[int, list[int]] = {}
        for r, c in sorted(self.cells):
            self.by_row.setdefault(r, []).append(c)

    def value(self, r: int, c: int, *, through_merge: bool = False) -> Any:
        if (r, c) in self.cells:
            return self.cells[(r, c)]
        if through_merge and (r, c) in self.covered:
            return self.cells.get(self.covered[(r, c)])
        return None

    def row_cols(self, r: int, c1: int, c2: int) -> list[int]:
        return [c for c in self.by_row.get(r, ()) if c1 <= c <= c2]

    def h_span(self, r: int, c: int) -> int:
        merge = self.anchor_span.get((r, c))
        return merge[3] - merge[1] + 1 if merge else 1

    def v_merge_end(self, r: int, c1: int, c2: int) -> int:
        return max(
            (m[2] for m in self.merges if m[0] <= r <= m[2] and m[1] <= c2 and m[3] >= c1),
            default=r,
        )


def _column_bands(sheet: _Sheet) -> list[tuple[int, int]]:
    occupied: set[int] = set()
    for r, cols in sheet.by_row.items():
        if len(cols) < 2:
            continue
        for c in cols:
            occupied.update(range(c, c + sheet.h_span(r, c)))
    for c in [c for _r, c in sheet.cells if c not in occupied]:
        occupied.add(c)
    bands: list[list[int]] = []
    for c in sorted(occupied):
        if bands and c == bands[-1][1] + 1:
            bands[-1][1] = c
        else:
            bands.append([c, c])
    merged: list[list[int]] = []
    for band in bands:
        if (
            merged
            and _band_has_multi_cell_rows(sheet, band)
            and not _band_has_header(sheet, band)
            and _band_has_header(sheet, merged[-1])
        ):
            merged[-1][1] = band[1]
        else:
            merged.append(band)
    # A header-less key column (e.g. names left of a calendar) joins the table it labels.
    index = 0
    while index + 1 < len(merged):
        left, right = merged[index], merged[index + 1]
        shares_rows = any(
            sheet.row_cols(r, left[0], left[1]) and sheet.row_cols(r, right[0], right[1])
            for r in sheet.by_row
        )
        if shares_rows and not _band_has_header(sheet, left) and _band_has_header(sheet, right):
            merged[index : index + 2] = [[left[0], right[1]]]
        else:
            index += 1
    return [(a, b) for a, b in merged]


def _band_has_multi_cell_rows(sheet: _Sheet, band: list[int]) -> bool:
    return any(len(sheet.row_cols(r, band[0], band[1])) >= 2 for r in sheet.by_row)


def _band_has_header(sheet: _Sheet, band: list[int]) -> bool:
    return any(
        _row_kind(sheet, r, band[0], band[1]) in {"header", "day_header"} for r in sheet.by_row
    )


def _row_kind(sheet: _Sheet, r: int, c1: int, c2: int) -> str:
    cols = sheet.row_cols(r, c1, c2)
    if not cols:
        return "blank"
    values = [sheet.cells[(r, c)] for c in cols]
    days = [d for d in (_day_number(v) for v in values) if d is not None]
    if len(days) >= 7 and days[:7] == list(range(1, 8)):
        return "day_header"
    if sum(_text(v).lower() in _WEEKDAYS for v in values) >= 7:
        return "weekday_header"
    texts = [_text(v) for v in values]
    labels = [t for v, t in zip(values, texts) if _is_label(v)]
    colon = sum(t.endswith((":", "：")) or bool(re.search(r"[:：]\s*\S", t)) for t in labels)
    if any(_TOTAL_RE.search(t) and len(t) <= 10 for t in labels[:3]):
        return "summary"
    if len(values) == 1 and _NOTE_RE.match(texts[0]):
        return "single"
    if (
        labels
        and colon * 2 >= len(labels)
        and len(labels) * 2 >= len(values)
        and not any(_is_data_like(v) for v in values)
    ):
        return "form_info"
    if len(values) == 1:
        return "single"
    if len(labels) == len(values) and all(sheet.h_span(r, c) >= 2 for c in cols):
        return "banner"
    if len(labels) / len(values) >= 0.75 and len({semantic_key(t) for t in labels}) >= 2:
        return "header"
    return "data"


def _is_parent_row(sheet: _Sheet, r: int, leaf: int, c1: int, c2: int) -> bool:
    kind = _row_kind(sheet, r, c1, c2)
    if kind == "weekday_header":
        return True
    if kind not in {"header", "single", "data", "form_info", "banner"}:
        return False
    cols = sheet.row_cols(r, c1, c2)
    leaf_cols = sheet.row_cols(leaf, c1, c2)
    labels = [c for c in cols if _is_label(sheet.cells[(r, c)])]
    merged = [c for c in labels if sheet.h_span(r, c) >= 2]
    if leaf_cols and len(cols) == 1:
        leaf_width = leaf_cols[-1] - leaf_cols[0] + 1
        if sheet.h_span(r, cols[0]) * 10 >= leaf_width * 9:
            return False
    return bool(merged) and len(cols) < max(2, len(leaf_cols)) and len(labels) * 2 >= len(cols)


def _header_paths(
    sheet: _Sheet, parents: list[int], leaf: int, c1: int, c2: int, subs: list[int]
) -> tuple[list[str], list[list[str]]]:
    paths: list[list[str]] = []
    for c in range(c1, c2 + 1):
        parts: list[str] = []
        for r in parents:
            anchor = next(
                (
                    (ar, ac)
                    for (ar, ac), (mr1, mc1, mr2, mc2) in sheet.anchor_span.items()
                    if ar == r and mc1 <= c <= mc2 and mr1 <= r <= mr2
                ),
                None,
            )
            value = sheet.cells.get(anchor) if anchor else sheet.cells.get((r, c))
            if value is None and (r, c) in sheet.covered:
                value = sheet.cells.get(sheet.covered[(r, c)])
            if _is_label(value):
                parts.append(_text(value))
        leaf_value = sheet.value(leaf, c, through_merge=True)
        if _text(leaf_value):
            parts.append(_text(leaf_value))
        parts.extend(_text(sheet.cells[(r, c)]) for r in subs if _is_label(sheet.cells.get((r, c))))
        paths.append(list(dict.fromkeys(parts)))
    labels: list[str] = []
    seen: Counter[str] = Counter()
    leaf_counts = Counter(path[-1] for path in paths if path)
    for index, path in enumerate(paths, start=1):
        if not path:
            base = f"未命名列{index}"
        elif len(path) > 1 and leaf_counts[path[-1]] > 1:
            base = "/".join(path)
        else:
            base = path[-1]
        seen[base] += 1
        labels.append(base if seen[base] == 1 else f"{base}_{seen[base]}")
    return labels, paths


def _anchor_split(tokens: list[str], start: int, c1: int, c2: int) -> list[tuple[int, int]]:
    """Split where the first header label repeats, allowing blocks of varying width."""
    occurrences = [i for i, t in enumerate(tokens) if t == tokens[start]]
    if len(occurrences) < 2:
        return []
    edges = [*occurrences, len(tokens)]
    first = set(tokens[edges[0] : edges[1]]) - {"", tokens[start]}
    bounds: list[tuple[int, int]] = []
    for a, b in zip(edges, edges[1:]):
        others = set(tokens[a:b]) - {"", tokens[start]}
        if bounds and len(others & first) < min(2, max(1, len(others))):
            bounds[-1] = (bounds[-1][0], c1 + b - 1)
            continue
        bounds.append((c1 + a, c1 + b - 1))
    if len(bounds) < 2:
        return []
    bounds[0] = (c1, bounds[0][1])
    bounds[-1] = (bounds[-1][0], c2)
    return bounds


def _periodic_split(sheet: _Sheet, leaf: int, c1: int, c2: int) -> list[tuple[int, int]]:
    tokens = [semantic_key(sheet.cells.get((leaf, c))) for c in range(c1, c2 + 1)]
    start = next((i for i, t in enumerate(tokens) if t), None)
    if start is None:
        return []
    anchored = _anchor_split(tokens, start, c1, c2)
    if anchored:
        return anchored
    width = len(tokens) - start
    for period in range(2, width // 2 + 1):
        first = tokens[start : start + period]
        nonempty = sum(bool(t) for t in first)
        if nonempty < 2:
            continue
        segments = 1
        while start + (segments + 1) * period <= len(tokens):
            seg = tokens[start + segments * period : start + (segments + 1) * period]
            matches = sum(bool(a) and a == b for a, b in zip(first, seg))
            if matches < 2 or matches * 2 < nonempty:
                break
            segments += 1
        if segments < 2:
            continue
        bounds = [
            (c1 + start + k * period, c1 + start + (k + 1) * period - 1) for k in range(segments)
        ]
        bounds[0] = (c1, bounds[0][1])
        tail = (bounds[-1][1] + 1, c2)
        if tail[0] <= c2:
            tail_tokens = tokens[tail[0] - c1 :]
            if sum(bool(t) for t in tail_tokens) >= 2:
                bounds.append(tail)
            else:
                bounds[-1] = (bounds[-1][0], c2)
        return bounds
    return []


class _Segmenter:
    def __init__(self, sheet: _Sheet, sheet_name: str) -> None:
        self.sheet = sheet
        self.name = sheet_name
        self.tables: list[SegmentedTable] = []
        self.cells: dict[tuple[int, int], tuple[str, str]] = {}
        self.row_roles: list[dict[str, Any]] = []
        self.next_id = 1

    def assign(
        self, r: int, c1: int, c2: int, role: str, table: str = "", reason: str = ""
    ) -> None:
        cols = self.sheet.row_cols(r, c1, c2)
        if not cols:
            return
        for c in cols:
            if (r, c) not in self.cells:
                self.cells[(r, c)] = (role, table)
        self.row_roles.append(
            {
                "row": r,
                "columns": [c1, c2],
                "role": role,
                "table_id": table,
                "reason": reason or ROLE_REASONS.get(role, ""),
            }
        )

    def run(self) -> SheetSegmentation:
        rows = sorted(self.sheet.by_row)
        if rows:
            for c1, c2 in _column_bands(self.sheet):
                self.segment_band(rows[0], rows[-1], c1, c2, allow_split=True)
        for (r, c), _value in self.sheet.cells.items():
            if (r, c) not in self.cells:
                self.cells[(r, c)] = ("note", "")
                self.row_roles.append(
                    {
                        "row": r,
                        "columns": [c, c],
                        "role": "note",
                        "table_id": "",
                        "reason": ROLE_REASONS["note"],
                    }
                )
        first_leaf: dict[str, int] = {}
        representatives: list[tuple[str, str, set[str]]] = []
        for table in sorted(self.tables, key=lambda t: (t.leaf_row, t.min_col)):
            keys = [k for k in table.signature.split("|") if k]
            lead, key_set = (keys[0] if keys else ""), set(keys)
            table.group = next(
                (
                    group
                    for group, group_lead, group_keys in representatives
                    if group_lead == lead
                    and len(key_set & group_keys) * 5 >= max(len(key_set | group_keys), 1) * 4
                ),
                "",
            )
            if not table.group:
                table.group = table.signature
                representatives.append((table.group, lead, key_set))
            if first_leaf.setdefault(table.group, table.leaf_row) != table.leaf_row:
                table.repeated = True
                for r in table.header_rows:
                    for c in self.sheet.row_cols(r, table.min_col, table.max_col):
                        self.cells[(r, c)] = ("repeated_header", table.table_id)
                for item in self.row_roles:
                    if item["table_id"] == table.table_id and item["role"] in {
                        "header",
                        "parent_header",
                    }:
                        item["role"] = "repeated_header"
                        item["reason"] = ROLE_REASONS["repeated_header"]
        self.row_roles.sort(key=lambda item: (item["row"], item["columns"][0]))
        return SheetSegmentation(self.name, self.tables, self.cells, self.row_roles)

    def _next_rows(
        self, r: int, end: int, c1: int, c2: int, limit: int = 3
    ) -> list[tuple[int, str]]:
        found: list[tuple[int, str]] = []
        for nr in range(r + 1, end + 1):
            kind = _row_kind(self.sheet, nr, c1, c2)
            if kind == "blank":
                continue
            found.append((nr, kind))
            if len(found) >= limit:
                break
        return found

    def _leads_to_header(self, r: int, end: int, c1: int, c2: int) -> bool:
        for nr, kind in self._next_rows(r, end, c1, c2):
            if kind in {"header", "day_header"}:
                return True
            if kind in {"weekday_header", "form_info", "banner"} or self._is_parent_of_next(
                nr, end, c1, c2
            ):
                continue
            return False
        return False

    def _is_parent_of_next(self, r: int, end: int, c1: int, c2: int) -> bool:
        if r + 1 > end:
            return False
        next_kind = _row_kind(self.sheet, r + 1, c1, c2)
        return next_kind in {"header", "day_header"} and _is_parent_row(
            self.sheet, r, r + 1, c1, c2
        )

    def _is_leaf(self, r: int, end: int, c1: int, c2: int) -> bool:
        kind = _row_kind(self.sheet, r, c1, c2)
        if kind == "day_header":
            return True
        return kind == "header" and not self._is_parent_of_next(r, end, c1, c2)

    def segment_band(self, start: int, end: int, c1: int, c2: int, *, allow_split: bool) -> None:
        r = start
        pending: list[tuple[int, str]] = []
        current: SegmentedTable | None = None
        last_data_row = 0
        while r <= end:
            kind = _row_kind(self.sheet, r, c1, c2)
            if kind == "blank":
                r += 1
                continue
            starts_table = self._is_leaf(r, end, c1, c2) or (
                kind in {"header", "weekday_header", "single", "data", "banner"}
                and self._is_parent_of_next(r, end, c1, c2)
            )
            if (
                current is not None
                and starts_table
                and kind not in {"day_header", "weekday_header"}
                and not (kind == "header" and self._matches_header(current, r))
                and (current.kind == "calendar" or last_data_row == r - 1)
                and not self._strong_header(r, end, c1, c2)
            ):
                starts_table = False
            if current is not None and starts_table and self._merge_continues(current, r):
                starts_table = False
            if starts_table:
                parents: list[int] = []
                leaf = r
                while not self._is_leaf(leaf, end, c1, c2):
                    parents.append(leaf)
                    leaf += 1
                for pr in range(leaf - 1, max(start, leaf - 3) - 1, -1):
                    if pr in parents or not _is_parent_row(self.sheet, pr, leaf, c1, c2):
                        break
                    if any(pr == p for p, _k in pending):
                        pending = [(p, k) for p, k in pending if p != pr]
                    parents.insert(0, pr)
                current = self._open_table(parents, leaf, end, c1, c2, pending)
                pending = []
                last_data_row = current.header_rows[-1]
                r = last_data_row + 1
                continue
            if current is None:
                pending.append((r, kind))
                r += 1
                continue
            role = self._body_role(current, r, kind, end, c1, c2, after_data=last_data_row == r - 1)
            if role == "close" and self._merge_continues(current, r):
                role = "note" if kind in {"banner", "form_info"} else "data"
            if role == "close":
                current = None
                continue
            if role == "data":
                last_data_row = r
                current.data_rows.append(r)
                current.end_row = max(current.end_row, r)
                self.assign(r, current.min_col, current.max_col, "data", current.table_id)
                if current.max_col < c2:
                    self.assign(r, current.max_col + 1, c2, "side_annotation", current.table_id)
                if current.min_col > c1:
                    self.assign(r, c1, current.min_col - 1, "side_annotation", current.table_id)
            else:
                self.assign(r, c1, c2, role, current.table_id)
            r += 1
        for pr, pkind in pending:
            self.assign(
                pr,
                c1,
                c2,
                "summary"
                if pkind == "summary"
                else ("form_info" if pkind == "form_info" else "note"),
            )
        self._finalize(start, end, c1, c2, allow_split)

    def _header_extension(self, leaf: int, end: int, c1: int, c2: int) -> list[int]:
        """Rows inside vertical merges that start on the leaf header row."""
        ext = max(
            (
                m[2]
                for c in self.sheet.row_cols(leaf, c1, c2)
                if (m := self.sheet.anchor_span.get((leaf, c))) and m[2] > leaf
            ),
            default=leaf,
        )
        rows: list[int] = []
        for r in range(leaf + 1, min(ext, end) + 1):
            values = [self.sheet.cells[(r, c)] for c in self.sheet.row_cols(r, c1, c2)]
            if any(not _is_label(v) for v in values):
                break
            rows.append(r)
        return rows

    def _merge_continues(self, table: SegmentedTable, r: int) -> bool:
        """A merged range that starts above ``r`` inside the table cannot be cut."""
        return any(
            m[0] < r <= m[2]
            and m[1] <= table.max_col
            and m[3] >= table.min_col
            and m[0] > table.leaf_row
            for m in self.sheet.merges
        )

    def _strong_header(self, r: int, end: int, c1: int, c2: int) -> bool:
        if _row_kind(self.sheet, r, c1, c2) != "header":
            return False
        cols = self.sheet.row_cols(r, c1, c2)
        if sum(_is_label(self.sheet.cells[(r, c)]) for c in cols) < 5:
            return False
        subs = self._header_extension(r, end, c1, c2)
        following = self._next_rows(subs[-1] if subs else r, end, c1, c2, limit=1)
        return bool(following) and any(
            _is_data_like(self.sheet.cells[(following[0][0], c)])
            for c in self.sheet.row_cols(following[0][0], c1, c2)
        )

    def _matches_header(self, table: SegmentedTable, r: int) -> bool:
        cols = self.sheet.row_cols(r, table.min_col, table.max_col)
        if len(cols) < 2:
            return False
        keys = {semantic_key(path[-1]) for path in table.header_paths if path}
        hits = sum(semantic_key(self.sheet.cells[(r, c)]) in keys for c in cols)
        return hits * 10 >= len(cols) * 7

    def _open_table(
        self,
        parents: list[int],
        leaf: int,
        end: int,
        c1: int,
        c2: int,
        pending: list[tuple[int, str]],
    ) -> SegmentedTable:
        header_rows = [*parents, leaf]
        cols = [c for r in header_rows for c in self.sheet.row_cols(r, c1, c2)]
        spans = [
            c + self.sheet.h_span(r, c) - 1
            for r in header_rows
            for c in self.sheet.row_cols(r, c1, c2)
        ]
        min_col = min(cols)
        max_col = min(c2, max(spans))
        kind = "calendar" if _row_kind(self.sheet, leaf, c1, c2) == "day_header" else "table"
        if kind == "calendar":
            min_col = c1
        title_rows: list[int] = []
        title = ""
        for pr, pkind in pending:
            if pkind in {"single", "banner"} and self._leads_to_header(pr, end, c1, c2):
                title_rows.append(pr)
                title = _text(self.sheet.cells[(pr, self.sheet.row_cols(pr, c1, c2)[0])])
        if not title:
            title = next(
                (
                    _text(self.sheet.cells[(pr, self.sheet.row_cols(pr, c1, c2)[0])])
                    for pr, pkind in reversed(pending)
                    if pkind in {"single", "banner"}
                    and _is_label(self.sheet.cells[(pr, self.sheet.row_cols(pr, c1, c2)[0])])
                ),
                "",
            )
        table_id = f"{self.name}!T{self.next_id}"
        self.next_id += 1
        for pr, pkind in pending:
            if pr in title_rows:
                role = "title"
            elif pkind == "form_info":
                role = "form_info"
            elif pkind == "summary":
                role = "summary"
            else:
                role = "preamble"
            self.assign(pr, c1, c2, role, table_id)
        subs = self._header_extension(leaf, end, min_col, max_col)
        headers, paths = _header_paths(self.sheet, parents, leaf, min_col, max_col, subs)
        table = SegmentedTable(
            table_id=table_id,
            min_col=min_col,
            max_col=max_col,
            title_rows=title_rows,
            header_rows=[*header_rows, *subs],
            leaf_row=leaf,
            headers=headers,
            header_paths=paths,
            end_row=max(
                leaf + len(subs),
                self.sheet.v_merge_end(leaf + len(subs) + 1, min_col, max_col)
                if leaf + len(subs) < end
                else leaf,
            ),
            kind=kind,
            title=title,
        )
        for r in parents:
            self.assign(r, c1, c2, "parent_header", table_id)
        for hr in (leaf, *subs):
            self.assign(hr, min_col, max_col, "header", table_id)
            if max_col < c2:
                self.assign(hr, max_col + 1, c2, "side_annotation", table_id)
            if min_col > c1:
                self.assign(hr, c1, min_col - 1, "side_annotation", table_id)
        self.tables.append(table)
        return table

    def _body_role(
        self,
        table: SegmentedTable,
        r: int,
        kind: str,
        end: int,
        c1: int,
        c2: int,
        *,
        after_data: bool,
    ) -> str:
        if kind == "header" and self._matches_header(table, r):
            return "close"
        if kind in {"day_header", "weekday_header"}:
            return "close"
        if kind in {"header", "data"}:
            if self._is_note_row(table, r):
                return "note"
            if table.kind == "calendar" or after_data:
                return "data"
        if kind == "header" and self._leads_or_is_header(r, end, c1, c2):
            return "close"
        if kind == "banner":
            return "close" if self._leads_to_header(r, end, c1, c2) else "note"
        if kind == "single":
            if self._leads_to_header(r, end, c1, c2):
                return "close"
            c = self.sheet.row_cols(r, c1, c2)[0]
            value = self.sheet.cells[(r, c)]
            text = _text(value)
            if c > table.max_col or c < table.min_col:
                return "side_annotation"
            wide = self.sheet.h_span(r, c) * 2 > (table.max_col - table.min_col + 1)
            if _is_data_like(value) and not wide:
                return "data"
            if wide or len(text) > 12 or _NOTE_RE.match(text) or c != table.min_col:
                return "note"
            return "data"
        if kind == "summary":
            return "summary"
        if kind == "form_info":
            return "form_info"
        if not self.sheet.row_cols(r, table.min_col, table.max_col):
            return "side_annotation"
        return "data"

    def _is_note_row(self, table: SegmentedTable, r: int) -> bool:
        cols = self.sheet.row_cols(r, table.min_col, table.max_col)
        if not cols:
            return False
        width = table.max_col - table.min_col + 1
        values = [self.sheet.cells[(r, c)] for c in cols]
        texts = [_text(value) for value in values]
        if len(cols) <= 2 and _NOTE_RE.match(texts[0]):
            return True
        if any(
            self.sheet.h_span(r, c) * 2 > width and not _is_data_like(value)
            for c, value in zip(cols, values)
        ):
            return True
        return not any(_is_data_like(value) for value in values) and max(map(len, texts)) > 30

    def _leads_or_is_header(self, r: int, end: int, c1: int, c2: int) -> bool:
        return self._is_leaf(r, end, c1, c2) or self._is_parent_of_next(r, end, c1, c2)

    def _finalize(self, start: int, end: int, c1: int, c2: int, allow_split: bool) -> None:
        band_tables = [
            t
            for t in self.tables
            if t.min_col >= c1 and t.max_col <= c2 and start <= t.leaf_row <= end
        ]
        for table in band_tables:
            self._apply_anchor_filter(table)
        if not allow_split:
            return
        prev_end = start - 1
        for table in sorted(band_tables, key=lambda t: t.leaf_row):
            first_row, last_row = prev_end + 1, max(table.end_row, table.leaf_row)
            prev_end = max(prev_end, last_row)
            bounds = _periodic_split(self.sheet, table.leaf_row, table.min_col, table.max_col)
            if len(bounds) < 2 or self._crosses_header_merge(table, bounds):
                continue
            self.tables.remove(table)
            lo, hi = table.min_col, table.max_col
            for r in range(first_row, last_row + 1):
                for c in self.sheet.row_cols(r, lo, hi):
                    self.cells.pop((r, c), None)
            self.row_roles = [
                item
                for item in self.row_roles
                if not (
                    first_row <= item["row"] <= last_row
                    and item["columns"][0] <= hi
                    and item["columns"][1] >= lo
                )
            ]
            for b1, b2 in bounds:
                self.segment_band(first_row, last_row, b1, b2, allow_split=False)

    def _crosses_header_merge(self, table: SegmentedTable, bounds: list[tuple[int, int]]) -> bool:
        edges = {b1 for b1, _b2 in bounds[1:]}
        return any(
            m[1] < edge <= m[3]
            for (r, _c), m in self.sheet.anchor_span.items()
            if r in table.header_rows
            for edge in edges
        )

    def _apply_anchor_filter(self, table: SegmentedTable) -> None:
        if len(table.data_rows) < 5 or table.kind == "calendar":
            return
        fill: Counter[int] = Counter()
        for r in table.data_rows:
            for c in range(table.min_col, table.max_col + 1):
                if self.sheet.value(r, c, through_merge=True) is not None:
                    fill[c] += 1
        anchors = [c for c, n in fill.items() if n * 100 >= len(table.data_rows) * 95]
        if not anchors:
            return
        kept: list[int] = []
        for r in table.data_rows:
            if any(self.sheet.value(r, c, through_merge=True) is not None for c in anchors):
                kept.append(r)
                continue
            for c in self.sheet.row_cols(r, table.min_col, table.max_col):
                self.cells[(r, c)] = ("out_of_schema", table.table_id)
            for item in self.row_roles:
                if (
                    item["row"] == r
                    and item["table_id"] == table.table_id
                    and item["role"] == "data"
                ):
                    item["role"] = "out_of_schema"
                    item["reason"] = ROLE_REASONS["out_of_schema"]
        table.data_rows = kept


def segment_sheet(sheet_name: str, cells: Grid, merges: list[Merge]) -> SheetSegmentation:
    """Segment one sheet. ``cells`` maps 1-based (row, col) to raw values."""
    return _Segmenter(_Sheet(cells, merges), sheet_name).run()


def worksheet_grid(worksheet: Any) -> tuple[Grid, list[Merge]]:
    """Read non-empty values and merged ranges from an openpyxl worksheet."""
    store = getattr(worksheet, "_cells", None)
    if isinstance(store, dict):
        cells = {
            key: cell.value
            for key, cell in store.items()
            if cell.value is not None and _text(cell.value)
        }
    else:
        cells = {
            (cell.row, cell.column): cell.value
            for row in worksheet.iter_rows()
            for cell in row
            if cell.value is not None and _text(cell.value)
        }
    merges = [
        (m.min_row, m.min_col, m.max_row, m.max_col)
        for m in getattr(getattr(worksheet, "merged_cells", None), "ranges", ())
    ]
    return cells, merges


def review_grid(review: dict, sheet: str) -> tuple[Grid, list[Merge]]:
    """Build the same grid from ``inspect_workbook`` output (string values)."""
    from openpyxl.utils.cell import column_index_from_string, coordinate_from_string

    from app.application.reviewed_excel_evidence import bounded_range

    cells: Grid = {}
    for cell in review.get("cells", []):
        if cell.get("sheet") != sheet:
            continue
        column, row = coordinate_from_string(cell["cell"])
        cells[(row, column_index_from_string(column))] = cell.get("value")
    overview: dict[str, Any] = next(
        (item for item in review.get("sheet_overview", []) if item.get("sheet") == sheet), {}
    )
    merges = []
    for ref in overview.get("merged_regions", []) or []:
        c1, r1, c2, r2 = bounded_range(ref)
        merges.append((r1, c1, r2, c2))
    return cells, merges


__all__ = [
    "EXCLUDED_ROLES",
    "ROLE_REASONS",
    "SegmentedTable",
    "SheetSegmentation",
    "review_grid",
    "segment_sheet",
    "worksheet_grid",
]
