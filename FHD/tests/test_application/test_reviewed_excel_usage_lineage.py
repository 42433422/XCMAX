"""Test-only restrictions survive classification and metadata-normalizing derivation."""

import json
from io import BytesIO

import pytest
from openpyxl import load_workbook
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.application.elt.service_support import dump_json, load_json
from app.application.reviewed_excel_template import inspect_workbook
from app.db.models.elt import EltRun, EltUpload
from app.fastapi_routes import reviewed_excel_template as routes
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.etl_template.legacy_biff import fixture
from tests.fixtures.etl_template.sources.generate import sample
from tests.test_application.test_reviewed_excel_legacy import archive, convert
from tests.test_application.test_reviewed_excel_template import review_store as _review_store

review_store = _review_store


def without_custom_properties(body):
    workbook = load_workbook(BytesIO(body))
    for name in list(workbook.custom_doc_props.names):
        del workbook.custom_doc_props[name]
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def save_data(preview):
    return {
        "review_id": preview["review_id"],
        "proposal_version": preview["proposal"]["version"],
        "candidate_id": "preserve",
        "selections": "[]",
        "name": "synthetic restriction test",
        "publish_to_tenant": "true",
    }


def test_standalone_classification_persists_and_reports_restrictions(review_store):
    derived, _ = convert(fixture())
    response = review_store.client.post(
        "/api/templates/reviewed-excel/classify",
        data={"expected_actor": "1:7"},
        files=[("files", ("test-only.xlsx", derived))],
    )
    assert response.status_code == 200, response.text
    item = response.json()["files"][0]
    assert item["usage_restrictions"]
    with tenant_scope(1), sessionmaker(bind=review_store.engine)() as db:
        run = db.get(EltRun, item["classification_id"])
        summary = load_json(run.summary_json, {})
        assert summary["usage_restrictions"] == item["usage_restrictions"]
        state = load_json(run.draft_json, {})
        state["versions"][-1].pop("usage_restrictions", None)
        run.draft_json = dump_json(state)
        db.commit()
    history = review_store.client.get(
        "/api/templates/reviewed-excel/classifications/" + item["classification_id"]
    )
    assert history.status_code == 200
    assert history.json()["usage_restrictions"] == item["usage_restrictions"]


def test_stripped_properties_cannot_bypass_bound_archive_source_hash(review_store):
    item, body = archive(review_store)
    stripped = without_custom_properties(body)
    assert not inspect_workbook(stripped)["usage_restrictions"]
    url = "/api/templates/reviewed-excel/classifications/" + item["classification_id"]
    labels = [
        {"sheet": s["sheet"], "range": r["range"], "labels": ["quotation"]}
        for s in item["sheets"]
        for r in s["regions"]
    ]
    confirmed = review_store.client.post(
        url + "/confirm",
        data={
            "expected_actor": "1:7",
            "version": item["version"],
            "labels_json": json.dumps(labels),
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    response = review_store.client.post(
        "/api/templates/reviewed-excel/preview",
        data={
            "expected_actor": "1:7",
            "classification_id": item["classification_id"],
            "classification_version": confirmed.json()["version"],
            "region_sheet": labels[0]["sheet"],
            "region_range": labels[0]["range"],
        },
        files={"file": ("stripped.xlsx", stripped)},
    )
    assert response.status_code == 409, response.text


def test_metadata_free_derived_workbook_still_blocked_by_database_lineage(
    review_store, monkeypatch
):
    item, body = archive(review_store)
    client = review_store.client
    url = "/api/templates/reviewed-excel/classifications/" + item["classification_id"]
    labels = [
        {"sheet": s["sheet"], "range": r["range"], "labels": ["quotation"]}
        for s in item["sheets"]
        for r in s["regions"]
    ]
    confirmed = client.post(
        url + "/confirm",
        data={
            "expected_actor": "1:7",
            "version": item["version"],
            "labels_json": json.dumps(labels),
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    derive = routes.derive_document_workbook
    # Model a legitimate serializer that drops custom properties. Server source
    # lineage must protect publication even when the derived bytes lack markers.
    monkeypatch.setattr(
        routes,
        "derive_document_workbook",
        lambda *a, **kw: without_custom_properties(derive(*a, **kw)),
    )
    response = client.post(
        "/api/templates/reviewed-excel/preview",
        data={
            "expected_actor": "1:7",
            "classification_id": item["classification_id"],
            "classification_version": confirmed.json()["version"],
            "region_sheet": labels[0]["sheet"],
            "region_range": labels[0]["range"],
        },
        files={"file": ("source.xlsx", body)},
    )
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["usage_restrictions"]
    with tenant_scope(1), sessionmaker(bind=review_store.engine)() as db:
        run = db.get(EltRun, preview["review_id"])
        upload = db.get(EltUpload, run.upload_id)
        from pathlib import Path

        assert not inspect_workbook(Path(upload.storage_path).read_bytes())["usage_restrictions"]
        summary = load_json(run.summary_json, {})
        assert summary["selected_region"]["classification_id"] == item["classification_id"]
        # Remove the redundant review-level copy: authoritative classification
        # summary is the only remaining usage restriction.
        summary.pop("usage_restrictions", None)
        run.summary_json = dump_json(summary)
        db.commit()
    saved = client.post("/api/templates/reviewed-excel/save", data=save_data(preview))
    assert saved.status_code == 409 and "打印版式未验证" in saved.text
    with review_store.engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM templates")).scalar_one() == 0
    review_store.actor["tenant"] = 2
    assert client.get(url).status_code == 404
    assert client.get(url + "/source").status_code == 404
    assert (
        client.post("/api/templates/reviewed-excel/save", data=save_data(preview)).status_code
        == 404
    )
    review_store.actor.update(tenant=1, id=8)
    assert client.get(url).status_code == 404
    assert (
        client.post("/api/templates/reviewed-excel/save", data=save_data(preview)).status_code
        == 404
    )


def test_normal_xlsx_can_still_publish(review_store):
    response = review_store.client.post(
        "/api/templates/reviewed-excel/preview",
        data={"expected_actor": "1:7"},
        files={"file": ("ordinary.xlsx", sample())},
    )
    assert response.status_code == 200, response.text
    preview = response.json()
    assert not preview["usage_restrictions"]
    saved = review_store.client.post("/api/templates/reviewed-excel/save", data=save_data(preview))
    assert saved.status_code == 200, saved.text
    assert saved.json()["success"]
