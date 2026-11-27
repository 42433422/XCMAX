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
import math
import os
import re
import threading
from collections.abc import Iterable
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
_MAX_GRID_CELLS = 250_000
_MAX_GRID_SIDE = 10_000
_MAX_HTML_CHARS = 4_000_000


@dataclass(slots=True)
class TableGrid:
    grid: list[list[str]]
    merges: list[tuple[int, int, int, int]] = field(default_factory=list)
    page: int = 1
    index: int = 0
    meta_lines: list[str] = field(default_factory=list)
    source_html: str | None = None
    bbox: list[float] | None = None
    # Engine-reported boxes may be crop-relative. Never synthesize page positions.
    cell_boxes: list[Any] = field(default_factory=list)


@dataclass(slots=True)
class PageStructure:
    page: int
    status: str
    tables: list[TableGrid] = field(default_factory=list)
    blocks: list[dict[str, Any]] = field(default_factory=list)
    reason: str | None = None


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
    markup = str(markup or "")
    if len(markup) > _MAX_HTML_CHARS:
        raise ValueError("table_html_limit")
    parser = _TableHtmlParser()
    parser.feed(markup)
    parser.close()
    if not parser.rows:
        return [], []
    grid: list[list[str]] = []
    merges: list[tuple[int, int, int, int]] = []
    occupied: set[tuple[int, int]] = set()
    for row_index, row in enumerate(parser.rows):
        if row_index >= _MAX_GRID_SIDE:
            raise ValueError("table_grid_limit")
        while len(grid) <= row_index:
            grid.append([])
        column = 0
        for cell in row:
            while (row_index, column) in occupied:
                column += 1
            rowspan, colspan = int(cell["rowspan"]), int(cell["colspan"])
            text = _clean(cell["text"])
            if (
                row_index + rowspan > _MAX_GRID_SIDE
                or column + colspan > _MAX_GRID_SIDE
                or rowspan * colspan + len(occupied) > _MAX_GRID_CELLS
            ):
                raise ValueError("table_grid_limit")
            for offset_row in range(rowspan):
                target_row = row_index + offset_row
                while len(grid) <= target_row:
                    grid.append([])
                for offset_col in range(colspan):
                    target_col = column + offset_col
                    if (target_row, target_col) in occupied:
                        raise ValueError("overlapping_table_spans")
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
    if len(grid) * width > _MAX_GRID_CELLS:
        raise ValueError("table_grid_limit")
    for columns in grid:
        columns.extend([""] * (width - len(columns)))
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
    items = result if isinstance(result, Iterable) and not isinstance(result, (dict, str, bytes)) else [result]
    payloads: list[dict[str, Any]] = []
    for item in items:
        payload = _payload(item)
        if payload is None:
            continue
        nested_raw = payload.get("res")
        nested: dict[str, Any] = nested_raw if isinstance(nested_raw, dict) else payload
        payloads.append(nested)
    return payloads


def _sequence(value: Any) -> list[Any]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    return list(value) if isinstance(value, (list, tuple)) else []


def _numbers(value: Any) -> list[float]:
    values = _sequence(value)
    if not all(isinstance(item, (int, float)) and math.isfinite(item) for item in values):
        return []
    return [float(item) for item in values]


def _bbox(value: Any) -> list[float] | None:
    coords = _numbers(value)
    if len(coords) == 4 and coords[0] <= coords[2] and coords[1] <= coords[3]:
        return coords
    return None


def _table_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    # PP-Structure exposes the same table in table_res_list and parsing_res_list.
    # Choose one representation rather than recursively collecting duplicates.
    entries = [
        item for item in (payload.get("table_res_list") or [])
        if isinstance(item, dict)
    ]
    if entries:
        return entries
    return [
        item for item in (payload.get("parsing_res_list") or [])
        if isinstance(item, dict) and item.get("block_label") == "table"
    ]


def _page_blocks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("overall_ocr_res")
    if not isinstance(result, dict):
        return []
    texts = _sequence(result.get("rec_texts"))
    scores = _sequence(result.get("rec_scores"))
    boxes = _sequence(result.get("rec_boxes"))
    polygons = _sequence(result.get("rec_polys"))
    blocks = []
    for index, text in enumerate(texts):
        box = _bbox(boxes[index]) if index < len(boxes) else None
        polygon = (
            [_numbers(point) for point in _sequence(polygons[index])]
            if index < len(polygons) else []
        )
        score = scores[index] if index < len(scores) else None
        block: dict[str, Any] = {
            "text": str(text),
            "confidence": float(score) if isinstance(score, (int, float))
            and math.isfinite(score) and 0 <= score <= 1 else None,
            "polygon": polygon if polygon and all(len(p) == 2 for p in polygon) else None,
            "coordinate_space": "engine_input_pixels",
        }
        if box:
            x0, y0, x1, y1 = box
            block.update(left=x0, top=y0, width=x1 - x0, height=y1 - y0)
        blocks.append(block)
    return blocks


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


def recognize_table_pages(
    images: list[Any],
    *,
    pipeline: Any | None = None,
) -> list[PageStructure]:
    """Report every input page; absence/failure is not successful structure."""
    if not images:
        return []
    engine = pipeline if pipeline is not None else get_table_structure_pipeline()
    pages: list[PageStructure] = []
    for page, image in enumerate(images, start=1):
        if engine is None:
            pages.append(PageStructure(page, "unavailable", reason="structure_model_unavailable"))
            continue
        report = PageStructure(page, "not_detected")
        try:
            # Prediction can return a lazy generator; consume inside this page boundary.
            payloads = _iter_payloads(engine.predict(input=image))
            if not payloads:
                report.status = "failed"
                report.reason = "unrecognized_structure_payload"
            for payload in payloads:
                report.blocks.extend(_page_blocks(payload))
                entries = _table_entries(payload)
                meta_lines = _iter_meta_lines(payload)
                for entry in entries:
                    markup = next((
                        entry[key] for key in ("pred_html", "html", "table_html", "block_content")
                        if isinstance(entry.get(key), str) and "<table" in entry[key].lower()
                    ), None)
                    if markup is None:
                        raise ValueError("table_structure_html_missing")
                    grid, merges = html_to_grid(markup)
                    if not grid or not any(grid):
                        raise ValueError("table_structure_grid_empty")
                    index = len(report.tables)
                    report.tables.append(TableGrid(
                        grid=grid,
                        merges=merges,
                        page=page,
                        index=index,
                        meta_lines=meta_lines if index == 0 else [],
                        source_html=markup,
                        bbox=_bbox(entry.get("block_bbox")),
                        cell_boxes=[
                            _numbers(box) or [_numbers(point) for point in _sequence(box)]
                            for box in _sequence(entry.get("cell_box_list"))
                        ],
                    ))
            if report.tables and report.status != "failed":
                report.status = "recognized"
        except BOUNDARY_ERRORS:
            # The backend is an isolation boundary. Keep any earlier table evidence,
            # but never report a partly failed page as recognized.
            logger.warning("PP-StructureV3 prediction failed on page %s", page, exc_info=True)
            report.status = "failed"
            report.reason = "structure_prediction_failed"
        pages.append(report)
    return pages


def recognize_table_structures(
    images: list[Any],
    *,
    pipeline: Any | None = None,
) -> list[TableGrid]:
    """Compatibility view for callers that only need recognized tables."""
    return [
        table for page in recognize_table_pages(images, pipeline=pipeline)
        if page.status == "recognized" for table in page.tables
    ]


__all__ = [
    "PageStructure",
    "TableGrid",
    "check_table_structure_available",
    "clear_table_structure_pipeline",
    "get_table_structure_pipeline",
    "html_to_grid",
    "recognize_table_pages",
    "recognize_table_structures",
    "table_structure_mode",
]
