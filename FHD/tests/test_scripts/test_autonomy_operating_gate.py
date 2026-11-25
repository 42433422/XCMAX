"""WG12 independent gate adversarial contract tests; fixtures are NOT product evidence."""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import pytest

from scripts.dev.autonomy_operating_gate import ARTIFACTS, FAULTS, NEGATIVE, evaluate

SHA = "a" * 40
AUDITOR_SHA = "b" * 40
DIGEST = "c" * 64
RELEASE_ARTIFACT = "d" * 64
DEPLOYMENT_RECEIPT = "e" * 64
KEY = b"isolated-test-only-independent-auditor-key-not-a-real-production-key"
NOW = datetime(2026, 11, 25, 20, tzinfo=UTC)


def stamp(value):
    return value.isoformat().replace("+00:00", "Z")


def fixtures():
    model = {
        "execution_mode": "real_model", "frozen_holdout_sha256": DIGEST,
        "trials": [
            {"task_id": f"t{task}", "trial": trial, "status": "PASS", "model_id": "frozen-real-model-id",
             "model_receipt_sha256": DIGEST, "tool_receipt_sha256": DIGEST, "business_readback_sha256": DIGEST}
            for task in range(100) for trial in (1, 2, 3)
        ],
    }
    business = {"scenarios": [
        {"scenario_id": f"case{i}", "status": "PASS", "employees": ["sales", "finance", "warehouse"],
         "systems": ["ERP", "AgentRuntime"], "approval_id": "approval", "customer_acceptance_id": "acceptance",
         "independent_readback_sha256": DIGEST, "reconciled_ledger_sha256": DIGEST}
        for i in range(3)
    ]}
    last = NOW - timedelta(minutes=20)
    heartbeat = {"samples": [
        {"seq": i, "at": stamp(last - timedelta(hours=72) + timedelta(minutes=5*i)),
         "runtime_id": "stable-runtime", "revision": i, "checkpoint_sha256": DIGEST}
        for i in range(865)
    ]}
    faults = {"cases": [
        {"type": name, "outcome": "SAFE_BLOCKED" if name in {"permission_revoked", "budget_exhausted"} else "RECOVERED",
         "duplicate_effects": 0, "independent_readback_sha256": DIGEST}
        for name in sorted(FAULTS)
    ]}
    goals = {"days": [
        {"day_start": stamp(datetime.combine(NOW.date() - timedelta(days=7-i), datetime.min.time(), tzinfo=UTC)),
         "origin": "agent_discovered_erp_gap", "status": "VERIFIED", "execution_receipt_id": f"task{i}",
         "goal_id": f"goal{i}", "independent_outcome_id": f"outcome{i}", "independent_readback_sha256": DIGEST}
        for i in range(7)
    ]}
    ledger = {"days": [
        {"day_start": stamp(datetime.combine(NOW.date() - timedelta(days=90-i), datetime.min.time(), tzinfo=UTC)),
         "revenue": "10.00", "cost": "7.99", "profit": "2.01",
         "independent_accountant": "outside-reviewer", "erp_ledger_sha256": DIGEST,
         "independent_readback_sha256": DIGEST, "unreconciled_entries": 0, "unauthorized_spend": 0}
        for i in range(90)
    ]}
    security = {"cases": [
        {"type": name, "result": "DENIED", "side_effect_count": 0, "independent_readback_sha256": DIGEST}
        for name in sorted(NEGATIVE)
    ]}
    improvement = {"paired_holdout_sha256": DIGEST, "independent_outcome_sha256": DIGEST,
                   "rollback_receipt_sha256": DIGEST, "paired_samples": 100, "experiment_approved": True,
                   "rollback_test_passed": True, "no_safety_regression": True,
                   "baseline_successes": 80, "candidate_successes": 86}
    return locals()


def write_fixture(root, change=None):
    rows = fixtures()
    if change:
        change(rows)
    evidence = {}
    for name in ARTIFACTS:
        data = {**rows[name], "source_sha": SHA, "environment": "production",
                "release_artifact_sha256": RELEASE_ARTIFACT,
                "deployment_receipt_sha256": DEPLOYMENT_RECEIPT}
        raw = json.dumps(data, ensure_ascii=False).encode()
        (root / f"{name}.json").write_bytes(raw)
        evidence[name] = {"path": f"{name}.json", "sha256": hashlib.sha256(raw).hexdigest()}
    manifest = {"schema_version": 2, "source_sha": SHA, "auditor_source_sha": AUDITOR_SHA,
                "release_artifact_sha256": RELEASE_ARTIFACT,
                "deployment_receipt_sha256": DEPLOYMENT_RECEIPT,
                "auditor_id": "independent-reviewer", "run_id": "audit-run-1",
                "captured_at": stamp(NOW - timedelta(minutes=5)), "artifacts": evidence}
    raw = json.dumps(manifest).encode()
    (root / "manifest.json").write_bytes(raw)
    (root / "manifest.hmac").write_text(hmac.new(KEY, raw, hashlib.sha256).hexdigest())
    return root


def verify(root, **kwargs):
    return evaluate(root, SHA, KEY, now=NOW, **kwargs)


def test_unaudited_directory_never_promotes(tmp_path):
    report = evaluate(tmp_path, SHA, None, now=NOW)
    assert report["highest_certifiable_level"] is None
    assert report["levels"]["L6"] == "BLOCKED"
    assert "signing key" in report["blockers"]["L01"]


def test_synthetic_signed_fixture_only_tests_verifier_logic(tmp_path):
    report = verify(write_fixture(tmp_path))
    assert report["highest_certifiable_level"] == "L6"
    assert all(x == "PASS" for x in report["checks"].values())
    assert report["provenance"]["release_artifact_sha256"] == RELEASE_ARTIFACT
    assert report["provenance"]["deployment_receipt_sha256"] == DEPLOYMENT_RECEIPT
    # Production acceptance additionally requires the independently controlled key,
    # original external receipts, authorised deployment and actual elapsed time.


@pytest.mark.parametrize("change,blocked", [
    (lambda v: v["model"]["trials"].pop(), "L02"),
    (lambda v: v["model"]["trials"].__setitem__(0, {**v["model"]["trials"][0], "model_receipt_sha256": "not-a-sha"}), "L02_smoke"),
    (lambda v: v["business"]["scenarios"][0].update(employees=["sales"]), "L03"),
    (lambda v: v["heartbeat"]["samples"].__setitem__(30, {**v["heartbeat"]["samples"][30], "at": stamp(NOW)}), "L04"),
    (lambda v: v["faults"]["cases"].pop(), "L05"),
    (lambda v: v["goals"]["days"].pop(), "L06"),
    (lambda v: v["ledger"]["days"].pop(), "L08"),
    (lambda v: v["ledger"]["days"][0].update(profit="3.00"), "L07"),
    (lambda v: v["security"]["cases"][0].update(side_effect_count=1), "L09"),
    (lambda v: v["improvement"].update(candidate_successes=81), "improvement"),
])
def test_negative_cases_block_level_upgrade(tmp_path, change, blocked):
    report = verify(write_fixture(tmp_path, change))
    assert report["checks"][blocked] == "BLOCKED"
    assert report["levels"]["L6"] == "BLOCKED"


def test_any_security_veto_blocks_even_l1(tmp_path):
    def modify(data):
        data["security"]["cases"][0]["result"] = "ALLOWED"
    report = verify(write_fixture(tmp_path, modify))
    assert all(status == "BLOCKED" for status in report["levels"].values())


def test_modified_raw_artifact_invalidates_independent_signature_chain(tmp_path):
    write_fixture(tmp_path)
    with (tmp_path / "model.json").open("ab") as file:
        file.write(b" ")
    report = verify(tmp_path)
    assert report["checks"]["L01"] == "BLOCKED"
    assert "checksum mismatch" in report["blockers"]["L01"]


def test_wrong_key_or_sha_cannot_approve(tmp_path):
    write_fixture(tmp_path)
    report = evaluate(tmp_path, SHA, b"other-trusted-auditor-key-of-adequate-length", now=NOW)
    assert report["highest_certifiable_level"] is None
    report = evaluate(tmp_path, "d" * 40, KEY, now=NOW)
    assert report["highest_certifiable_level"] is None


def test_manifest_cannot_include_path_traversal(tmp_path):
    write_fixture(tmp_path)
    m = json.loads((tmp_path / "manifest.json").read_text())
    m["artifacts"]["model"]["path"] = "../escape.json"
    raw = json.dumps(m).encode()
    (tmp_path / "manifest.json").write_bytes(raw)
    (tmp_path / "manifest.hmac").write_text(hmac.new(KEY, raw, hashlib.sha256).hexdigest())
    report = verify(tmp_path)
    assert report["checks"]["L01"] == "BLOCKED"


def test_duplicate_json_field_fails_closed(tmp_path):
    write_fixture(tmp_path)
    raw = (tmp_path / "manifest.json").read_bytes().replace(b'"schema_version": 1', b'"schema_version": 1, "schema_version": 1')
    (tmp_path / "manifest.json").write_bytes(raw)
    (tmp_path / "manifest.hmac").write_text(hmac.new(KEY, raw, hashlib.sha256).hexdigest())
    assert verify(tmp_path)["checks"]["L01"] == "BLOCKED"


def test_missing_actual_elapsed_time_blocks_8h_and_72h(tmp_path):
    def shorten(data):
        data["heartbeat"]["samples"] = data["heartbeat"]["samples"][-96:]
        for i, sample in enumerate(data["heartbeat"]["samples"]):
            sample["seq"] = i
    result = verify(write_fixture(tmp_path, shorten))
    assert result["checks"]["L04"] == "BLOCKED"
    assert result["checks"]["L05"] == "BLOCKED"
    assert result["checks"]["L09"] == "PASS"



@pytest.mark.parametrize("field", ["release_artifact_sha256", "deployment_receipt_sha256"])
def test_signed_manifest_release_identity_cannot_drift(tmp_path, field):
    write_fixture(tmp_path)
    path = tmp_path / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest[field] = "f" * 64
    raw = json.dumps(manifest).encode()
    path.write_bytes(raw)
    (tmp_path / "manifest.hmac").write_text(hmac.new(KEY, raw, hashlib.sha256).hexdigest())
    report = verify(tmp_path)
    assert report["checks"]["L01"] == "BLOCKED"
    assert report["levels"]["L6"] == "BLOCKED"


@pytest.mark.parametrize("field", ["release_artifact_sha256", "deployment_receipt_sha256"])
def test_resigned_raw_artifact_cannot_switch_deployment_identity(tmp_path, field):
    write_fixture(tmp_path)
    artifact = tmp_path / "model.json"
    data = json.loads(artifact.read_text())
    data[field] = "f" * 64
    raw_artifact = json.dumps(data).encode()
    artifact.write_bytes(raw_artifact)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"]["model"]["sha256"] = hashlib.sha256(raw_artifact).hexdigest()
    raw_manifest = json.dumps(manifest).encode()
    manifest_path.write_bytes(raw_manifest)
    (tmp_path / "manifest.hmac").write_text(
        hmac.new(KEY, raw_manifest, hashlib.sha256).hexdigest()
    )
    report = verify(tmp_path)
    assert report["checks"]["L01"] == "BLOCKED"
    assert report["highest_certifiable_level"] is None
