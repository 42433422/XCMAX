"""Disposable native-cell pages using stdlib JSON, zlib and sorted coordinate indexes.

Only the application may retain an index after current snapshot authorization.
The original workbook remains authoritative; an index never grants file access.
"""

from __future__ import annotations

import json
import sys
import zlib
from array import array
from bisect import bisect_left, bisect_right
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

PAGE_BYTE_BUDGET = 40_000
_BLOCK_CELLS = 128
_BLOCK_BYTES = 128 * 1024


def _encode(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


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

    @property
    def size_bytes(self) -> int:
        return (
            sys.getsizeof(self)
            + sum(
                sys.getsizeof(value)
                for value in (self.rows, self.columns, self.sizes, self.starts, self.blocks)
            )
            + self.block_storage_bytes
            + sys.getsizeof(self.block_storage_bytes)
        )

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
        return result


def project_workbook_page(
    source: dict[str, Any] | WorkbookPageIndex,
    *,
    view: str,
    sheet_name: str | None,
    bounds: tuple[int, int, int, int] | None,
    offset: int,
    limit: int,
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
        else:
            values = next(item["cells"] for item in source["sheets"] if item["sheet"] == sheet_name)
            read = values.__getitem__
            size = lambda position: len(_encode(values[position]))
            column = lambda position: values[position]["column"]
            start, end = 0, len(values)
            if bounds:
                start = bisect_left(values, bounds[1], key=lambda cell: cell["row"])
                end = bisect_right(values, bounds[3], key=lambda cell: cell["row"])
        if bounds:
            # Count on compact coordinates; retain only this page's positions.
            # No full list of matching cell objects or decoded JSON is built.
            positions, total = [], 0
            for position in range(start, end):
                if bounds[0] <= column(position) <= bounds[2]:
                    if offset <= total < offset + limit:
                        positions.append(position)
                    total += 1
        else:
            total = end - start
            positions = range(start + offset, min(start + offset + limit, end))
    page: list[dict[str, Any]] = []
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
