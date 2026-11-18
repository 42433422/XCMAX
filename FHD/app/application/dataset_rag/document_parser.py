"""Admitted document decoding and chunk segmentation."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.infrastructure.rag import SemanticChunker
from app.infrastructure.rag.semantic_chunker import Chunk
from app.utils.security.safe_download_path import resolve_under_allowed_dirs


def _pdf_ocr_enabled() -> bool:
    """扫描件 OCR 开关：XCAGI_PDF_OCR=off 关闭，其余（默认 auto）启用空页 OCR。"""
    from app.infrastructure.document_parsing.ocr import ocr_mode

    return ocr_mode() != "off"


def _table_to_markdown(rows: Any, *, max_rows: int = 200) -> str:
    """Serialize table rows to Markdown without adding a table-parsing dependency."""
    all_rows = list(rows or [])
    cleaned: list[list[str]] = []
    for row in all_rows[:max_rows]:
        cells = [" ".join(str(cell or "").split()) for cell in (row or [])]
        if any(cells):
            cleaned.append(cells)
    if not cleaned:
        return ""
    width = max(len(row) for row in cleaned)
    for row in cleaned:
        row.extend([""] * (width - len(row)))

    def escape(value: str) -> str:
        return value.replace("|", "\\|")

    lines = [
        "| " + " | ".join(escape(cell) for cell in cleaned[0]) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    for row in cleaned[1:]:
        lines.append("| " + " | ".join(escape(cell) for cell in row) + " |")
    if len(all_rows) > max_rows:
        lines.append(f"\n（表格已截断，仅保留前 {max_rows} 行）")
    return "\n".join(lines)


class DocumentParser:
    """Resolve admitted paths, decode document formats, and segment text."""

    def __init__(
        self,
        *,
        chunker: SemanticChunker,
        allowed_roots: list[Path] | None,
        default_roots: Callable[[], list[Path]],
    ) -> None:
        self._chunker = chunker
        self._allowed_roots = allowed_roots
        self._default_roots = default_roots

    def _resolve_file_path(self, file_path: str) -> Path:
        return resolve_under_allowed_dirs(file_path, self._allowed_file_roots())

    def _allowed_file_roots(self) -> list[Path]:
        if self._allowed_roots is not None:
            return [Path(root).resolve() for root in self._allowed_roots]
        return self._default_roots()

    def _extract_file_text(self, path: Path) -> tuple[str, str, dict[str, Any]]:
        """按格式路由：复杂文档优先 Docling，表格与文本保持原实现。"""
        from app.infrastructure.document_parsing.router import parse_document

        return parse_document(path, lambda: self._extract_legacy_file_text(path))

    def _extract_legacy_file_text(self, path: Path) -> tuple[str, str, dict[str, Any]]:
        if not path.exists() or not path.is_file():
            raise ValueError(f"file not found: {path}")
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return self._extract_pdf_text(path)
        if suffix == ".docx":
            return self._extract_docx_text(path)
        if suffix == ".pptx":
            return self._extract_pptx_text(path)
        if suffix in {".xlsx", ".xls"}:
            return self._extract_excel_text(path)
        if suffix in {".txt", ".md", ".csv", ".json", ".log"}:
            text, encoding = self._read_text_with_fallback(path)
            return (text, "text_file", {"extension": suffix, "encoding": encoding})
        if suffix in {".html", ".htm"}:
            from app.infrastructure.document_parsing.web_fetch import extract_html_text

            raw, encoding = self._read_text_with_fallback(path)
            text, title = extract_html_text(raw)
            metadata: dict[str, Any] = {"extension": suffix, "encoding": encoding}
            if title:
                metadata["title"] = title
            return (text, "trafilatura_html", metadata)
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            from app.infrastructure.document_parsing.ocr import ocr_image_text

            text = ocr_image_text(path).strip()
            if not text:
                raise ValueError(f"图片未识别到文字：{path.name}（需安装 rapidocr-onnxruntime）")
            return (text, "rapidocr", {"extension": suffix, "image_ocr": True})
        raise ValueError(f"unsupported document type: {suffix or '<none>'}")

    def _read_text_with_fallback(self, path: Path) -> tuple[str, str]:
        """Read text without adding chardet: UTF-8 first, then GB18030, then lossy UTF-8."""
        raw = path.read_bytes()
        for encoding in ("utf-8-sig", "gb18030", "utf-16"):
            try:
                return raw.decode(encoding), encoding
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace"), "utf-8(replace)"

    def _extract_pdf_text(self, path: Path) -> tuple[str, str, dict[str, Any]]:
        try:
            import pdfplumber
        except ImportError as exc:
            raise RuntimeError("pdfplumber is required to ingest PDF documents") from exc
        max_pages = 500
        max_tables = 50
        max_table_rows = 200
        max_ocr_pages = 30
        pages: list[str] = []
        table_count = 0
        ocr_pages: list[int] = []
        empty_pages: list[int] = []
        with pdfplumber.open(str(path)) as pdf:
            all_pages = pdf.pages
            page_count = len(all_pages)
            for index, page in enumerate(all_pages[:max_pages], start=1):
                page_text = (page.extract_text() or "").strip()
                tables: list[str] = []
                if table_count < max_tables:
                    try:
                        raw_tables = page.extract_tables() or []
                    except (ValueError, TypeError):
                        raw_tables = []
                    for rows in raw_tables:
                        if table_count >= max_tables:
                            break
                        markdown = _table_to_markdown(rows, max_rows=max_table_rows)
                        if markdown:
                            tables.append(f"[table {table_count + 1}]\n{markdown}")
                            table_count += 1
                # 扫描件兜底：文本层为空时才 OCR，避免文本版 PDF 付多余算力
                if not page_text and len(ocr_pages) < max_ocr_pages and _pdf_ocr_enabled():
                    from app.infrastructure.document_parsing.ocr import ocr_page_text

                    page_text = ocr_page_text(page).strip()
                    if page_text:
                        ocr_pages.append(index)
                if page_text or tables:
                    block = [f"[page {index}]"]
                    if page_text:
                        block.append(page_text)
                    block.extend(tables)
                    pages.append("\n".join(block))
                else:
                    empty_pages.append(index)
        if not pages:
            raise ValueError(
                "PDF 未检测到可提取文本，可能是扫描件；"
                "安装 rapidocr-onnxruntime 后会自动 OCR，或请提供文本版 PDF"
            )
        metadata: dict[str, Any] = {
            "extension": ".pdf",
            "page_count": page_count,
            "table_count": table_count,
            "pages_without_text": len(empty_pages),
            "ocr_pages": len(ocr_pages),
        }
        warnings: list[str] = []
        if page_count > max_pages:
            warnings.append(f"仅解析前 {max_pages} 页（共 {page_count} 页）")
        if len(empty_pages) > max_ocr_pages:
            warnings.append(f"OCR 仅处理前 {max_ocr_pages} 个空页")
        if empty_pages:
            warnings.append(f"{len(empty_pages)} 页未提取到文本，可能为图片页")
        if warnings:
            metadata["parser_warnings"] = warnings
        parser_backend = "pdfplumber+ocr" if ocr_pages else "pdfplumber"
        return ("\n\n".join(pages), parser_backend, metadata)

    def _extract_docx_text(self, path: Path) -> tuple[str, str, dict[str, Any]]:
        try:
            from docx import Document
        except ImportError as exc:
            raise RuntimeError("python-docx is required to ingest DOCX documents") from exc
        doc = Document(str(path))
        parts: list[str] = []
        header_count = 0
        footer_count = 0
        for section in doc.sections:
            for paragraph in section.header.paragraphs:
                text = paragraph.text.strip()
                if text:
                    parts.append(f"[页眉] {text}")
                    header_count += 1
            for paragraph in section.footer.paragraphs:
                text = paragraph.text.strip()
                if text:
                    parts.append(f"[页脚] {text}")
                    footer_count += 1
        for paragraph in doc.paragraphs:
            text = paragraph.text.strip()
            if text:
                parts.append(text)
        table_count = 0
        for table in doc.tables:
            rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
            markdown = _table_to_markdown(rows)
            if markdown:
                table_count += 1
                parts.append(f"[table {table_count}]\n{markdown}")
        return (
            "\n".join(parts),
            "python-docx",
            {
                "extension": ".docx",
                "paragraph_count": len(doc.paragraphs),
                "table_count": table_count,
                "header_paragraph_count": header_count,
                "footer_paragraph_count": footer_count,
            },
        )

    def _extract_pptx_text(self, path: Path) -> tuple[str, str, dict[str, Any]]:
        try:
            from pptx import Presentation
        except ImportError as exc:
            raise RuntimeError("python-pptx is required to ingest PPTX documents") from exc
        presentation = Presentation(str(path))
        parts: list[str] = []
        table_count = 0
        slide_count = 0

        def collect_shapes(shapes: Any, slide_index: int) -> None:
            nonlocal table_count
            for shape in shapes:
                if getattr(shape, "shape_type", None) == 6 and hasattr(shape, "shapes"):
                    collect_shapes(shape.shapes, slide_index)
                    continue
                if getattr(shape, "has_text_frame", False):
                    text = str(getattr(shape, "text", "") or "").strip()
                    if text:
                        parts.append(text)
                if getattr(shape, "has_table", False):
                    rows = [
                        [str(cell.text or "").strip() for cell in row.cells]
                        for row in shape.table.rows
                    ]
                    markdown = _table_to_markdown(rows)
                    if markdown:
                        table_count += 1
                        parts.append(f"[slide {slide_index} table {table_count}]\n{markdown}")

        for index, slide in enumerate(presentation.slides, start=1):
            slide_count += 1
            parts.append(f"[slide {index}]")
            collect_shapes(slide.shapes, index)
            notes_text = ""
            if getattr(slide, "has_notes_slide", False):
                notes_frame = getattr(slide.notes_slide, "notes_text_frame", None)
                if notes_frame is not None:
                    notes_text = str(getattr(notes_frame, "text", "") or "").strip()
            if notes_text:
                parts.append(f"[备注 {index}] {notes_text}")
        return (
            "\n".join(parts),
            "python-pptx",
            {"extension": ".pptx", "slide_count": slide_count, "table_count": table_count},
        )

    def _extract_excel_text(self, path: Path) -> tuple[str, str, dict[str, Any]]:
        suffix = path.suffix.lower()
        if suffix == ".xlsx":
            return self._extract_xlsx_text(path)
        if suffix == ".xls":
            return self._extract_xls_text(path)
        raise ValueError(f"unsupported document type: {suffix or '<none>'}")

    def _extract_xlsx_text(self, path: Path) -> tuple[str, str, dict[str, Any]]:
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise RuntimeError("openpyxl is required to ingest XLSX documents") from exc
        max_rows_per_sheet = 5000
        max_cols = 100
        parts: list[str] = []
        sheet_count = 0
        row_count = 0
        wb = load_workbook(str(path), read_only=True, data_only=True)
        try:
            for sheet in wb.worksheets:
                sheet_count += 1
                sheet_lines: list[str] = []
                for index, row in enumerate(sheet.iter_rows(values_only=True)):
                    if index >= max_rows_per_sheet:
                        sheet_lines.append(f"... truncated after {max_rows_per_sheet} rows")
                        break
                    cells: list[str] = []
                    for col_index, cell in enumerate(row or ()):
                        if col_index >= max_cols:
                            break
                        if cell is None:
                            continue
                        text = str(cell).strip()
                        if text:
                            cells.append(text)
                    if cells:
                        sheet_lines.append("\t".join(cells))
                        row_count += 1
                if sheet_lines:
                    parts.append(f"[sheet {sheet.title}]\n" + "\n".join(sheet_lines))
        finally:
            wb.close()
        return (
            "\n\n".join(parts),
            "openpyxl",
            {"extension": ".xlsx", "sheet_count": sheet_count, "row_count": row_count},
        )

    def _extract_xls_text(self, path: Path) -> tuple[str, str, dict[str, Any]]:
        try:
            import xlrd
        except ImportError as exc:
            raise RuntimeError("xlrd is required to ingest XLS documents") from exc
        max_rows_per_sheet = 5000
        max_cols = 100
        parts: list[str] = []
        sheet_count = 0
        row_count = 0
        book = xlrd.open_workbook(str(path))
        for sheet in book.sheets():
            sheet_count += 1
            sheet_lines: list[str] = []
            nrows = min(int(sheet.nrows), max_rows_per_sheet)
            for row_index in range(nrows):
                cells: list[str] = []
                ncols = min(int(sheet.ncols), max_cols)
                for col_index in range(ncols):
                    value = sheet.cell_value(row_index, col_index)
                    if value is None or value == "":
                        continue
                    text = str(value).strip()
                    if text:
                        cells.append(text)
                if cells:
                    sheet_lines.append("\t".join(cells))
                    row_count += 1
            if int(sheet.nrows) > max_rows_per_sheet:
                sheet_lines.append(f"... truncated after {max_rows_per_sheet} rows")
            if sheet_lines:
                parts.append(f"[sheet {sheet.name}]\n" + "\n".join(sheet_lines))
        return (
            "\n\n".join(parts),
            "xlrd",
            {"extension": ".xls", "sheet_count": sheet_count, "row_count": row_count},
        )

    def _split_text(
        self, text: str, *, strategy: str, chunk_size: int, chunk_overlap: int
    ) -> list[Chunk]:
        if strategy == "semantic":
            return self._chunker.split_by_semantic(text)
        return self._chunker.split_by_fixed(
            text,
            chunk_size=max(50, min(int(chunk_size), 5000)),
            chunk_overlap=max(0, min(int(chunk_overlap), 500)),
        )
