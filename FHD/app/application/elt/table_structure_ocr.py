"""Local table-structure recognition for scanned/image/PDF intake.

Uses PaddleOCR's PP-StructureV3 pipeline when it is installed with local
models.  No network API is called: when the package or its models are missing,
the caller keeps the existing text-line clustering fallback.

Environment:

* ``FHD_ETL_TABLE_STRUCTURE``: ``auto`` (default), ``off`` or ``required``.
* ``PADDLEOCR_LAYOUT_MODEL_DIR``, ``PADDLEOCR_TABLE_STRUCTURE_MODEL_DIR``,
  ``PADDLEOCR_TABLE_CLASSIFICATION_MODEL_DIR``: local PaddleX inference dirs.

The pipeline output is converted from HTML tables into a grid plus 1-based
merged ranges, which is exactly what ``cell_tidy`` and the workbook bridge
already understand.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_PIPELINE: Any | None = None
_PIPELINE_READY = False
_META_RE = re.compile(r"客户|购货|收货|联系人|日期|单号|订单|buyer|customer|date|order", re.I)
_MAX_META_LINES = 3


@dataclass(slots=True)
class TableGrid:
    grid: list[list[str]]
    merges: list[tuple[int, int, int, int]] = field(default_factory=list)
    page: int = 1
    index: int = 0
    meta_lines: list[str] = field(default_factory=list)


def table_structure_mode() -> str:
    return (os.environ.get("FHD_ETL_TABLE_STRUCTURE") or "auto").strip().lower() or "auto"


def check_table_structure_available() -> bool:
    try:
        from paddleocr import PPStructureV3  # noqa: F401
    except ImportError:
        return False
    return True


def _model_kwargs() -> dict[str, str]:
    mapping = {
        "layout_detection_model_dir": "PADDLEOCR_LAYOUT_MODEL_DIR",
        "table_structure_recognition_model_dir": "PADDLEOCR_TABLE_STRUCTURE_MODEL_DIR",
        "table_classification_model_dir": "PADDLEOCR_TABLE_CLASSIFICATION_MODEL_DIR",
        "wired_table_cell_detection_model_dir": "PADDLEOCR_WIRED_TABLE_CELL_MODEL_DIR",
        "wireless_table_cell_detection_model_dir": "PADDLEOCR_WIRELESS_TABLE_CELL_MODEL_DIR",
    }
    return {
        keyword: value
        for keyword, variable in mapping.items()
        if (value := (os.environ.get(variable) or "").strip())
    }


def _allow_download() -> bool:
    value = (os.environ.get("FHD_ETL_TABLE_STRUCTURE_ALLOW_DOWNLOAD") or "").strip().lower()
    return value in {"1", "true", "yes"}


def _build_pipeline() -> Any | None:
    from paddleocr import PPStructureV3

    model_kwargs = _model_kwargs()
    if not model_kwargs and not _allow_download():
        logger.info(
            "table structure model dirs are not configured; "
            "set PADDLEOCR_*_MODEL_DIR or FHD_ETL_TABLE_STRUCTURE_ALLOW_DOWNLOAD=1"
        )
        return None
    options: dict[str, Any] = {
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
        "use_formula_recognition": False,
        "use_seal_recognition": False,
        **model_kwargs,
    }
    try:
        return PPStructureV3(**options)
    except TypeError as exc:
        # Older 3.x releases do not accept every optional switch.
        logger.debug("PPStructureV3 rejected optional switches (%s); retrying minimal", exc)
        return PPStructureV3(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            **model_kwargs,
        )


def get_table_structure_pipeline() -> Any | None:
    """Lazily build one pipeline per process; never downloads implicitly."""
    global _PIPELINE, _PIPELINE_READY
    if table_structure_mode() == "off" or not check_table_structure_available():
        return None
    with _LOCK:
        if not _PIPELINE_READY:
            _PIPELINE_READY = True
            try:
                _PIPELINE = _build_pipeline()
            except RECOVERABLE_ERRORS:
                logger.warning("PP-StructureV3 pipeline unavailable", exc_info=True)
                _PIPELINE = None
        return _PIPELINE


def clear_table_structure_pipeline() -> None:
    global _PIPELINE, _PIPELINE_READY
    with _LOCK:
        _PIPELINE = None
        _PIPELINE_READY = False


class _TableHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[dict[str, Any]]] = []
        self._row: list[dict[str, Any]] | None = None
        self._cell: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"}:
            values = dict(attrs)
            self._cell = {
                "text": "",
                "rowspan": _span(values.get("rowspan")),
                "colspan": _span(values.get("colspan")),
            }
        elif tag == "br" and self._cell is not None:
            self._cell["text"] += " "

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None:
            if self._row is not None:
                self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def _span(value: Any) -> int:
    try:
        return max(1, int(value or 1))
    except (TypeError, ValueError):
        return 1


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def html_to_grid(markup: str) -> tuple[list[list[str]], list[tuple[int, int, int, int]]]:
    """Convert an HTML table into a rectangular grid plus 1-based merge ranges."""
    parser = _TableHtmlParser()
    parser.feed(str(markup or ""))
    parser.close()
    if not parser.rows:
        return [], []
    grid: list[list[str]] = []
    merges: list[tuple[int, int, int, int]] = []
    occupied: set[tuple[int, int]] = set()
    for row_index, row in enumerate(parser.rows):
        while len(grid) <= row_index:
            grid.append([])
        column = 0
        for cell in row:
            while (row_index, column) in occupied:
                column += 1
            rowspan, colspan = int(cell["rowspan"]), int(cell["colspan"])
            text = _clean(cell["text"])
            for offset_row in range(rowspan):
                target_row = row_index + offset_row
                while len(grid) <= target_row:
                    grid.append([])
                for offset_col in range(colspan):
                    target_col = column + offset_col
                    while len(grid[target_row]) <= target_col:
                        grid[target_row].append("")
                    grid[target_row][target_col] = (
                        text if (offset_row, offset_col) == (0, 0) else ""
                    )
                    occupied.add((target_row, target_col))
            if rowspan > 1 or colspan > 1:
                merges.append((row_index + 1, column + 1, row_index + rowspan, column + colspan))
            column += colspan
    width = max((len(columns) for columns in grid), default=0)
    for columns in grid:
        columns.extend([""] * (width - len(columns)))
    while grid and not any(cell for cell in grid[-1]):
        grid.pop()
    return grid, merges


def _payload(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    payload = getattr(value, "json", None)
    if callable(payload):
        payload = payload()
    if isinstance(payload, dict):
        return payload
    return None


def _iter_payloads(result: Any) -> list[dict[str, Any]]:
    items = result if isinstance(result, (list, tuple)) else [result]
    payloads: list[dict[str, Any]] = []
    for item in items:
        payload = _payload(item)
        if payload is None:
            continue
        nested_raw = payload.get("res")
        nested: dict[str, Any] = nested_raw if isinstance(nested_raw, dict) else payload
        payloads.append(nested)
    return payloads


def _iter_html(value: Any, depth: int = 0) -> list[str]:
    if depth > 8:
        return []
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("<") and "<table" in text.lower():
            return [text]
        return []
    if isinstance(value, dict):
        found: list[str] = []
        for key in ("pred_html", "html", "table_html"):
            if key in value:
                found.extend(_iter_html(value[key], depth + 1))
        if not found:
            for item in value.values():
                found.extend(_iter_html(item, depth + 1))
        return found
    if isinstance(value, (list, tuple)):
        found = []
        for item in value:
            found.extend(_iter_html(item, depth + 1))
        return found
    return []


def _iter_meta_lines(payload: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for block in payload.get("parsing_res_list") or []:
        if not isinstance(block, dict):
            continue
        if str(block.get("block_label") or "") not in {
            "text",
            "doc_title",
            "paragraph_title",
            "header",
        }:
            continue
        text = _clean(block.get("block_content") or block.get("content") or "")
        if text and _META_RE.search(text) and text not in lines:
            lines.append(text)
    return lines[:_MAX_META_LINES]


def recognize_table_structures(
    images: list[Any],
    *,
    pipeline: Any | None = None,
) -> list[TableGrid]:
    """Return one ``TableGrid`` per detected table; empty when unavailable."""
    if not images:
        return []
    engine = pipeline if pipeline is not None else get_table_structure_pipeline()
    if engine is None:
        return []
    tables: list[TableGrid] = []
    for page, image in enumerate(images, start=1):
        try:
            result = engine.predict(input=image)
        except TypeError as exc:
            logger.debug("PP-StructureV3 rejected 'input' keyword on page %s (%s)", page, exc)
            result = engine.predict(image)
        except BOUNDARY_ERRORS:
            # 每页独立隔离：单页识别失败只跳过该页，不让整份单据失去结构还原。
            logger.warning("PP-StructureV3 prediction failed on page %s", page, exc_info=True)
            continue
        for payload in _iter_payloads(result):
            htmls = _iter_html(payload)
            if not htmls:
                continue
            meta_lines = _iter_meta_lines(payload)
            for index, markup in enumerate(htmls):
                grid, merges = html_to_grid(markup)
                if not grid:
                    continue
                tables.append(
                    TableGrid(
                        grid=grid,
                        merges=merges,
                        page=page,
                        index=index,
                        meta_lines=meta_lines if index == 0 else [],
                    )
                )
    return tables


__all__ = [
    "TableGrid",
    "check_table_structure_available",
    "clear_table_structure_pipeline",
    "get_table_structure_pipeline",
    "html_to_grid",
    "recognize_table_structures",
    "table_structure_mode",
]
