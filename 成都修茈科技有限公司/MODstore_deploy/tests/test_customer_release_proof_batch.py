"""A request shares repair proof reads but keeps original customer case bindings."""

from collections import Counter
from types import SimpleNamespace

from modstore_server.customer_service_tools import json_dumps, json_loads
from tests.test_customer_issue_delivery_pipeline import github_fixture, make_ticket, seed_repair


def test_pending_batch_fetches_each_proof_once_and_binds_each_case(client, monkeypatch, tmp_path):
    from modstore_server import customer_issue_shared_release as shared
    from modstore_server.models import get_session_factory, init_db
    from modstore_server.models_cs import CustomerServiceTicket

    # Seeded CRs must not consume other tests' daily dispatch budget.
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "release-proof-batch.sqlite"))
    init_db()

    owner, first = make_ticket(client, monkeypatch)
    response = client.post(
        "/api/customer-service/issues/intake",
        json={
            "source": "customer_feedback",
            "source_ref": f"proof-batch-{first}",
            "title": "另一份原单",
            "description": "同一修复的另一处原问题",
            "issue_domain": "software",
        },
    )
    assert response.status_code == 200, response.text
    second = response.json()["ticket_id"]
    github_fixture(monkeypatch)
    reads = Counter()
    original_fetch, original_pulls = shared._fetch_json, shared._pulls_for_commit

    def fetch(url):
        reads[url] += 1
        return original_fetch(url)

    def pulls(sha):
        reads[f"pulls:{sha}"] += 1
        return original_pulls(sha)

    monkeypatch.setattr(shared, "_fetch_json", fetch)
    monkeypatch.setattr(shared, "_pulls_for_commit", pulls)
    with get_session_factory()() as db:
        for tid in (first, second):
            seed_repair(db, db.get(CustomerServiceTicket, tid))
    pending = client.get(
        "/api/customer-service/issues/pending-runtime", params={"host_sha": "c" * 40}
    )
    assert pending.status_code == 200, pending.text
    targets = {
        item["id"]: item["target"]
        for item in pending.json()["items"]
        if item["id"] in (first, second)
    }
    assert len(targets) == 2 and len(reads) == 5 and set(reads.values()) == {1}
    assert targets[first]["action_id"] != targets[second]["action_id"]
    assert targets[first]["case_id"] != targets[second]["case_id"]
    assert {target["owner_user_id"] for target in targets.values()} == {owner.id}
    target = targets[first]
    receipt = {
        key: target[key]
        for key in ("host_sha", "version", "release_id", "signed_metadata_sha256", "case_id")
    }
    receipt.update(
        receipt_id="batch-confirm-1",
        client_instance_id="test-instance",
        customer_confirmed=True,
        confirmation_note="客户独立确认原问题已解决",
    )
    closed = client.post(f"/api/customer-service/issues/{first}/runtime-receipt", json=receipt)
    assert closed.status_code == 200, closed.text
    with get_session_factory()() as db:
        assert db.get(CustomerServiceTicket, first).status == "resolved"
        other = db.get(CustomerServiceTicket, second)
        assert other.status == "processing" and other.closed_at is None
        evidence = json_loads(other.evidence_json, {})
        evidence["resolution"].pop("release_target")
        other.evidence_json = json_dumps(evidence)
        db.commit()
    again = client.get(
        "/api/customer-service/issues/pending-runtime", params={"host_sha": "c" * 40}
    )
    assert again.status_code == 200, again.text
    assert set(reads.values()) == {2}, "proof snapshots must not survive a request"


def test_proof_snapshot_cannot_be_mutated_by_a_ticket():
    from modstore_server.customer_issue_shared_release import _ReleaseProofBatch

    batch = _ReleaseProofBatch()
    source = {"check_runs": [{"conclusion": "failure"}]}
    first = batch.read("head:fixed", lambda: source)
    first["check_runs"][0]["conclusion"] = "success"
    source["check_runs"][0]["conclusion"] = "success"
    assert batch.read("head:fixed", lambda: None)["check_runs"][0]["conclusion"] == "failure"


def test_batch_does_not_reuse_a_different_head_or_host(monkeypatch):
    from modstore_server import customer_issue_shared_release as shared

    github_fixture(monkeypatch)
    batch = shared._ReleaseProofBatch()
    first = SimpleNamespace(id=1, status="applied", staged_commit_sha="a" * 40)
    second = SimpleNamespace(id=2, status="applied", staged_commit_sha="e" * 40)
    assert shared._merged_repair(first, "c" * 40, proofs=batch)
    assert shared._merged_repair(second, "c" * 40, proofs=batch) is None
    original_fetch = shared._fetch_json
    monkeypatch.setattr(
        shared,
        "_fetch_json",
        lambda url: (
            {"status": "diverged", "merge_base_commit": {"sha": "f" * 40}}
            if "/compare/" in url
            else original_fetch(url)
        ),
    )
    assert shared._merged_repair(first, "f" * 40, proofs=batch) is None


def test_failed_proof_fetch_does_not_cache_success(monkeypatch):
    from modstore_server.customer_issue_shared_release import _ReleaseProofBatch

    batch = _ReleaseProofBatch()
    calls = []

    def fetch():
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("unavailable")
        return {"conclusion": "failure"}

    import pytest

    with pytest.raises(ValueError):
        batch.read("head", fetch)
    assert batch.read("head", fetch) == {"conclusion": "failure"}
    assert len(calls) == 2
