"""Resolve owned ELT upload references without trusting client paths or model metadata."""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zipfile import BadZipFile, ZipFile
from zlib import error as ZlibError

from app.application.shipment_excel_elt_security import open_elt_input_file
from app.db.models.elt import EltUpload
from app.db.session import get_db
from app.infrastructure.auth.agent_mod_scope import validate_actor_context
from app.infrastructure.tenant_scope import tenant_scope
from app.utils.operational_errors import BOUNDARY_ERRORS

MAX_ATTACHMENT_BYTES = 16 * 1024 * 1024
MAX_TEXT = 24_000
_CONTEXT_FILE_BYTES = 256 * 1024
_CONTEXT_PACKAGE_BYTES = 2 * 1024 * 1024
_CONTEXT_TEXT_BYTES = 16 * 1024
_CONTEXT_SUFFIXES = frozenset({".csv", ".docx"})


class AttachmentInputError(ValueError):
    """Safe actionable error; never includes a local path or parser traceback."""


@dataclass
class _InlineReadBudget:
    file_bytes: int = _CONTEXT_FILE_BYTES
    package_bytes: int = _CONTEXT_PACKAGE_BYTES
    text_bytes: int = _CONTEXT_TEXT_BYTES


def _docx_preview(raw: bytes, coverage: dict[str, Any], *, budget: _InlineReadBudget | None) -> str:
    from docx import Document
    from docx.opc.constants import RELATIONSHIP_TYPE
    from docx.oxml.exceptions import InvalidXmlError
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph

    max_tables, max_rows, max_columns, max_cell_chars = 20, 200, 40, 500
    coverage.update(
        scope="paragraphs_and_tables",
        max_tables=max_tables,
        max_rows_per_table=max_rows,
        max_columns=max_columns,
        max_cell_chars=max_cell_chars,
    )
    paragraph_tag, table_tag, row_tag, cell_tag = map(qn, ("w:p", "w:tbl", "w:tr", "w:tc"))
    lines: list[str] = []
    remaining = MAX_TEXT

    def append(text: str, *, cell: bool = False) -> bool:
        nonlocal remaining
        separator = int(bool(lines))
        if len(text) + separator > remaining:
            coverage["truncated"] = True
            if not cell and remaining > separator:
                lines.append(text[: remaining - separator])
            return False
        lines.append(text)
        remaining -= len(text) + separator
        return True

    package = io.BytesIO(raw)
    try:
        with ZipFile(package) as archive:
            # Bound expanded bytes before python-docx loads related package parts.
            expanded = sum(member.file_size for member in archive.infolist())
            if expanded > (budget.package_bytes if budget else 2 * MAX_ATTACHMENT_BYTES):
                raise AttachmentInputError("附件解压后体积过大，请重新上传较小的文件")
            if budget is not None:
                budget.package_bytes -= expanded
        package.seek(0)
        document = Document(package)
        # Inline recall requires complete body data. A footnotes part often
        # contains just template separators, so inspect actual body references.
        if budget is not None and (
            document.element.xpath(
                ".//w:sdt | .//w:ins | .//w:del | .//w:moveFrom | .//w:moveTo | .//w:drawing | "
                ".//w:pict | .//w:object | .//w:altChunk | .//w:footnoteReference | .//w:endnoteReference"
            )
            or any(
                rel.reltype in {RELATIONSHIP_TYPE.HEADER, RELATIONSHIP_TYPE.FOOTER}
                for rel in document.part.rels.values()
            )
        ):
            coverage["truncated"] = True
        table_index = 0
        for block in document.element.body:
            if block.tag == paragraph_tag:
                if not append(Paragraph(block, document).text):
                    break
            elif block.tag == table_tag:
                table_index += 1
                if table_index > max_tables:
                    coverage["truncated"] = True
                    continue
                for row_index, row in enumerate(block.iterchildren(row_tag), start=1):
                    if row_index > max_rows:
                        coverage["truncated"] = True
                        break
                    column = 1 + row.grid_before
                    if column < 1 or row.grid_after < 0:
                        raise ValueError("Invalid DOCX grid offset")
                    for cell in row.iterchildren(cell_tag):
                        if column > max_columns:
                            coverage["truncated"] = True
                            break
                        # Do not expand merged cells into duplicate values or allocate by grid span.
                        span = cell.grid_span
                        if span < 1:
                            raise ValueError("Invalid DOCX grid span")
                        if cell.find(table_tag) is not None:
                            coverage["truncated"] = True
                        if cell.vMerge != "continue":
                            text = " ".join(
                                Paragraph(p, document).text
                                for p in cell.iterchildren(paragraph_tag)
                            )
                            text = " ".join(text.split())
                            if len(text) > max_cell_chars:
                                coverage["truncated"] = True
                            if text and not append(
                                f"[表格 {table_index} 行 {row_index} 列 {column}] {text[:max_cell_chars]}",
                                cell=True,
                            ):
                                return "\n".join(lines)
                        column += span
                    coverage["truncated"] |= column - 1 + row.grid_after > max_columns
            elif block.tag != qn("w:sectPr"):
                coverage["truncated"] = True
    except (BadZipFile, InvalidXmlError, KeyError, SyntaxError, ZlibError) as exc:
        raise AttachmentInputError("附件解析失败，请重新上传可读取的文件") from exc
    return "\n".join(lines)


def _decode(
    raw: bytes,
    suffix: str,
    *,
    inline_context: bool = False,
    budget: _InlineReadBudget | None = None,
) -> tuple[str, dict[str, Any]]:
    coverage: dict[str, Any] = {"truncated": False, "max_text_chars": MAX_TEXT}

    def finish(text: str) -> tuple[str, dict[str, Any]]:
        coverage["truncated"] = coverage["truncated"] or len(text) > MAX_TEXT
        coverage["notice"] = (
            "仅提取了部分附件内容，不得据此声称已读完整文件或作全量统计。"
            if coverage["truncated"]
            else "已读取此格式支持的文字内容。"
        )
        return text[:MAX_TEXT], coverage

    if suffix in {".xlsx", ".xlsm"}:
        from openpyxl import load_workbook
        from openpyxl.utils.cell import get_column_letter

        workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True, keep_links=False)
        coverage.update(max_sheets=20, max_rows_per_sheet=200, max_columns=40, max_cell_chars=500)
        try:
            lines: list[str] = []
            length = 0

            def append(line: str) -> bool:
                nonlocal length
                length += len(line) + bool(lines)
                if length > MAX_TEXT:
                    coverage["truncated"] = True
                    return False
                lines.append(line)
                return True

            coverage["truncated"] = len(workbook.worksheets) > 20
            for sheet in workbook.worksheets[:20]:
                coverage["truncated"] |= (sheet.max_row or 0) > 200 or (sheet.max_column or 0) > 40
                if not append("[工作表] " + json.dumps(sheet.title, ensure_ascii=False)):
                    break
                column_count = min(sheet.max_column or 40, 40)
                last_column = get_column_letter(column_count)
                rows = sheet.iter_rows(
                    min_row=1,
                    min_col=1,
                    max_row=min(sheet.max_row or 200, 200),
                    max_col=column_count,
                    values_only=True,
                )
                # Read-only openpyxl yields missing rows and cells at their original positions.
                for number, row in enumerate(rows, start=1):
                    cells = ["" if value is None else str(value) for value in row]
                    coverage["truncated"] |= any(len(cell) > 500 for cell in cells)
                    ref = f"A{number}:{last_column}{number}"
                    values = json.dumps([cell[:500] for cell in cells], ensure_ascii=False)
                    if not append(f"[{ref}] {values}"):
                        return finish("\n".join(lines))
            return finish("\n".join(lines))
        finally:
            workbook.close()
    if suffix == ".pdf":
        try:
            from app.infrastructure.document_parsing.router import parse_pdf_bytes_with_docling

            docling_text = parse_pdf_bytes_with_docling(raw)
        except BOUNDARY_ERRORS:
            docling_text = None
        if docling_text and docling_text.strip():
            coverage["method"] = "docling"
            return finish(docling_text)

        import pdfplumber

        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            coverage.update(max_pages=20, truncated=len(pdf.pages) > 20)
            return finish("\n".join((page.extract_text() or "") for page in pdf.pages[:20]))
    if suffix in {".png", ".jpg", ".jpeg"}:
        from PIL import Image

        from app.domain.shared_services.ocr_service import get_ocr_service

        with Image.open(io.BytesIO(raw)) as image:
            blocks = get_ocr_service().recognize_text_blocks(image) or []
        coverage["method"] = "ocr_unverified"
        return finish(
            "\n".join(str(block.get("text") or "") for block in blocks if isinstance(block, dict))
        )
    if suffix == ".csv":
        return finish(raw.decode("utf-8-sig"))
    if suffix == ".docx":
        return finish(
            _docx_preview(
                raw,
                coverage,
                budget=budget or (_InlineReadBudget() if inline_context else None),
            )
        )
    raise AttachmentInputError("附件格式暂不支持，请重新上传 PDF、图片、CSV 或 XLSX")


def resolve_attachment_inputs(
    context: dict[str, Any], *, inline_context: bool = False
) -> list[dict[str, Any]]:
    ids = context.get("attachment_upload_ids")
    if ids is None:
        return []  # Legacy evidence remains untrusted context, never an ingestible artifact.
    if (
        not isinstance(ids, list)
        or not 1 <= len(ids) <= 4
        or any(not isinstance(item, str) or not item or len(item) > 80 for item in ids)
        or len(set(ids)) != len(ids)
    ):
        raise AttachmentInputError("附件引用无效，请重新上传")
    if validate_actor_context(context) is not None:
        raise AttachmentInputError("附件需要有效登录授权，请重新登录")
    owner, tenant = int(context["user_id"]), int(context["tenant_id"])
    budget = _InlineReadBudget() if inline_context else None
    artifacts = []
    with tenant_scope(tenant), get_db() as db:
        for upload_id in ids:
            row = (
                db.query(EltUpload)
                .filter(
                    EltUpload.id == upload_id,
                    EltUpload.owner_user_id == owner,
                    EltUpload.tenant_id == tenant,
                )
                .first()
            )
            if row is None:
                raise AttachmentInputError("附件不属于当前账户，请重新上传")
            expiry = row.expires_at
            if expiry is None or expiry.replace(tzinfo=UTC) <= datetime.now(UTC):
                raise AttachmentInputError("附件已过期，请重新上传")
            max_bytes = budget.file_bytes if budget is not None else MAX_ATTACHMENT_BYTES
            if budget is not None and (
                row.suffix not in _CONTEXT_SUFFIXES or row.size_bytes > max_bytes
            ):
                return []
            try:
                with open_elt_input_file(row.storage_path, owner_user_id=owner) as stream:
                    raw = stream.read(max_bytes + 1)
            except (OSError, ValueError, RuntimeError) as exc:
                raise AttachmentInputError("附件无法安全读取，请重新上传") from exc
            if (
                len(raw) > max_bytes
                or len(raw) != row.size_bytes
                or hashlib.sha256(raw).hexdigest() != row.sha256
            ):
                raise AttachmentInputError("附件内容校验失败，请重新上传")
            try:
                text, coverage = _decode(raw, row.suffix, budget=budget)
            except (OSError, ValueError, RuntimeError, ImportError) as exc:
                raise AttachmentInputError("附件解析失败，请重新上传可读取的文件") from exc
            if not text.strip():
                raise AttachmentInputError("附件没有可读取的文字，请重新上传清晰文件")
            if budget is not None:
                budget.file_bytes -= len(raw)
                budget.text_bytes -= len(text.encode("utf-8"))
                if coverage["truncated"] or budget.text_bytes < 0:
                    return []
            artifacts.append(
                {
                    "artifact_type": "file_analysis",
                    "name": row.file_name,
                    "source": "owned_elt_upload",
                    "uri": "",
                    "summary": "已验证账户归属的附件",
                    "preview": {"text": text, "coverage": coverage},
                    "metadata": {
                        "upload_id": row.id,
                        "sha256": row.sha256,
                        "parser_used": "owned_upload",
                        "skip_dataset_ingest": True,
                    },
                }
            )
    return artifacts


def resolve_attachment_context(context: dict[str, Any]):
    """Shared planning boundary for chat, streaming chat and durable Agent runs."""
    artifacts = resolve_attachment_inputs(context)
    if not artifacts:
        return dict(context), artifacts
    return {
        **context,
        "file_context": {
            "verified_uploads": [
                {
                    "name": item["name"],
                    "upload_id": item["metadata"]["upload_id"],
                    **item["preview"],
                }
                for item in artifacts
            ]
        },
    }, artifacts


def read_bound_chat_attachment(upload_id: str, context: dict[str, Any]) -> dict[str, Any]:
    """Reopen a current or same-conversation upload bound by the parent goal."""
    from app.application.agent_runtime.conversation_attachments import resolve_conversation_upload
    from app.infrastructure.xiaox.receipts import action_parent

    reference = (
        resolve_conversation_upload(upload_id, context) if isinstance(upload_id, str) else None
    )
    expected: str | None
    if reference:
        selected, expected = reference.upload_id, reference.sha256
    else:
        parent = action_parent(context)
        if parent is None:
            raise AttachmentInputError("附件读取需要原对话任务")
        _, binding, _ = parent
        request = binding.run.metadata["runtime_goal_contract"]["request"]
        selected, expected = (
            upload_id,
            next(
                (
                    item["metadata"]["sha256"]
                    for item in request["attachments"]
                    if item.get("source") == "owned_elt_upload"
                    and item["metadata"]["upload_id"] == upload_id
                ),
                None,
            ),
        )
    if not expected:
        raise AttachmentInputError("附件未绑定到当前对话任务")
    [artifact] = resolve_attachment_inputs({**context, "attachment_upload_ids": [selected]})
    if artifact["metadata"]["sha256"] != expected:
        raise AttachmentInputError("附件内容与原任务凭证不一致")
    return {
        "upload_id": upload_id,
        "name": artifact["name"],
        "sha256": expected,
        **artifact["preview"],
    }
