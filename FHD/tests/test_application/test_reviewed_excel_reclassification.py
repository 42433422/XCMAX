"""Explicit archive reclassification preserves evidence and uses compare-and-swap."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy.orm import sessionmaker

from app.application.elt.service_support import dump_json, load_json
from app.db.models.elt import EltRun, EltUpload
from app.db.models.elt_archive import EltArchiveVersion
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.etl_template.sources.generate import sample
from tests.test_application.test_reviewed_excel_template import review_store as _review_store

review_store = _review_store


def archived(store):
    client = store.client
    assert (
        client.post(
            "/api/templates/reviewed-excel/archive-quota",
            data={
                "expected_actor": "1:7",
                "limit_bytes": 1000000,
            },
        ).status_code
        == 200
    )
    body = sample()
    result = client.post(
        "/api/templates/reviewed-excel/archive-classify",
        data={
            "expected_actor": "1:7",
            "request_key": "reclassify-test",
        },
        files={"file": ("sample.xlsx", body)},
    )
    assert result.status_code == 200, result.text
    return result.json(), body


def reclassify(store, old):
    return store.client.post(
        f"/api/templates/reviewed-excel/archive-versions/{old['archive_version_id']}/classify",
        data={
            "expected_actor": "1:7",
            "reclassify": "true",
            "expected_classification_id": old["classification_id"],
        },
    )


def test_explicit_reclassification_preserves_history_and_default_idempotency(review_store):
    old, body = archived(review_store)
    url = f"/api/templates/reviewed-excel/archive-versions/{old['archive_version_id']}/classify"
    old_id = old["classification_id"]
    with tenant_scope(1), sessionmaker(bind=review_store.engine)() as db:
        run = db.get(EltRun, old_id)
        state = load_json(run.draft_json, {})
        state["analysis_checkpoint"] = {
            "phase": "failed",
            "budget_version": "old-budget",
            "version": old["version"],
            "results": [],
            "total": 1,
            "max_calls": 1,
        }
        state["model_audit"] = [
            {"request": {"messages": ["synthetic full input"]}, "response": "synthetic full output"}
        ]
        run.draft_json = dump_json(state)
        old_draft = run.draft_json
        db.commit()
    assert (
        review_store.client.post(url, data={"expected_actor": "1:7"}).json()["classification_id"]
        == old_id
    )
    for expected in [None, "wrong"]:
        response = review_store.client.post(
            url,
            data={
                "expected_actor": "1:7",
                "reclassify": "true",
                **({"expected_classification_id": expected} if expected else {}),
            },
        )
        assert response.status_code == 409
    response = reclassify(review_store, old)
    assert response.status_code == 200, response.text
    new = response.json()
    assert new["classification_id"] != old_id
    assert new["sha256"] == old["sha256"] and new["archive_version_id"] == old["archive_version_id"]
    assert new["model_status"] == "not_called" and new["confirmed"] is False
    assert reclassify(review_store, old).status_code == 409
    assert (
        review_store.client.post(url, data={"expected_actor": "1:7"}).json()["classification_id"]
        == new["classification_id"]
    )
    with tenant_scope(1), sessionmaker(bind=review_store.engine)() as db:
        assert db.get(EltRun, old_id).draft_json == old_draft
        assert db.query(EltRun).count() == 2
        assert (
            db.get(EltArchiveVersion, old["archive_version_id"]).classification_id
            == new["classification_id"]
        )
    history = review_store.client.get(f"/api/templates/reviewed-excel/classifications/{old_id}")
    assert history.status_code == 200
    assert history.json()["checkpoint"]["phase"] == "failed"
    assert history.json()["versions"] == state["versions"]
    for classification_id in [old_id, new["classification_id"]]:
        assert (
            review_store.client.get(
                f"/api/templates/reviewed-excel/classifications/{classification_id}/source"
            ).content
            == body
        )


@pytest.mark.parametrize("actor", [{"tenant": 2}, {"id": 8}, {"manage": False}])
def test_reclassification_rejects_other_actor(review_store, actor):
    old, _body = archived(review_store)
    review_store.actor.update(actor)
    response = review_store.client.post(
        f"/api/templates/reviewed-excel/archive-versions/{old['archive_version_id']}/classify",
        data={
            "expected_actor": f"{review_store.actor['tenant']}:{review_store.actor['id']}",
            "reclassify": "true",
            "expected_classification_id": old["classification_id"],
        },
    )
    assert response.status_code in {400, 403, 404}
    with sessionmaker(bind=review_store.engine)() as db:
        assert db.query(EltRun).count() == 1


def test_concurrent_reclassification_claims_only_one_new_run(review_store):
    old, _body = archived(review_store)
    barrier = Barrier(2)

    def submit():
        barrier.wait()
        return reclassify(review_store, old).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: submit(), range(2)))
    assert sorted(statuses) == [200, 409]
    with tenant_scope(1), sessionmaker(bind=review_store.engine)() as db:
        assert db.query(EltRun).count() == 2
        assert db.query(EltUpload).count() == 2


@pytest.mark.parametrize("after_upload", [False, True])
def test_failed_reclassification_keeps_original_association(
    review_store, monkeypatch, after_upload
):
    from app.fastapi_routes.reviewed_excel import archive

    old, _body = archived(review_store)

    def fail(*args, **kwargs):
        raise ValueError("synthetic storage failure")

    if after_upload:
        monkeypatch.setattr(archive, "_classification_version", fail)
    else:
        monkeypatch.setattr(archive.UploadServiceMixin, "save_upload", fail)
    uploads_before = set((review_store.root / "etl" / "uploads").rglob("*"))
    assert reclassify(review_store, old).status_code == 400
    assert set((review_store.root / "etl" / "uploads").rglob("*")) == uploads_before
    with tenant_scope(1), sessionmaker(bind=review_store.engine)() as db:
        assert db.query(EltRun).count() == 1
        assert db.query(EltUpload).count() == 1
        assert (
            db.get(EltArchiveVersion, old["archive_version_id"]).classification_id
            == old["classification_id"]
        )
