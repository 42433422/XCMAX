import json

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from modstore_server import mac_control_delivery as delivery
from modstore_server.db.mac_control import MacControlEvent
from modstore_server.mac_control_store import accept
from modstore_server.models import Base

SOURCE, MERGED = "a" * 40, "b" * 40
RECEIPT = {
    "source": "executor_git_readback",
    "pushed": True,
    "commit_sha": SOURCE,
    "archive_sha256": "c" * 64,
}
RUNTIME = {
    "deploy_tier": "production",
    "git_sha": MERGED,
    "artifact_sha256": "d" * 64,
    "release_id": "xcagi-1.0.0.1-" + MERGED,
}


class GitHub:
    def __init__(self):
        self.calls = []
        self.runs = [{"name": "backend-test", "conclusion": "success", "status": "completed"}]
        self.pulls = [
            {
                "number": 123,
                "state": "closed",
                "merged_at": "2026-09-08",
                "merge_commit_sha": MERGED,
                "head": {"sha": SOURCE},
                "base": {"repo": {"full_name": delivery.REPOSITORY}},
            }
        ]
        self.ancestry = "behind"
        self.fail = False

    def get(self, path):
        self.calls.append(path)
        if self.fail:
            raise httpx.ConnectError("secret-fixture-must-not-leak")
        if "/pulls?" in path:
            return self.pulls
        if "check-runs" in path:
            return {"check_runs": self.runs, "total_count": len(self.runs)}
        if "/reviews?" in path:
            return [{"state": "APPROVED", "user": {"id": 1}}]
        if path.startswith("compare/"):
            return {"status": self.ancestry}
        raise AssertionError(path)

    def close(self):
        pass


def states(result):
    return {s["name"]: s["state"] for s in result["stages"]}


def test_release_stages_require_exact_source_main_ancestry_and_runtime_artifact():
    github = GitHub()
    result = delivery.release_facts(RECEIPT, github, RUNTIME)
    assert states(result) == {
        "code": "recorded",
        "tests": "passed",
        "approval": "approved",
        "merged": "verified",
        "deployed": "verified",
    }
    assert result["pull_request"]["url"] == "https://github.com/42433422/XCMAX/pull/123"
    assert (
        states(delivery.release_facts(RECEIPT, github, {**RUNTIME, "artifact_sha256": ""}))[
            "deployed"
        ]
        != "verified"
    )
    assert (
        states(delivery.release_facts(RECEIPT, github, {**RUNTIME, "deploy_tier": "local"}))[
            "deployed"
        ]
        != "verified"
    )
    assert (
        states(delivery.release_facts(RECEIPT, github, {**RUNTIME, "release_id": "other"}))[
            "deployed"
        ]
        != "verified"
    )
    assert (
        states(delivery.release_facts(RECEIPT, github, {**RUNTIME, "release_id": MERGED}))[
            "deployed"
        ]
        == "verified"
    )
    assert (
        states(
            delivery.release_facts(
                RECEIPT, github, {**RUNTIME, "release_id": "xcagi-1.0.0.1-" + SOURCE}
            )
        )["deployed"]
        != "verified"
    )
    github.ancestry = "ahead"
    assert states(delivery.release_facts(RECEIPT, github, RUNTIME))["merged"] != "verified"


@pytest.mark.parametrize(
    "runs",
    [
        [],
        [{"name": "backend-test", "conclusion": "skipped"}],
        [{"name": "backend-test", "conclusion": "failure"}],
    ],
)
def test_missing_skipped_or_failed_checks_never_prove_tests_passed(runs):
    github = GitHub()
    github.runs = runs
    assert states(delivery.release_facts(RECEIPT, github, RUNTIME))["tests"] != "passed"


def test_other_repository_and_ambiguous_pr_never_prove_merge():
    github = GitHub()
    github.pulls *= 2
    assert delivery.release_facts(RECEIPT, github, RUNTIME)["error"] == "pull_request_ambiguous"
    github.pulls = [{**github.pulls[0], "base": {"repo": {"full_name": "other/repo"}}}]
    assert delivery.release_facts(RECEIPT, github, RUNTIME)["error"] == "pull_request_missing"


def test_release_observations_survive_reopen_and_failure_cannot_complete_customer(
    tmp_path, monkeypatch
):
    github = GitHub()
    monkeypatch.setenv("MODSTORE_PARA_REPO_URL", "https://github.com/42433422/XCMAX.git")
    monkeypatch.setattr(delivery, "GitHubEvidence", lambda: github)
    monkeypatch.setattr(delivery, "health_payload", lambda: RUNTIME)
    clock = [1000.0]
    monkeypatch.setattr(delivery.time, "time", lambda: clock[0])
    engine = create_engine("sqlite:///" + str(tmp_path / "test.db"))
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        task = accept(db, actor="fixture", key="delivery-fixture", request={"message": "fixture"})
        task.snapshot_json = json.dumps(
            {"reports": [{"applied": True, "status": "completed", "report": json.dumps(RECEIPT)}]}
        )
        db.commit()
        task_id = task.id
        customer = {
            "tickets": [
                {
                    "delivery_verification": {
                        "customer_acceptance": "accepted",
                        "completed": False,
                        "runtime_business_verified": False,
                        "receipts": [],
                    }
                }
            ]
        }
        result = delivery.delivery_trace(db, task, customer)
        assert states(result)["business"] == "unknown"
        assert states(result)["installed"] == "unknown"
        verification = customer["tickets"][0]["delivery_verification"]
        verification.update(
            completed=True, runtime_business_verified=True, verified_host_shas=[SOURCE]
        )
        assert states(delivery.delivery_trace(db, task, customer))["business"] == "unknown"
        assert states(delivery.delivery_trace(db, task, customer))["installed"] == "unknown"
        verification["verified_host_shas"] = [MERGED]
        assert states(delivery.delivery_trace(db, task, customer))["business"] == "verified"
        assert states(delivery.delivery_trace(db, task, customer))["installed"] == "verified"
        calls = len(github.calls)
        delivery.delivery_trace(db, task, customer)
        assert len(github.calls) == calls
        assert db.query(MacControlEvent).filter_by(state="delivery_evidence_updated").count() == 1
    engine.dispose()
    engine = create_engine("sqlite:///" + str(tmp_path / "test.db"))
    with Session(engine) as db:
        from modstore_server.db.mac_control import MacControlTask

        task = db.get(MacControlTask, task_id)
        assert delivery.delivery_trace(db, task)["freshness"] == "fresh"
        clock[0] += 121
        github.fail = True
        result = delivery.delivery_trace(db, task)
        assert result["freshness"] == "unavailable"
        assert states(result)["business"] == "unknown"
        assert "secret-fixture" not in json.dumps(result)
    engine.dispose()


def test_employee_ticket_link_uses_business_owner_not_supplied_customer(tmp_path, monkeypatch):
    from modstore_server import mac_control_delegate as delegate
    from modstore_server.db.mac_control import MacControlTask
    from modstore_server.models import User
    from modstore_server.models_cs import CustomerServiceSession, CustomerServiceTicket

    engine = create_engine("sqlite:///" + str(tmp_path / "employee.db"))
    Base.metadata.create_all(engine)
    monkeypatch.setattr(delegate, "get_session_factory", lambda: lambda: Session(engine))
    with Session(engine) as db:
        user = User(username="linked-customer", password_hash="fixture")
        db.add(user)
        db.flush()
        session = CustomerServiceSession(user_id=user.id)
        db.add(session)
        db.flush()
        ticket = CustomerServiceTicket(
            user_id=user.id, session_id=session.id, ticket_no="linked-fixture"
        )
        db.add(ticket)
        db.commit()
        ticket_id, owner = ticket.id, user.id
    bad = delegate.accept_employee(
        "fixture",
        {"incident_event_id": "event-1", "ticket_id": ticket_id, "customer_id": 999},
        "employee",
    )
    assert bad["status"] == "blocked_invalid_ticket_identity"
    result = delegate.accept_employee(
        "fixture", {"incident_event_id": "event-1", "ticket_id": ticket_id}, "employee"
    )
    with Session(engine) as db:
        request = json.loads(db.get(MacControlTask, result["correlation_id"]).request_json)
        assert request["ticket_id"] == ticket_id and request["customer_id"] == owner
        assert db.query(MacControlTask).count() == 1
    engine.dispose()
