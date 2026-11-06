"""Word (.docx) intake for the docking-center archive-classify path."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile

import pytest
from openpyxl import load_workbook
from sqlalchemy import text

from app.application.elt.errors import ReviewedExcelError
from app.application.reviewed_excel_docx import is_docx_package
from app.application.reviewed_excel_legacy import prepare_archive_workbook
from tests.test_application.test_reviewed_excel_template import (
    account_session_client as account_session_client,
)
from tests.test_application.test_reviewed_excel_template import (
    review_store as review_store,
)


def _derived_from_classification(client, classification_id: str) -> bytes:
    source = client.get(f"/api/templates/reviewed-excel/classifications/{classification_id}/source")
    assert source.status_code == 200, source.text
    return source.content


def _minimal_docx(*, party: str = "样例往来单位", rows: list[list[str]] | None = None) -> bytes:
    """Build a synthetic OOXML package with one table. No customer data."""
    if rows is None:
        rows = [
            ["日期", "摘要", "欠款", "收款"],
            ["2026-01-01", "样例明细", "100.00", "0"],
            ["2026-01-02", "样例回款", "0", "40.00"],
        ]

    def cell(text: str) -> str:
        return (
            "<w:tc><w:tcPr/><w:p><w:r><w:t>"
            + text.replace("&", "&amp;").replace("<", "&lt;")
            + "</w:t></w:r></w:p></w:tc>"
        )

    table_xml = ["<w:tbl>"]
    for row in rows:
        table_xml.append("<w:tr>" + "".join(cell(value) for value in row) + "</w:tr>")
    table_xml.append("</w:tbl>")
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        f"<w:p><w:r><w:t>{party}</w:t></w:r></w:p>"
        f"<w:p><w:r><w:t>对账单</w:t></w:r></w:p>"
        + "".join(table_xml)
        + "<w:sectPr/></w:body></w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("[Content_Types].xml", content_types)
        package.writestr("_rels/.rels", rels)
        package.writestr("word/document.xml", document)
    return buffer.getvalue()


def test_is_docx_package_rejects_plain_xlsx():
    from openpyxl import Workbook

    book = Workbook()
    out = io.BytesIO()
    book.save(out)
    assert not is_docx_package(out.getvalue())
    assert is_docx_package(_minimal_docx())


def _replace_document(body: bytes, transform) -> bytes:
    out = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(body)) as original,
        zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as target,
    ):
        for name in original.namelist():
            content = original.read(name)
            if name == "word/document.xml":
                content = transform(content.decode()).encode()
            target.writestr(name, content)
    return out.getvalue()


def test_docx_preserves_literal_formulas_long_cells_and_trailing_paragraphs():
    formula = "=SUM(1,2)"
    long_text = "原始正文" * 200
    body = _minimal_docx(rows=[["摘要", "内容"], [formula, long_text]])
    body = _replace_document(
        body,
        lambda xml: xml.replace(
            "<w:sectPr/>",
            "<w:p><w:r><w:t>表后余额说明</w:t></w:r></w:p><w:sectPr/>",
        ),
    )
    converted, review = prepare_archive_workbook(body)
    book = load_workbook(io.BytesIO(converted), data_only=False)
    try:
        cells = [cell for sheet in book for row in sheet for cell in row]
        matched = [cell for cell in cells if cell.value == formula]
        assert len(matched) == 1 and matched[0].data_type == "s"
        assert any(cell.value == long_text for cell in cells)
        assert any(cell.value == "表后余额说明" for cell in cells)
        assert review["conversion_receipt"]["truncated"] is False
        assert review["conversion_receipt"]["paragraph_count"] == 3
    finally:
        book.close()


@pytest.mark.parametrize("limit", ["_MAX_ROWS", "_MAX_COLUMNS", "_MAX_TEXT"])
def test_docx_refuses_limit_overflow_without_truncation(monkeypatch, limit):
    monkeypatch.setattr(f"app.application.reviewed_excel_docx.{limit}", 2)
    with pytest.raises(ReviewedExcelError, match="超过"):
        prepare_archive_workbook(_minimal_docx())


def test_docx_refuses_merged_cells_instead_of_shifting_columns():
    body = _replace_document(
        _minimal_docx(),
        lambda xml: xml.replace("<w:tcPr/>", '<w:tcPr><w:gridSpan w:val="2"/></w:tcPr>', 1),
    )
    with pytest.raises(ReviewedExcelError, match="合并单元格"):
        prepare_archive_workbook(body)


@pytest.mark.parametrize(
    "fragment",
    [
        "<w:customXml><w:p><w:r><w:t>余额999.00</w:t></w:r></w:p></w:customXml>",
        "<w:customXml><w:tbl><w:tr><w:tc><w:p><w:r><w:t>余额999.00</w:t>"
        "</w:r></w:p></w:tc></w:tr></w:tbl></w:customXml>",
        "<w:p><w:moveFrom><w:r><w:t>旧金额999.00</w:t></w:r></w:moveFrom>"
        "<w:moveTo><w:r><w:t>新金额999.00</w:t></w:r></w:moveTo></w:p>",
        "<w:p><w:ins><w:r><w:t>未确认金额999.00</w:t></w:r></w:ins></w:p>",
        "<w:altChunk/>",
        "<w:unknown><w:p><w:r><w:t>余额999.00</w:t></w:r></w:p></w:unknown>",
        "<w:tbl><w:unknown><w:tr><w:tc><w:p><w:r><w:t>余额999.00</w:t>"
        "</w:r></w:p></w:tc></w:tr></w:unknown></w:tbl>",
    ],
)
def test_docx_refuses_unhandled_wrappers_and_revisions(fragment):
    body = _replace_document(
        _minimal_docx(), lambda xml: xml.replace("<w:sectPr/>", fragment + "<w:sectPr/>")
    )
    with pytest.raises(ReviewedExcelError, match="无法|不支持"):
        prepare_archive_workbook(body)


def test_docx_invalid_xml_is_a_business_error():
    body = _replace_document(_minimal_docx(), lambda xml: xml[:-30])
    with pytest.raises(ReviewedExcelError, match="XML"):
        prepare_archive_workbook(body)


def test_docx_checks_uncompressed_xml_before_reading(monkeypatch):
    body = _replace_document(_minimal_docx(), lambda xml: xml + " " * 200_000)
    monkeypatch.setattr("app.application.reviewed_excel_docx.MAX_BYTES", 4096)
    assert len(body) < 4096
    with pytest.raises(ReviewedExcelError, match="解压大小"):
        prepare_archive_workbook(body)


def test_prepare_archive_workbook_converts_docx_with_receipt():
    body = _minimal_docx()
    converted, review = prepare_archive_workbook(body)
    assert converted != body
    assert is_docx_package(body)
    assert not is_docx_package(converted)
    receipt = review["conversion_receipt"]
    assert receipt["source_kind"] == "docx"
    assert receipt["source_sha256"] == hashlib.sha256(body).hexdigest()
    assert receipt["derived_sha256"] == hashlib.sha256(converted).hexdigest()
    assert receipt["purpose"] == "docking_center_word_statement"
    workbook = load_workbook(io.BytesIO(converted), data_only=True)
    values = [[cell.value for cell in row] for row in workbook.active.iter_rows()]
    flat = {str(value) for row in values for value in row if value is not None}
    assert "欠款" in flat and "样例明细" in flat and "样例往来单位" in flat


def test_archive_classify_accepts_synthetic_docx(review_store):
    body = _minimal_docx()
    with review_store.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO etl_archive_quotas (tenant_id, limit_bytes, reserved_bytes) "
                "VALUES (1, 1000000, 0)"
            )
        )
    client = review_store.client
    response = client.post(
        "/api/templates/reviewed-excel/archive-classify",
        data={"expected_actor": "1:7", "request_key": "docx-statement-1"},
        files={
            "file": (
                "样例对账单.docx",
                body,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert response.status_code == 200, response.text
    item = response.json()
    assert item["status"] == "classified"
    assert item["model_status"] == "not_called"
    assert item["conversion_receipt"]["source_kind"] == "docx"
    assert item["conversion_receipt"]["source_sha256"] == hashlib.sha256(body).hexdigest()
    assert item["sheets"], "derived workbook must classify into sheets"
    assert any(sheet.get("regions") for sheet in item["sheets"])
    original = client.get(
        f"/api/templates/reviewed-excel/archive-versions/{item['archive_version_id']}/download"
    )
    assert original.status_code == 200
    assert original.content == body


def test_missing_model_session_cannot_execute_docx_writes(
    review_store, account_session_client, monkeypatch
):
    """A classified Word file must not write when the model never returned."""
    body = _minimal_docx()
    with review_store.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO etl_archive_quotas (tenant_id, limit_bytes, reserved_bytes) "
                "VALUES (1, 1000000, 0)"
            )
        )
    client = review_store.client
    classified = client.post(
        "/api/templates/reviewed-excel/archive-classify",
        data={"expected_actor": "1:7", "request_key": "docx-no-model"},
        files={"file": ("样例对账单.docx", body)},
    )
    assert classified.status_code == 200, classified.text
    item = classified.json()
    labels = [
        {"sheet": sheet["sheet"], "range": region["range"], "labels": region["labels"]}
        for sheet in item["sheets"]
        for region in sheet["regions"]
    ]
    confirmed = client.post(
        f"/api/templates/reviewed-excel/classifications/{item['classification_id']}/confirm",
        data={"version": item["version"], "labels_json": json.dumps(labels)},
    )
    assert confirmed.status_code == 200, confirmed.text
    derived = _derived_from_classification(client, item["classification_id"])
    preview = client.post(
        "/api/templates/reviewed-excel/preview",
        data={
            "expected_actor": "1:7",
            "classification_id": item["classification_id"],
            "classification_version": confirmed.json()["version"],
            "region_sheet": labels[0]["sheet"],
            "region_range": labels[0]["range"],
        },
        files={"file": ("样例对账单.xlsx", derived)},
    )
    assert preview.status_code == 200, preview.text
    review_id = preview.json()["review_id"]
    proposal_version = preview.json()["proposal"]["version"]
    candidate_id = preview.json()["proposal"]["candidates"][0]["id"]
    with review_store.engine.begin() as conn:
        stored = json.loads(
            conn.execute(
                text("SELECT draft_json FROM etl_runs WHERE id=:id"), {"id": review_id}
            ).scalar_one()
        )
        stored["versions"][-1]["model"]["status"] = "not_called"
        conn.execute(
            text("UPDATE etl_runs SET draft_json=:draft WHERE id=:id"),
            {"id": review_id, "draft": json.dumps(stored)},
        )
    saved = client.post(
        "/api/templates/reviewed-excel/save",
        data={
            "review_id": review_id,
            "name": "docx-no-model",
            "proposal_version": proposal_version,
            "candidate_id": candidate_id,
            "publish_to_tenant": "false",
            "private_intake": "true",
            "selections": "[]",
        },
    )
    assert saved.status_code == 409
    assert saved.json()["detail"]["code"] == "model_required"
    with review_store.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM templates")).scalar_one() == 0


def test_confirmed_model_template_path_still_saves(review_store, account_session_client):
    """Returned model proposal can still save after Word-derived preview."""
    body = _minimal_docx()
    with review_store.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO etl_archive_quotas (tenant_id, limit_bytes, reserved_bytes) "
                "VALUES (1, 1000000, 0)"
            )
        )
    client = review_store.client
    classified = client.post(
        "/api/templates/reviewed-excel/archive-classify",
        data={"expected_actor": "1:7", "request_key": "docx-model-ok"},
        files={"file": ("样例对账单.docx", body)},
    )
    assert classified.status_code == 200, classified.text
    item = classified.json()
    labels = [
        {"sheet": sheet["sheet"], "range": region["range"], "labels": region["labels"]}
        for sheet in item["sheets"]
        for region in sheet["regions"]
    ]
    confirmed = client.post(
        f"/api/templates/reviewed-excel/classifications/{item['classification_id']}/confirm",
        data={"version": item["version"], "labels_json": json.dumps(labels)},
    ).json()
    derived = _derived_from_classification(client, item["classification_id"])
    preview = client.post(
        "/api/templates/reviewed-excel/preview",
        data={
            "expected_actor": "1:7",
            "classification_id": item["classification_id"],
            "classification_version": confirmed["version"],
            "region_sheet": labels[0]["sheet"],
            "region_range": labels[0]["range"],
        },
        files={"file": ("样例对账单.xlsx", derived)},
    )
    assert preview.status_code == 200, preview.text
    payload = preview.json()
    assert payload["proposal"]["model"]["status"] == "returned"
    saved = client.post(
        "/api/templates/reviewed-excel/save",
        data={
            "review_id": payload["review_id"],
            "name": "docx-model-ok",
            "proposal_version": payload["proposal"]["version"],
            "candidate_id": payload["proposal"]["candidates"][0]["id"],
            "publish_to_tenant": "true",
            "selections": "[]",
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json().get("success") is True
    with review_store.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM templates")).scalar_one() >= 1
