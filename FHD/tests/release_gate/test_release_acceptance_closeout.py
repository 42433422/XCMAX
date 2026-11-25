"""Fail-closed release acceptance; all remote calls are mocked."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import pytest

FHD = Path(__file__).resolve().parents[2]
SCRIPT = FHD / "scripts/dev/release_acceptance_closeout.py"
SHA = "a" * 40


def load():
    spec = importlib.util.spec_from_file_location("release_acceptance_closeout", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def config(issues=None):
    return {
        "schema": "xcagi.download_release.public/v1",
        "download_version": "1.0.0.7",
        "version_lock": "1.0.0.7",
        "release_ready": True,
        "git_sha": SHA,
        "release_id": f"xcagi-1.0.0.7-{SHA}",
        "linked_issues": [42] if issues is None else issues,
    }


def receipt(verdict="accepted"):
    return {
        "version": "1.0.0.7",
        "build_sha": SHA,
        "verdict": verdict,
        "per_platform": {
            "win": {"installed": 1, "failed": 0},
            "mac": {"installed": 1, "failed": 0},
        },
    }


def args():
    return argparse.Namespace(
        release_config="",
        market_base="https://xiu-ci.com",
        market_token="test",
        repo="test/repo",
        token="inert",
        version="",
        channel="stable",
        dry_run=False,
        apply=True,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"linked_issues": []},
        {"linked_issues": None},
        {"release_ready": False},
        {"git_sha": "bad"},
        {"release_id": "wrong"},
        {"version_lock": "1.0.0.6"},
    ],
)
def test_missing_or_unpublished_release_never_reads_receipts(monkeypatch, changes):
    m = load()
    data = {**config(), **changes}
    monkeypatch.setattr(m, "_fetch_published_release", lambda _: data)
    monkeypatch.setattr(
        m,
        "_fetch_acceptance",
        lambda *a: pytest.fail("must not fetch acceptance for invalid release"),
    )
    assert m.run(args()) == 1


def test_receipt_mismatched_sha_never_mutates_issue(monkeypatch):
    m = load()
    monkeypatch.setattr(m, "_fetch_published_release", lambda _: config())
    monkeypatch.setattr(m, "_fetch_acceptance", lambda *a: {**receipt(), "build_sha": "b" * 40})
    monkeypatch.setattr(m, "_http", lambda *a: pytest.fail("must not mutate issues"))
    assert m.run(args()) == 1


def test_persistence_failure_prevents_github_mutation(monkeypatch):
    m = load()
    monkeypatch.setattr(m, "_fetch_published_release", lambda _: config())
    monkeypatch.setattr(m, "_fetch_acceptance", lambda *a: receipt())
    monkeypatch.setattr(m, "_ensure_label", lambda *a: None)
    monkeypatch.setattr(m, "_record_verdict_local", lambda *a: False)

    def github(method, url, token, body=None):
        assert method == "GET"
        return {"number": 42, "state": "open", "labels": []}

    monkeypatch.setattr(m, "_http", github)
    assert m.run(args()) == 1


def test_accepted_closes_original_issue_with_existing_label(monkeypatch):
    m = load()
    monkeypatch.setattr(m, "_fetch_published_release", lambda _: config())
    monkeypatch.setattr(m, "_fetch_acceptance", lambda *a: receipt())
    monkeypatch.setattr(m, "_ensure_label", lambda *a: None)
    monkeypatch.setattr(m, "_record_verdict_local", lambda *a: True)
    calls = []

    def github(method, url, token, body=None):
        calls.append((method, url, body))
        if method == "GET":
            return {"number": 42, "state": "open", "labels": [{"name": "customer-accepted"}]}
        if method == "PATCH":
            return {"state": "closed"}
        return {"ok": True}

    monkeypatch.setattr(m, "_http", github)
    assert m.run(args()) == 0
    assert [action[0] for action in calls] == ["GET", "PATCH"]
    assert calls[-1][2] == {"state": "closed", "state_reason": "completed"}


def test_new_acceptance_adds_evidence_and_closes(monkeypatch):
    m = load()
    calls = []

    def github(method, url, token, body=None):
        calls.append((method, body))
        if method == "GET":
            return {"number": 42, "state": "open", "labels": []}
        if method == "PATCH":
            return {"state": "closed"}
        return {"ok": True}

    monkeypatch.setattr(m, "_fetch_published_release", lambda _: config())
    monkeypatch.setattr(m, "_fetch_acceptance", lambda *a: receipt())
    monkeypatch.setattr(m, "_ensure_label", lambda *a: None)
    monkeypatch.setattr(m, "_record_verdict_local", lambda *a: True)
    monkeypatch.setattr(m, "_http", github)
    assert m.run(args()) == 0
    assert [action[0] for action in calls] == ["GET", "POST", "POST", "PATCH"]


def test_rejected_reopens_accepted_issue(monkeypatch):
    m = load()
    calls = []

    def github(method, url, token, body=None):
        calls.append((method, body))
        if method == "GET":
            return {"number": 42, "state": "closed", "labels": [{"name": "customer-accepted"}]}
        if method == "PATCH":
            return {"state": "open"}
        return {"ok": True}

    monkeypatch.setattr(m, "_fetch_published_release", lambda _: config())
    monkeypatch.setattr(m, "_fetch_acceptance", lambda *a: receipt("rejected"))
    monkeypatch.setattr(m, "_ensure_label", lambda *a: None)
    monkeypatch.setattr(m, "_record_verdict_local", lambda *a: True)
    monkeypatch.setattr(m, "_http", github)
    assert m.run(args()) == 0
    assert calls[1] == ("PATCH", {"state": "open"})

def _business_evidence():
    identity = {
        "version": "1.0.0.7", "build_sha": SHA,
        "tenant_id": "tenant1", "customer_id": "customer1",
        "task_id": "task1", "run_id": "run1",
    }
    stages = {
        kind: {
            **identity, "receipt_id": f"receipt-{kind}", "source_sha256": "0" * 64,
            "status": "accepted" if kind == "customer_confirmation" else "verified",
        }
        for kind in (
            "source", "approval", "execution", "database", "artifact",
            "independent_reconciliation", "customer_confirmation",
        )
    }
    # Schema-only fixture. Production validation requires authorized original
    # bytes, committed DB readbacks and human customer confirmation.
    stages["source"].update(
        source_kind="authorized_customer_original", synthetic=False
    )
    stages["approval"]["approved_by"] = "approver1"
    stages["database"].update(
        inventory_committed=True,
        finance_committed=True,
        readback_verified=True,
        inventory_readback_sha256="4" * 64,
        finance_readback_sha256="5" * 64,
    )
    stages["artifact"].update(format="xlsx", download_hash_verified=True)
    stages["independent_reconciliation"]["reconciliation_sha256"] = "6" * 64
    stages["approval"]["approved_action_sha256"] = "2" * 64
    stages["execution"].update(approved_action_sha256="2" * 64, executed_by="worker1")
    stages["artifact"]["artifact_sha256"] = "1" * 64
    stages["customer_confirmation"].update(
        artifact_sha256="1" * 64, confirmed_by="customer1",
        confirmed_at="2026-11-25T12:00:00Z",
    )
    stages["independent_reconciliation"].update(
        verifier_id="readback1", original_to_database=True,
        database_to_artifact=True, inventory_and_accounting=True,
        approval_scope=True,
    )
    return {
        **identity, "source_sha256": "0" * 64, "artifact_sha256": "1" * 64,
        "status": "accepted", "stages": stages,
    }


def test_installer_pass_does_not_close_business_work_order(monkeypatch):
    m = load()
    issue = {"number": 42, "state": "open", "labels": [
        {"name": "business-acceptance-required"}
    ]}
    events = []

    def github(method, _url, _token, body=None):
        events.append((method, body))
        assert method == "GET", "business proof missing, do not mutate the issue"
        return issue

    monkeypatch.setattr(m, "_fetch_published_release", lambda _: config())
    monkeypatch.setattr(m, "_fetch_acceptance", lambda *a: receipt())
    monkeypatch.setattr(m, "_ensure_label", lambda *a: None)
    monkeypatch.setattr(m, "_record_verdict_local", lambda *a: pytest.fail("no receipt"))
    monkeypatch.setattr(m, "_http", github)
    assert m.run(args()) == 1
    assert events == [("GET", None)]


@pytest.mark.parametrize("drift", [
    "source", "approval", "execution", "database", "artifact",
    "independent_reconciliation", "customer_confirmation", "foreign_tenant",
    "other_artifact", "self_verified", "wrong_amounts",
    "synthetic_source", "missing_source_kind", "missing_approver",
    "self_approved", "inventory_not_committed", "finance_not_committed",
    "database_readback_missing", "inventory_readback_missing",
    "finance_readback_missing", "not_xlsx", "download_unverified",
    "self_confirmed", "reconciliation_digest_missing",
])
def test_business_receipts_fail_closed_on_missing_or_mismatched_stage(drift):
    m = load()
    issue = {"number": 42, "labels": [{"name": "business-acceptance-required"}]}
    record = _business_evidence()
    if drift == "foreign_tenant":
        record["stages"]["approval"]["tenant_id"] = "other"
    elif drift == "other_artifact":
        record["stages"]["customer_confirmation"]["artifact_sha256"] = "3" * 64
    elif drift == "self_verified":
        record["stages"]["independent_reconciliation"]["verifier_id"] = "worker1"
    elif drift == "wrong_amounts":
        record["stages"]["independent_reconciliation"]["inventory_and_accounting"] = False
    elif drift == "synthetic_source":
        record["stages"]["source"]["synthetic"] = True
    elif drift == "missing_source_kind":
        record["stages"]["source"].pop("source_kind")
    elif drift == "missing_approver":
        record["stages"]["approval"].pop("approved_by")
    elif drift == "self_approved":
        record["stages"]["approval"]["approved_by"] = "worker1"
    elif drift == "inventory_not_committed":
        record["stages"]["database"]["inventory_committed"] = False
    elif drift == "finance_not_committed":
        record["stages"]["database"]["finance_committed"] = False
    elif drift == "database_readback_missing":
        record["stages"]["database"]["readback_verified"] = False
    elif drift == "inventory_readback_missing":
        record["stages"]["database"].pop("inventory_readback_sha256")
    elif drift == "finance_readback_missing":
        record["stages"]["database"].pop("finance_readback_sha256")
    elif drift == "not_xlsx":
        record["stages"]["artifact"]["format"] = "csv"
    elif drift == "download_unverified":
        record["stages"]["artifact"]["download_hash_verified"] = False
    elif drift == "self_confirmed":
        record["stages"]["customer_confirmation"]["confirmed_by"] = "worker1"
    elif drift == "reconciliation_digest_missing":
        record["stages"]["independent_reconciliation"].pop("reconciliation_sha256")
    else:
        record["stages"].pop(drift)
    assert not m._business_receipts_complete(
        issue, {"business_receipts": {"42": record}}, "1.0.0.7", SHA
    )


def test_complete_business_identity_contract_is_distinct_from_installer_status():
    m = load()
    issue = {"number": 42, "labels": [{"name": "business-acceptance-required"}]}
    assert m._business_receipts_complete(
        issue, {"business_receipts": {"42": _business_evidence()}}, "1.0.0.7", SHA
    )

def test_business_verdict_persistence_stores_only_bound_receipt_digest(monkeypatch):
    import hashlib
    import json

    m = load()
    business = _business_evidence()
    acceptance = {**receipt(), "business_receipts": {"42": business}}
    captured = []

    def persist(method, _url, _token, body=None):
        captured.append((method, body))
        return {"ok": True}

    monkeypatch.setattr(m, "_http", persist)
    assert m._record_verdict_local(
        "https://xiu-ci.com", "test", 42, "1.0.0.7", "accepted", acceptance
    )
    assert len(captured) == 1 and captured[0][0] == "POST"
    payload = captured[0][1]
    expected = hashlib.sha256(
        json.dumps(
            business, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    assert payload["evidence"]["business_receipt_sha256"] == expected
    assert "business_receipts" not in payload["evidence"]
    assert "customer_id" not in payload["evidence"]
