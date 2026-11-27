"""Disposable native-cell pages using stdlib JSON, zlib and sorted coordinate indexes.

Only the application may retain an index after current snapshot authorization.
The original workbook remains authoritative; an index never grants file access.
"""

from __future__ import annotations

import json
import math
import sys
import zlib
from array import array
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

PAGE_BYTE_BUDGET = 40_000
_BLOCK_CELLS = 128
_BLOCK_BYTES = 128 * 1024
MAX_LOOKUP_QUERY_BYTES = 16 * 1024
_STRING_VALUE_TYPES = {"text", "rich_text", "formula", "error", "date", "datetime", "time"}
_VALUE_TYPES = _STRING_VALUE_TYPES | {"number", "boolean", "null", "unknown", "duration_seconds"}
_VALUE_STATES = {"present", "empty_string", "blank", "unknown"}


def _encode(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _value_key(value_type: str, value_state: str, value: Any) -> str:
    """Keep the native tags; normalize only the declared numeric scalar equality.

    Native ``number`` 1 and 1.0 compare equally. Decimal's exact ratio avoids
    converting large integers to float, and the native type tag separates bool.
    Formula text is indexed as text under ``formula``, never as its cached value.
    """
    scalar = value
    if value_type in {"number", "duration_seconds"} and type(value) in {int, float}:
        if type(value) is float and not math.isfinite(value):
            # Native non-finite values remain in the original facts. They cannot
            # be requested through the finite JSON scalar lookup contract.
            scalar = str(value)
        else:
            numerator, denominator = Decimal(str(value)).as_integer_ratio()
            scalar = [str(numerator), str(denominator)]
    return json.dumps([value_type, value_state, scalar], ensure_ascii=False, separators=(",", ":"))


def validate_lookup(value_match: Any, style_id: Any) -> tuple[str | None, str | None]:
    """Validate small selectors before encoding or creating any derived index."""
    if style_id is not None and (not isinstance(style_id, str) or not 1 <= len(style_id) <= 256):
        raise ValueError("invalid_native_style_id")
    if value_match is None:
        return None, style_id
    if (
        not isinstance(value_match, dict)
        or len(value_match) != 3
        or set(value_match) != {"value_type", "value_state", "value"}
    ):
        raise ValueError("invalid_native_value_match")
    value_type, state, value = (
        value_match["value_type"],
        value_match["value_state"],
        value_match["value"],
    )
    if (
        not isinstance(value_type, str)
        or value_type not in _VALUE_TYPES
        or not isinstance(state, str)
        or state not in _VALUE_STATES
    ):
        raise ValueError("invalid_native_value_match")
    # Check character/bit lengths before allocating JSON/Decimal copies. UTF-8
    # accounting below is bounded by this first check, including non-ASCII text.
    if (isinstance(value, str) and len(value) > MAX_LOOKUP_QUERY_BYTES) or (
        type(value) is int and value.bit_length() > 4096
    ):
        raise ValueError("native_lookup_query_budget_exceeded")
    valid = (
        (
            value is None
            and (
                (value_type == "null" and state == "blank")
                or (value_type in {"unknown", "formula"} and state == "unknown")
            )
        )
        or (
            value_type in _STRING_VALUE_TYPES
            and isinstance(value, str)
            and state == ("empty_string" if value == "" else "present")
        )
        or (value_type == "boolean" and type(value) is bool and state == "present")
        or (
            value_type in {"number", "duration_seconds"}
            and type(value) in {int, float}
            and (type(value) is int or math.isfinite(value))
            and state == "present"
        )
    )
    if not valid:
        raise ValueError("invalid_native_value_match")
    try:
        if len(_encode(value_match)) > MAX_LOOKUP_QUERY_BYTES:
            raise ValueError("native_lookup_query_budget_exceeded")
        return _value_key(value_type, state, value), style_id
    except (OverflowError, ArithmeticError) as exc:
        raise ValueError("invalid_native_value_match") from exc


def _metadata(document: dict[str, Any]) -> dict[str, Any]:
    return {
        **{
            key: document.get(key)
            for key in ("schema_version", "document_id", "source_ref", "status", "warnings")
        },
        "sheets": [
            {
                "sheet_id": sheet["sheet_id"],
                "sheet": sheet["sheet"],
                "sheet_state": sheet["sheet_state"],
                "cell_count": len(sheet["cells"]),
                "rows": sheet.get("max_row"),
                "columns": sheet.get("max_column"),
                "content_range": sheet.get("content_range"),
                "status": sheet.get("status"),
            }
            for sheet in document["sheets"]
        ],
    }


class _IndexBudgetExceeded(ValueError):
    pass


@dataclass(slots=True)
class _CellIndex:
    rows: array[int] = field(default_factory=lambda: array("I"))
    columns: array[int] = field(default_factory=lambda: array("I"))
    sizes: array[int] = field(default_factory=lambda: array("I"))
    starts: array[int] = field(default_factory=lambda: array("I"))
    blocks: list[bytes] = field(default_factory=list)
    block_storage_bytes: int = 0
    value_postings: dict[str, array[int]] = field(default_factory=dict)
    style_postings: dict[str, array[int]] = field(default_factory=dict)
    posting_storage_bytes: int = 0
    postings_complete: bool = False

    @property
    def size_bytes(self) -> int:
        return (
            sys.getsizeof(self)
            + sum(
                sys.getsizeof(value)
                for value in (
                    self.rows,
                    self.columns,
                    self.sizes,
                    self.starts,
                    self.blocks,
                    self.value_postings,
                    self.style_postings,
                )
            )
            + self.block_storage_bytes
            + sys.getsizeof(self.block_storage_bytes)
            + self.posting_storage_bytes
            + sys.getsizeof(self.posting_storage_bytes)
            + sys.getsizeof(self.postings_complete)
        )

    def _post(self, postings: dict[str, array[int]], key: str, position: int) -> None:
        positions = postings.get(key)
        if positions is None:
            positions = postings[key] = array("I")
            self.posting_storage_bytes += sys.getsizeof(key) + sys.getsizeof(positions)
        before = sys.getsizeof(positions)
        positions.append(position)
        self.posting_storage_bytes += sys.getsizeof(positions) - before

    def _discard_postings(self) -> None:
        self.value_postings.clear()
        self.style_postings.clear()
        self.posting_storage_bytes = 0
        self.postings_complete = False

    def build_postings(self, cells: list[dict[str, Any]], max_bytes: int) -> None:
        """Use only spare capacity after the complete coordinate index exists."""
        self._discard_postings()
        for position, cell in enumerate(cells):
            self._post(
                self.value_postings,
                _value_key(cell["value_type"], cell["value_state"], cell["value"]),
                position,
            )
            self._post(self.style_postings, cell["style_id"], position)
            if self.size_bytes > max_bytes:
                # An incomplete inverted index must never mean zero matches.
                # Keep the original coordinate/zlib cache for ordinary pages;
                # filtered pages will stream its blocks with the same matcher.
                self._discard_postings()
                return
        self.postings_complete = True

    @classmethod
    def build(cls, cells: list[dict[str, Any]], max_bytes: int) -> _CellIndex:
        index = cls()
        pieces: list[bytes] = []
        block_bytes = 2

        def flush() -> None:
            if pieces:
                index.starts.append(len(index.rows) - len(pieces))
                block = zlib.compress(b"[" + b",".join(pieces) + b"]", level=1)
                index.blocks.append(block)
                index.block_storage_bytes += sys.getsizeof(block)
                pieces.clear()
            if index.size_bytes > max_bytes:
                raise _IndexBudgetExceeded

        for cell in cells:
            encoded = _encode(cell)
            if len(encoded) + 2 > _BLOCK_BYTES:
                raise _IndexBudgetExceeded
            if (
                len(pieces) == _BLOCK_CELLS
                or block_bytes + len(encoded) + bool(pieces) > _BLOCK_BYTES
            ):
                flush()
                block_bytes = 2
            block_bytes += len(encoded) + bool(pieces)
            pieces.append(encoded)
            index.rows.append(cell["row"])
            index.columns.append(cell["column"])
            index.sizes.append(len(encoded))
        flush()
        return index

    def matches(
        self,
        start: int,
        end: int,
        value_key: str | None,
        style_id: str | None,
        read: Callable[[int], dict[str, Any]],
    ) -> Iterator[int]:
        if not self.postings_complete and (value_key is not None or style_id is not None):
            for position in range(start, end):
                cell = read(position)
                if (style_id is None or cell["style_id"] == style_id) and (
                    value_key is None
                    or _value_key(cell["value_type"], cell["value_state"], cell["value"])
                    == value_key
                ):
                    yield position
            return
        postings = []
        for mapping, key in ((self.value_postings, value_key), (self.style_postings, style_id)):
            if key is not None:
                positions = mapping.get(key)
                if positions is None:
                    return
                postings.append(positions)
        if not postings:
            yield from range(start, end)
            return
        primary = min(postings, key=len)
        others = [positions for positions in postings if positions is not primary]
        # Posting positions are appended in original row/column order. Intersect
        # without materializing a full set of matching cells or positions.
        for index in range(bisect_left(primary, start), bisect_left(primary, end)):
            position = primary[index]
            if all(
                (found := bisect_left(positions, position)) < len(positions)
                and positions[found] == position
                for positions in others
            ):
                yield position

    def reader(self) -> Callable[[int], dict[str, Any]]:
        # The one decoded block belongs to this request, never the shared cache.
        block_number = -1
        decoded: list[dict[str, Any]] = []

        def read(position: int) -> dict[str, Any]:
            nonlocal block_number, decoded
            current = bisect_right(self.starts, position) - 1
            if current != block_number:
                decoded = json.loads(zlib.decompress(self.blocks[current]))
                block_number = current
            return decoded[position - self.starts[current]]

        return read


@dataclass(slots=True)
class WorkbookPageIndex:
    metadata: bytes
    sheets: dict[str, _CellIndex]

    @property
    def size_bytes(self) -> int:
        return (
            sys.getsizeof(self)
            + sys.getsizeof(self.metadata)
            + sys.getsizeof(self.sheets)
            + sum(sys.getsizeof(name) + sheet.size_bytes for name, sheet in self.sheets.items())
        )

    @classmethod
    def build(cls, document: dict[str, Any], max_bytes: int) -> WorkbookPageIndex | None:
        result = cls(_encode(_metadata(document)), {})
        if result.size_bytes > max_bytes:
            return None
        try:
            for sheet in document["sheets"]:
                result.sheets[sheet["sheet"]] = _CellIndex.build(
                    sheet["cells"], max_bytes - result.size_bytes - sys.getsizeof(sheet["sheet"])
                )
                if result.size_bytes > max_bytes:
                    raise _IndexBudgetExceeded
        except _IndexBudgetExceeded:
            # Oversize documents still use the complete original facts for this
            # request; only optional reuse is skipped, never source content.
            return None
        # Reserve the complete original coordinate cache before considering
        # optional inverted indexes. High-cardinality values cannot evict it.
        for sheet in document["sheets"]:
            cells = result.sheets[sheet["sheet"]]
            cells.build_postings(sheet["cells"], cells.size_bytes + max_bytes - result.size_bytes)
        return result


def project_workbook_page(
    source: dict[str, Any] | WorkbookPageIndex,
    *,
    view: str,
    sheet_name: str | None,
    bounds: tuple[int, int, int, int] | None,
    offset: int,
    limit: int,
    value_key: str | None = None,
    style_id: str | None = None,
) -> dict[str, Any]:
    metadata = (
        json.loads(source.metadata)
        if isinstance(source, WorkbookPageIndex)
        else json.loads(_encode(_metadata(source)))
    )
    if metadata["status"] in {"blocked", "unsupported"}:
        raise ValueError("native_facts_blocked")
    directory = metadata.pop("sheets")
    positions: range | list[int]
    if view == "sheets":
        if value_key is not None or style_id is not None:
            raise ValueError("native_lookup_requires_cells_view")
        total = len(directory)
        positions = range(offset, min(offset + limit, total))
        read = directory.__getitem__
        size = lambda position: len(_encode(directory[position]))
    else:
        sheet = next((item for item in directory if item["sheet"] == sheet_name), None)
        if sheet is None:
            raise ValueError("native_cells_require_existing_sheet_name")
        if sheet["status"] == "unsupported":
            raise ValueError("native_sheet_unsupported")
        if isinstance(source, WorkbookPageIndex):
            cells = source.sheets[sheet["sheet"]]
            read, size = cells.reader(), cells.sizes.__getitem__
            start, end = 0, len(cells.rows)
            column = cells.columns.__getitem__
            if bounds:
                start = bisect_left(cells.rows, bounds[1])
                end = bisect_right(cells.rows, bounds[3])
            matches = cells.matches(start, end, value_key, style_id, read)
        else:
            values = next(item["cells"] for item in source["sheets"] if item["sheet"] == sheet_name)
            read = values.__getitem__
            size = lambda position: len(_encode(values[position]))
            column = lambda position: values[position]["column"]
            start, end = 0, len(values)
            if bounds:
                start = bisect_left(values, bounds[1], key=lambda cell: cell["row"])
                end = bisect_right(values, bounds[3], key=lambda cell: cell["row"])
            matches = (
                position
                for position in range(start, end)
                if (style_id is None or values[position]["style_id"] == style_id)
                and (
                    value_key is None
                    or _value_key(
                        values[position]["value_type"],
                        values[position]["value_state"],
                        values[position]["value"],
                    )
                    == value_key
                )
            )
        if bounds or value_key is not None or style_id is not None:
            # Count on compact coordinates; retain only this page's positions.
            # No full list of matching cell objects or decoded JSON is built.
            positions, total = [], 0
            for position in matches:
                if bounds is None or bounds[0] <= column(position) <= bounds[2]:
                    if offset <= total < offset + limit:
                        positions.append(position)
                    total += 1
        else:
            total = end - start
            positions = range(start + offset, min(start + offset + limit, end))
    page: list[dict[str, Any]] = []
    if (value_key is not None or style_id is not None) and offset > total:
        raise ValueError("native_lookup_offset_out_of_range")
    page_bytes = 2
    for position in positions:
        item_bytes = size(position)
        if page_bytes + item_bytes + bool(page) > PAGE_BYTE_BUDGET:
            if not page:
                raise ValueError("native_fact_exceeds_page_byte_budget")
            break
        page_bytes += item_bytes + bool(page)
        page.append(read(position))
    has_more = offset + len(page) < total
    return {
        "schema_version": metadata["schema_version"],
        "document_id": metadata["document_id"],
        "source_ref": metadata["source_ref"],
        "source_sha256": metadata["source_ref"]["source_sha256"],
        "source_status": metadata["status"],
        "partial": metadata["status"] != "complete",
        "total_items": total,
        "returned_items": len(page),
        "page_byte_budget": PAGE_BYTE_BUDGET,
        "page_bytes": page_bytes,
        "offset": offset,
        "has_more": has_more,
        "truncated": has_more,
        "next_offset": offset + len(page) if has_more else None,
        view: page,
        "warnings": metadata["warnings"] or [],
    }
