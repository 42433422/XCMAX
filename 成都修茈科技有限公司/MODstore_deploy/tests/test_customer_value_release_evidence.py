"""Formal customer evidence consumes original workflows and published installers."""

import json
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modstore_server import customer_value_evidence as evidence
from modstore_server import workflow_customer_delivery as delivery
from modstore_server.api.deps import require_admin
from modstore_server.customer_value_evidence_api import router
from modstore_server.models import UpdateInstallationReceipt, get_session_factory
from tests import test_workflow_customer_delivery as original
from tests.customer_value_release_fixture import published_catalog
from tests.test_retort_experiment_lifecycle import Clock
from tests.test_retort_workflow_customer import business_receipts

experiment_run = original.experiment_run
workflow_experiment = original.workflow_experiment
execution_experiment = original.execution_experiment
customer_workflow = original.customer_workflow


@pytest.mark.parametrize(
    "change",
    ["none", "other_release", "candidate", "bytes", "superseded", "future_install", "late_install"],
)
def test_formal_api_reads_original_native_delivery_and_published_desktop(
    customer_workflow, monkeypatch, tmp_path, change
):
    env, sha = customer_workflow, "a" * 40
    monkeypatch.setattr(evidence, "datetime", Clock)
    monkeypatch.setattr(evidence, "load_authoritative_payment_orders", lambda _days: env["source"])
    env["order"]["enterprise_subject_id"] = "original-enterprise-identity"
    catalog, catalog_path, artifact = published_catalog(tmp_path, monkeypatch, sha)
    with get_session_factory()() as db:
        db.add(
            UpdateInstallationReceipt(
                user_id=env["customer_id"],
                installation_id="original-customer-desktop",
                idempotency_key=f"original-customer-install-{env['customer_id']}",
                channel="stable",
                platform="macos",
                target_version="1.0.0.1",
                installed_version="1.0.0.1",
                target_build_sha=sha,
                installed_build_sha=sha,
                status="installed",
                reported_at=(Clock.value - timedelta(minutes=5)).replace(tzinfo=None),
            )
        )
        db.commit()
    response = env["execute"]()
    assert response.status_code == 200, response.text
    output = env["artifact"]
    completed_at = Clock.value
    Clock.value += timedelta(minutes=10)

    def usage(kind):
        response = env["http"].post(
            "/api/customer-value/usage-receipts",
            json={
                **original._query(env),
                "receipt_kind": kind,
                "idempotency_key": f"original-workflow-{kind}-receipt",
                "run_id": f"original-workflow-{kind}-run",
                "task_type": "csv-generation",
                "output_id": output["artifact_id"],
                "output_sha256": output["artifact_sha256"],
            },
        )
        assert response.status_code == 200, response.text

    usage("first_use")
    business_receipts(env)
    Clock.value += timedelta(hours=25)
    usage("reuse")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_admin] = lambda: env["admin"]
    with TestClient(app) as client:
        unscoped = client.get("/api/admin/customer-value/evidence").json()["data"]
        assert "release_sha" not in unscoped and unscoped["complete_customer_count"] == 1
        bound = client.get("/api/admin/customer-value/evidence", params={"release_sha": sha})
        assert bound.status_code == 200, bound.text
        body = bound.json()["data"]
        assert body["release_sha"] == sha and body["complete_customer_count"] == 1
        assert body["verification_scope"] == "native_customer_release"
        assert body["value_ledger_ready"] is True
        assert output["artifact_id"] not in bound.text
        assert env["order"]["out_trade_no"] not in bound.text
        assert client.get("/api/admin/customer-value/evidence?release_sha=main").status_code == 422

        if change == "other_release":
            sha = "b" * 40
            # The desktop really belongs to the requested release; the original
            # business execution still belongs to another runtime SHA.
            published_catalog(tmp_path, monkeypatch, sha)
            with get_session_factory()() as db:
                row = (
                    db.query(UpdateInstallationReceipt)
                    .filter_by(
                        user_id=env["customer_id"], installation_id="original-customer-desktop"
                    )
                    .one()
                )
                row.installed_build_sha = row.target_build_sha = sha
                db.commit()
        elif change == "candidate":
            artifact["state"] = "candidate"
            catalog_path.write_text(json.dumps(catalog))
        elif change == "bytes":
            path = delivery._artifact_snapshot_path(env["binding"]["customer_delivery"], output)
            path.write_bytes(b"changed-original-output")
        elif change == "superseded":
            with get_session_factory()() as db:
                db.add(
                    UpdateInstallationReceipt(
                        user_id=env["customer_id"],
                        installation_id="original-customer-desktop",
                        idempotency_key=f"different-customer-install-{env['customer_id']}",
                        channel="stable",
                        platform="macos",
                        target_version="1.0.0.1",
                        installed_version="1.0.0.1",
                        target_build_sha="b" * 40,
                        installed_build_sha="b" * 40,
                        status="installed",
                        reported_at=Clock.value.replace(tzinfo=None),
                    )
                )
                db.commit()
        elif change in {"future_install", "late_install"}:
            with get_session_factory()() as db:
                row = (
                    db.query(UpdateInstallationReceipt)
                    .filter_by(
                        user_id=env["customer_id"], installation_id="original-customer-desktop"
                    )
                    .one()
                )
                row.reported_at = (
                    Clock.value + timedelta(hours=1)
                    if change == "future_install"
                    else completed_at + timedelta(minutes=5)
                ).replace(tzinfo=None)
                db.commit()
            if change == "late_install":
                # Delivery may be generated before installation; the existing
                # business contract requires installation before first use.
                legacy = client.get("/api/admin/customer-value/evidence").json()["data"]
                assert legacy["complete_customer_count"] == 1
        result = client.get("/api/admin/customer-value/evidence", params={"release_sha": sha})
        assert result.status_code == 200, result.text
        expected = 1 if change in {"none", "late_install"} else 0
        assert result.json()["data"]["complete_customer_count"] == expected
        assert result.json()["data"]["verified_paid_count"] == expected
        if change == "future_install":
            assert result.json()["data"]["six_stage_counts"]["installation"] == 0
    injected = evidence.build_customer_value_evidence(orders=[env["order"]], release_sha="a" * 40)
    assert injected["value_ledger_ready"] is False
