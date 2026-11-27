"""Excel ETL OCR 桥接：扫描件/图片/PDF → 网格表 → 临时 xlsx → 走通用解析。

不硬编码送货单版式；OCR 只负责还原单元格，列映射仍由 universal/KB/LLM 完成。
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, BinaryIO

from app.application import shipment_excel_elt_security as elt_security
from app.utils.elt_env import elt_getenv
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
_PDF_SUFFIXES = {".pdf"}


def is_ocr_source(path: str | Path) -> bool:
    suffix = Path(path).suffix.lower()
    return suffix in _IMAGE_SUFFIXES or suffix in _PDF_SUFFIXES


def _cluster_axis(values: list[float], *, threshold: float) -> list[float]:
    if not values:
        return []
    ordered = sorted(values)
    clusters: list[list[float]] = [[ordered[0]]]
    for value in ordered[1:]:
        if abs(value - clusters[-1][-1]) <= threshold:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    return [sum(c) / len(c) for c in clusters]


def text_blocks_to_grid(
    blocks: list[dict[str, Any]],
    *,
    row_threshold: float | None = None,
    col_threshold: float | None = None,
) -> list[list[str]]:
    """将带坐标文本块聚类为二维表格（行优先、列从左到右）。"""
    cleaned: list[dict[str, Any]] = []
    for raw in blocks or []:
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        if "center" in raw and isinstance(raw.get("center"), (tuple, list)):
            cx, cy = float(raw["center"][0]), float(raw["center"][1])
        else:
            left = float(raw.get("left") or 0)
            top = float(raw.get("top") or 0)
            width = float(raw.get("width") or 0)
            height = float(raw.get("height") or 0)
            cx = left + width / 2.0
            cy = float(raw.get("y_center") or (top + height / 2.0))
        cleaned.append({"text": text, "cx": cx, "cy": cy})
    if not cleaned:
        return []

    ys = [b["cy"] for b in cleaned]
    xs = [b["cx"] for b in cleaned]
    y_span = max(ys) - min(ys) if ys else 1.0
    x_span = max(xs) - min(xs) if xs else 1.0
    row_th = float(row_threshold if row_threshold is not None else max(18.0, y_span * 0.03))
    col_th = float(col_threshold if col_threshold is not None else max(24.0, x_span * 0.04))

    row_centers = _cluster_axis(ys, threshold=row_th)
    col_centers = _cluster_axis(xs, threshold=col_th)
    if not row_centers or not col_centers:
        return []

    grid: list[list[str]] = [["" for _ in col_centers] for _ in row_centers]
    for block in cleaned:
        r = min(range(len(row_centers)), key=lambda i: abs(row_centers[i] - block["cy"]))
        c = min(range(len(col_centers)), key=lambda i: abs(col_centers[i] - block["cx"]))
        prev = grid[r][c]
        grid[r][c] = f"{prev} {block['text']}".strip() if prev else block["text"]
    # 去掉全空行
    return [row for row in grid if any(str(cell).strip() for cell in row)]


def _workbook_output_path(output_path: str | Path | None) -> Path:
    if output_path:
        raw_output_path = output_path
    else:
        from app.utils.path_io.path_utils import get_app_data_dir

        temp_root = Path(get_app_data_dir()) / "temp_excel"
        temp_root.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(prefix="elt_ocr_", suffix=".xlsx", dir=temp_root)
        os.close(descriptor)
        raw_output_path = Path(temp_name)
    return elt_security.resolve_elt_output_path(raw_output_path)


def grid_to_workbook_path(
    grid: list[list[str]],
    *,
    output_path: str | Path | None = None,
    sheet_name: str = "OCR",
    meta_lines: list[str] | None = None,
) -> Path:
    from openpyxl import Workbook

    path = _workbook_output_path(output_path)
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = (sheet_name or "OCR")[:31]
    row_idx = 1
    for line in meta_lines or []:
        text = str(line or "").strip()
        if not text:
            continue
        ws.cell(row_idx, 1, text).data_type = "s"
        row_idx += 1
    for row in grid:
        for col, value in enumerate(row, start=1):
            ws.cell(row_idx, col, value).data_type = "s"
        row_idx += 1
    with elt_security.open_elt_output_file(path) as output_file:
        wb.save(output_file)
    wb.close()
    return path


def _table_sheet_name(sheet_name: str, index: int) -> str:
    suffix = f"_{index}"
    return f"{(sheet_name or 'OCR')[:31 - len(suffix)]}{suffix}"


def tables_to_workbook_path(
    tables: list[Any],
    *,
    output_path: str | Path | None = None,
    sheet_name: str = "OCR",
    meta_lines: list[str] | None = None,
) -> Path:
    """Write each recognized table to its own sheet and keep merge ranges."""
    from openpyxl import Workbook

    path = _workbook_output_path(output_path)
    base_name = sheet_name or "OCR"
    wb = Workbook()
    default_sheet = wb.active
    assert default_sheet is not None
    wb.remove(default_sheet)
    for index, table in enumerate(tables, start=1):
        ws = wb.create_sheet(_table_sheet_name(base_name, index))
        row_idx = 1
        lines = meta_lines if index == 1 and meta_lines is not None else table.meta_lines
        for line in lines or []:
            text = str(line or "").strip()
            if not text:
                continue
            ws.cell(row_idx, 1, text).data_type = "s"
            row_idx += 1
        grid_start = row_idx
        for row in table.grid:
            for col, value in enumerate(row, start=1):
                ws.cell(row_idx, col, value).data_type = "s"
            row_idx += 1
        for min_row, min_col, max_row, max_col in table.merges:
            ws.merge_cells(
                start_row=grid_start + min_row - 1,
                start_column=min_col,
                end_row=grid_start + max_row - 1,
                end_column=max_col,
            )
    if not wb.worksheets:
        wb.create_sheet(base_name[:31])
    with elt_security.open_elt_output_file(path) as output_file:
        wb.save(output_file)
    wb.close()
    return path


class OcrInputLimitError(ValueError):
    """An input exceeds the explicitly supported OCR processing budget."""


def _load_image_arrays(
    source: BinaryIO | Path, *, suffix: str | None = None, strict_limits: bool = False,
    page_indices: list[int] | None = None,
) -> list[Any]:
    """从已安全打开的输入流读取图像；Path 调用也经安全句柄打开。"""
    if isinstance(source, Path):
        source_suffix = suffix or source.suffix.lower()
        with elt_security.open_elt_input_file(source) as input_stream:
            return _load_image_arrays(
                input_stream, suffix=source_suffix, strict_limits=strict_limits,
                page_indices=page_indices,
            )
    if not suffix:
        raise ValueError("suffix is required when loading an OCR stream")
    max_pixels = 16_000_000
    max_pages = min(20, max(1, int(elt_getenv("FHD_EXCEL_ELT_OCR_MAX_PAGES") or 5)))
    max_total_pixels = 32_000_000
    if suffix in _IMAGE_SUFFIXES:
        import numpy as np
        from PIL import Image, ImageSequence

        with Image.open(source) as image:
            if not strict_limits:
                return [np.array(image.convert("RGB"))]
            if getattr(image, "n_frames", 1) > max_pages:
                raise OcrInputLimitError("ocr_page_limit")
            pages = []
            for frame in ImageSequence.Iterator(image):
                if frame.width * frame.height > max_pixels:
                    raise OcrInputLimitError("ocr_pixel_limit")
                if sum(page.shape[0] * page.shape[1] for page in pages) + frame.width * frame.height > max_total_pixels:
                    raise OcrInputLimitError("ocr_total_pixel_limit")
                pages.append(np.array(frame.convert("RGB")))
            return pages

    if suffix in _PDF_SUFFIXES:
        # 优先 pypdfium2（轻）；否则 pdf2image
        try:
            import numpy as np
            import pypdfium2 as pdfium

            source.seek(0)
            pdf = pdfium.PdfDocument(source)
            try:
                pages = []
                if strict_limits and len(pdf) > max_pages:
                    raise OcrInputLimitError("ocr_page_limit")
                selected = page_indices if page_indices is not None else range(min(len(pdf), max_pages))
                for i in selected:
                    page = pdf[i]
                    try:
                        pixels = page.get_width() * page.get_height() * 4
                        if strict_limits and pixels > max_pixels:
                            raise OcrInputLimitError("ocr_pixel_limit")
                        if strict_limits and (
                            sum(item.shape[0] * item.shape[1] for item in pages) + pixels > max_total_pixels
                        ):
                            raise OcrInputLimitError("ocr_total_pixel_limit")
                        bitmap = page.render(scale=2)
                        try:
                            pages.append(np.array(bitmap.to_pil().convert("RGB")))
                        finally:
                            bitmap.close()
                    finally:
                        page.close()
                return pages
            finally:
                pdf.close()
        except OcrInputLimitError:
            raise
        except RECOVERABLE_ERRORS:
            if strict_limits or page_indices is not None:
                # Do not let the compatibility renderer bypass the strict budget.
                raise
            logger.debug("pypdfium2 pdf render unavailable", exc_info=True)
        try:
            import numpy as np
            from pdf2image import convert_from_bytes

            source.seek(0)
            images = convert_from_bytes(source.read(), first_page=1, last_page=max_pages)
            return [np.array(img.convert("RGB")) for img in images]
        except RECOVERABLE_ERRORS as exc:
            raise RuntimeError("PDF OCR 依赖不可用（需 pypdfium2 或 pdf2image）") from exc

    raise RuntimeError(f"不支持的 OCR 源类型: {suffix}")


def _native_pdf_candidates(source: BinaryIO) -> tuple[int | None, dict[int, Any]]:
    """Route native-only table pages using the existing pdfplumber component.

    A page with raster content, no native table, or incomplete native parsing is
    left to the OCR adapter. Native cell geometry is PDF points, not OCR pixels.
    """
    from app.application.elt.table_structure_ocr import PageStructure, TableGrid

    try:
        import pdfplumber
    except ImportError:
        return None, {}
    reports = {}
    max_pages = min(20, max(1, int(elt_getenv("FHD_EXCEL_ELT_OCR_MAX_PAGES") or 5)))
    source.seek(0)
    with pdfplumber.open(source) as pdf:
        count = len(pdf.pages)
        if count > max_pages:
            raise OcrInputLimitError("ocr_page_limit")
        for number, page in enumerate(pdf.pages, start=1):
            try:
                if page.images or not (page.extract_text() or "").strip():
                    continue
                candidates = []
                for index, table in enumerate(page.find_tables()):
                    rows = table.extract()
                    if not rows or not any(row for row in rows):
                        continue
                    grid = [["" if cell is None else str(cell) for cell in row] for row in rows]
                    if sum(len(row) for row in grid) > 250_000:
                        raise OcrInputLimitError("ocr_native_grid_limit")
                    candidates.append(TableGrid(
                        grid=grid,
                        page=number,
                        index=index,
                        bbox=list(table.bbox),
                        cell_boxes=[list(box) for box in table.cells],
                        native_missing_cells=[
                            (row_index, col_index)
                            for row_index, row in enumerate(rows, start=1)
                            for col_index, cell in enumerate(row, start=1)
                            if cell is None
                        ],
                    ))
                if candidates:
                    blocks = [{
                        "text": word["text"],
                        "left": word["x0"], "top": word["top"],
                        "width": word["x1"] - word["x0"],
                        "height": word["bottom"] - word["top"],
                        "confidence": None,
                        "coordinate_space": "pdf_points_top_left",
                    } for word in page.extract_words()]
                    reports[number] = PageStructure(
                        number, "native_candidate", tables=candidates, blocks=blocks,
                        coordinate_space="pdf_points_top_left",
                        page_size=(float(page.width), float(page.height)),
                        reason="native_merges_unverified",
                    )
            except OcrInputLimitError:
                raise
            except RECOVERABLE_ERRORS:
                logger.warning("native PDF page %s unavailable; OCR route retained", number)
            finally:
                page.close()
    return count, reports


def ocr_source_to_workbook(
    file_path: str | Path,
    *,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """扫描件/图片/PDF → 临时 xlsx。"""
    try:
        path = elt_security.resolve_elt_path(file_path)
    except elt_security.ShipmentEltPathError:
        return {"success": False, "message": "非法输入路径", "error_code": "unsafe_path"}
    if not is_ocr_source(path):
        return {
            "success": False,
            "message": f"不是 OCR 源（支持图片/PDF）: {path.suffix}",
            "error_code": "not_ocr_source",
        }

    try:
        from app.application.elt.table_structure_ocr import (
            TableGrid,
            recognize_table_pages,
            table_structure_mode,
        )
        from app.domain.shared_services.ocr_service import get_ocr_service
        from app.infrastructure.document_parsing.ocr import ocr_array_blocks

        with elt_security.open_elt_input_file(path) as source_file:
            digest = hashlib.sha256()
            for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
                digest.update(chunk)
            source_sha256 = digest.hexdigest()
            source_file.seek(0)
            native = {}
            page_count = None
            if path.suffix.lower() in _PDF_SUFFIXES:
                page_count, native = _native_pdf_candidates(source_file)
            selected = (
                [number - 1 for number in range(1, page_count + 1) if number not in native]
                if page_count is not None else None
            )
            source_file.seek(0)
            images = [] if selected == [] else _load_image_arrays(
                source_file, suffix=path.suffix.lower(), strict_limits=True,
                page_indices=selected,
            )
        page_numbers = (
            [index + 1 for index in selected] if selected is not None
            else list(range(1, len(images) + 1))
        )
        raster_by_page = dict(zip(page_numbers, images, strict=True))
        reports = sorted(
            [*native.values(), *recognize_table_pages(images, page_numbers=page_numbers)],
            key=lambda report: report.page,
        )
        tables = []
        page_evidence = []
        failures = []
        block_count = 0
        source_name = re.sub(r'[\\/*?:\[\]]', "_", path.stem)[:28] or "OCR"
        legacy_ocr = None
        for report in reports:
            image = raster_by_page.get(report.page)
            blocks = report.blocks
            candidates = report.tables if report.status in {"recognized", "native_candidate"} else []
            if not candidates:
                if table_structure_mode() == "required":
                    failures.append(report.page)
                    continue
                if image is None:
                    failures.append(report.page)
                    continue
                blocks = blocks or ocr_array_blocks(image)
                backend = "rapidocr" if blocks and not report.blocks else "pp-structure-v3-text"
                if not blocks:
                    if legacy_ocr is None:
                        legacy_ocr = get_ocr_service()
                    blocks = legacy_ocr.recognize_text_blocks(image) or []
                    backend = getattr(legacy_ocr, "get_active_ocr_backend", lambda: "unknown")()
                # Only blocks with genuine coordinates may enter the old clustering fallback.
                positioned = [
                    block for block in blocks if block.get("center") is not None
                    or all(key in block for key in ("left", "top", "width", "height"))
                ]
                grid = text_blocks_to_grid(positioned)
                if not grid:
                    failures.append(report.page)
                    continue
                candidates = [TableGrid(grid=grid, page=report.page)]
                status = "partial"
            else:
                backend = "pdfplumber" if report.status == "native_candidate" else "pp-structure-v3"
                status = "partial" if report.status == "native_candidate" else "candidate"
            block_count += len(blocks)
            image_sha256 = hashlib.sha256(memoryview(image)).hexdigest() if image is not None else None
            for table in candidates:
                tables.append(table)
                page_evidence.append({
                    "sheet_name": _table_sheet_name(source_name, len(tables)),
                    "page_number": report.page,
                    "table_index": table.index,
                    "source_sha256": source_sha256,
                    "image_sha256": image_sha256,
                    "image_width": int(image.shape[1]) if image is not None else None,
                    "image_height": int(image.shape[0]) if image is not None else None,
                    "page_size": report.page_size,
                    "coordinate_space": report.coordinate_space,
                    "structure_status": status,
                    "structure_backend_status": report.status,
                    "structure_reason": report.reason,
                    "backend": backend,
                    "bbox": table.bbox,
                    "cell_boxes": table.cell_boxes,
                    "cell_box_coordinate_space": (
                        report.coordinate_space if backend == "pdfplumber" else "backend_reported_unknown"
                    ),
                    "native_missing_cells": table.native_missing_cells,
                    "table_ocr_blocks": table.table_ocr_blocks,
                    "source_html": table.source_html,
                    "merges": table.merges,
                    "blocks": blocks,
                    "data_start_row": len(table.meta_lines) + 1,
                })
        if failures or not tables:
            return {
                "success": False,
                "message": "OCR 未取得全部页面的表格候选；不能静默丢页",
                "error_code": "ocr_incomplete_pages",
                "failed_pages": failures,
                "pages": page_evidence,
                "source_sha256": source_sha256,
                "structure_status": "blocked",
            }
        xlsx = tables_to_workbook_path(tables, output_path=output_path, sheet_name=source_name)
        partial = any(page["structure_status"] == "partial" for page in page_evidence)
        return {
            "success": True,
            "file_path": str(xlsx),
            "source_path": str(path),
            "source_sha256": source_sha256,
            "structure_status": "partial" if partial else "candidate",
            "requires_confirmation": True,
            "pages": page_evidence,
            "block_count": block_count,
            "backend": "mixed" if len({page["backend"] for page in page_evidence}) > 1 else page_evidence[0]["backend"],
            "row_count": sum(len(table.grid) for table in tables),
            "col_count": max((len(row) for table in tables for row in table.grid), default=0),
            "meta_lines": [line for table in tables for line in table.meta_lines],
            "message": f"OCR 已生成待核对表格候选 {xlsx.name}",
        }
    except OcrInputLimitError as exc:
        return {
            "success": False,
            "message": "OCR 输入超过页面或像素预算；请拆分后重试",
            "error_code": str(exc),
            "structure_status": "blocked",
        }
    except FileNotFoundError:
        return {"success": False, "message": f"文件不存在: {path}", "error_code": "missing_file"}
    except elt_security.ShipmentEltPathError:
        return {"success": False, "message": "非法输入路径", "error_code": "unsafe_path"}
    except RECOVERABLE_ERRORS:
        logger.exception("ocr_source_to_workbook failed")
        return {"success": False, "message": "OCR 失败", "error_code": "ocr_failed"}


def parse_ocr_document(
    file_path: str | Path,
    *,
    include_ledger: bool | str = "auto",
    unit_name_hint: str | None = None,
    profile_id: str | None = None,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """OCR 源文件 → 解析 notes（内部先转 xlsx）。"""
    from app.application.shipment_excel_elt_app_service import parse_delivery_notes
    from app.application.shipment_excel_elt_security import (
        ShipmentEltPathError,
        resolve_elt_output_path,
        resolve_elt_path,
    )

    try:
        src = resolve_elt_path(file_path, workspace_root=workspace_root, must_exist=True)
    except ShipmentEltPathError:
        return {
            "success": False,
            "message": "非法文件路径",
            "error_code": "unsafe_path",
            "notes": [],
        }

    from app.utils.path_io.path_utils import get_app_data_dir

    temp_root = Path(get_app_data_dir()) / "temp_excel"
    temp_root.mkdir(parents=True, exist_ok=True)
    out_dir = Path(tempfile.mkdtemp(prefix="elt_ocr_out_", dir=temp_root))
    try:
        out_xlsx = resolve_elt_output_path(
            out_dir / f"{src.stem}_ocr.xlsx",
            workspace_root=workspace_root or out_dir,
        )
    except ShipmentEltPathError:
        out_xlsx = out_dir / f"{src.stem}_ocr.xlsx"

    ocr_result = ocr_source_to_workbook(src, output_path=out_xlsx)
    if not ocr_result.get("success"):
        return {**ocr_result, "notes": [], "ocr": ocr_result}

    parsed = parse_delivery_notes(
        ocr_result["file_path"],
        include_ledger=include_ledger,
        unit_name_hint=unit_name_hint or src.stem,
        profile_id=profile_id,
        allow_ocr=False,
    )
    return {
        **parsed,
        "ocr": ocr_result,
        "source_kind_input": "ocr",
        "source_path": str(src),
        "message": f"OCR→解析：{parsed.get('message')}",
    }


__all__ = [
    "grid_to_workbook_path",
    "tables_to_workbook_path",
    "is_ocr_source",
    "ocr_source_to_workbook",
    "parse_ocr_document",
    "text_blocks_to_grid",
]
