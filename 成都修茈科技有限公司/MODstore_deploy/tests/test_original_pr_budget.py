"""Original PR budgets preserve native recovery, authority and final CI evidence."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from modstore_server import customer_ticket_github
from modstore_server import para_github_repair as repair
from modstore_server import strategic_company_resources as company
from modstore_server import strategic_portfolio as portfolio
from modstore_server import strategic_workspace_bridge as bridge
from modstore_server import strategic_workspace_receipts as receipts
from modstore_server.db.mac_control import MacControlTask
from modstore_server.para_execution_isolation import HEADER_ONLY_PLATFORM_PROFILE
from tests import test_strategic_pr_repair as original

# These are the same real company approval, Mac HTTP and model gateway fixtures.
database = original.database
configured = original.configured
upstream_master = original.upstream_master
gateway = original.gateway
work = original.work
REPO = original.REPO
SOURCE, CONTROLLER, CANDIDATE = original.SOURCE, original.CONTROLLER, original.CANDIDATE


def _start(work, monkeypatch, *, lost_ack=False):
    if not lost_ack:
        original.start(work)
        return
    sync, attempts = repair.sync, []

    def response_lost():
        raise repair.ParaUnavailable("submit response lost after native task creation")

    def observe_original(factory):
        sync(factory)
        if work.raw and not attempts:
            with factory() as db:
                row = db.get(MacControlTask, work.task_id)
                assert not row.para_task_id and row.attempt_id
                attempts.append(row.attempt_id)
            sync(factory)  # The next normal scheduler pass reads the original native task.
            with factory() as db:
                row = db.get(MacControlTask, work.task_id)
                assert row.para_task_id == "para-one" and row.attempt_id == attempts[0]

    work.on_submit = response_lost
    with monkeypatch.context() as scoped:
        scoped.setattr(repair, "sync", observe_original)
        original.start(work)
    assert attempts == [work.attempt]
    assert len(work.submissions) == len(work.writes) == 1


@pytest.mark.parametrize("lost_ack", [False, True])
@pytest.mark.parametrize("final_ci", ["success", "failure"])
def test_original_task_budget_native_usage_publication_and_original_ci_close_once(
    work, monkeypatch, lost_ack, final_ci
):
    original.approve(work)
    _start(work, monkeypatch, lost_ack=lost_ack)
    assert work.grant["request_id"] == work.request_id and "event_id" not in work.grant
    assert work.grant["kind"] == repair.REPAIR_KIND and work.grant["schema"] == repair.SCHEMA
    submitted = work.submissions[0]
    assert submitted["branch"] == SOURCE and submitted["tool_name"] == "opencode"
    assert submitted["max_attempts"] == 1 and submitted["auto_merge"] is False
    seen = original.call_model(work, monkeypatch)
    observed = original.candidate(work)
    assert observed["publication_candidate"]["commit_sha"] == CANDIDATE
    assert observed["strategic_budget"]["request_id"] == work.request_id
    assert observed["strategic_budget"]["kind"] == repair.REPAIR_KIND
    assert observed["strategic_budget"]["schema"] == repair.SCHEMA
    assert observed["model_allocation"]["execution_isolation"] == HEADER_ONLY_PLATFORM_PROFILE
    published = original.publish(work)
    assert published["finished"] and published["conclusion"] == "success"
    assert original.publisher_proof(work, published).authorization["authorized"] is True
    with work.factory() as db:
        row = db.get(MacControlTask, work.task_id)
        assert row.state == "execution_completed" and row.reason == repair.CI_PENDING
        assert (row.request_json, row.request_digest) == (work.original_json, work.original_digest)
    work.pr_labels = ["needs-human"]
    refused = work.client.get(work.status_url, headers=work.auth).json()
    assert refused["publication_authorization"]["authorized"] is False
    assert refused["publication_candidate"] == published["publication_candidate"]
    assert refused["finished"] and refused["conclusion"] == "success"
    if lost_ack:
        company.revoke_company(
            work.company_id, authorizer_user_id=7, actor="admin:7", reason="operator veto"
        )
    else:
        portfolio.stop_portfolio(
            work.decision_id, owner_user_id=7, actor="admin:7", reason="operator veto"
        )
    receipts.reconcile_request(work.request_id)
    assert portfolio.portfolio_status(work.decision_id)["tasks"]["a"]["status"] == "waiting"
    original.original_ci(work)
    repair.sync(work.factory)
    assert portfolio.portfolio_status(work.decision_id)["tasks"]["a"]["status"] == "waiting"
    original.original_ci(work, status="completed", conclusion=final_ci)
    repair.sync(work.factory)
    saved = portfolio.portfolio_status(work.decision_id)["tasks"]["a"]
    assert saved["status"] == ("completed" if final_ci == "success" else "failed")
    receipt = saved["execution_receipt"]["remote_receipt"]
    assert receipt["verification"]["head_sha"] == CANDIDATE
    assert receipt["verification"]["run_id"] == 100
    assert receipt["delivery"]["status"] == "not_verified"
    assert not receipts.reconcile_request(work.request_id)
    repair.sync(work.factory)
    assert len(seen["requests"]) == len(work.writes) == len(work.submissions) == 1
    assert saved["actual_tokens"] == 13 and len(saved["calls"]) == 1
    assert "model_grant" not in saved["remote_state"]
    assert all(grant["status"] == "closed" for grant in saved["remote_state"]["task_grants"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("attempt_id", "0" * 32),
        ("task_id", "foreign-task"),
        ("base_branch", CONTROLLER),
        ("device_id", "foreign-device"),
        ("phase", "resume"),
    ],
)
def test_original_grant_rejects_other_tasks_or_controller_as_source(
    work, monkeypatch, field, value
):
    original.approve(work)
    original.start(work)
    if field == "task_id":
        native = original.mac_control_transport.ParaClient

        class Para(native):
            def task(self, task_id):
                if task_id == value:
                    return {**deepcopy(work.raw), "id": value}
                return super().task(task_id)

        monkeypatch.setattr(original.mac_control_transport, "ParaClient", Para)
    response = work.client.post(
        work.control + "/task-grant",
        json={**work.identity, field: value},
        headers={"Authorization": f"Bearer {work.bootstrap}"},
    )
    assert response.status_code == 409, response.text
    assert not portfolio.portfolio_status(work.decision_id)["tasks"]["a"]["calls"]


@pytest.mark.parametrize("change", ["request", "incident", "company"])
def test_original_authority_revocation_blocks_new_model_calls(work, change):
    original.approve(work)
    original.start(work)
    if change == "request":
        with work.factory() as db:
            row = db.get(MacControlTask, work.task_id)
            request = json.loads(row.request_json)
            request["message"] = "different operation"
            row.request_json = json.dumps(request)
            db.commit()
    elif change == "incident":
        work.incident_labels = ["auto-incident"]
    else:
        company.revoke_company(
            work.company_id, authorizer_user_id=7, actor="admin:7", reason="operator veto"
        )
    response = work.client.get(
        work.control + "/v1/models",
        headers={"Authorization": f"Bearer {work.grant['model_token']}"},
    )
    assert response.status_code == 409
    assert not portfolio.portfolio_status(work.decision_id)["tasks"]["a"]["calls"]


def test_original_unknown_usage_cannot_publish_or_replay(work, monkeypatch):
    original.approve(work)
    original.start(work)
    original.call_model(work, monkeypatch, meter="absent")
    assert not bridge.candidate_metered(work.request_id, work.grant)
    observed = original.candidate(work)
    assert observed["publication_authorization"]["authorized"] is False
    replay = work.client.post(
        work.control + "/claim",
        headers=work.auth,
        json={
            "run_id": 42,
            "run_attempt": 1,
            "repository": REPO,
            "source_sha": CONTROLLER,
            "phase": "execute",
            "execution_isolation": HEADER_ONLY_PLATFORM_PROFILE,
        },
    )
    assert replay.status_code == 409
    repair.sync(work.factory)
    assert len(work.writes) == len(work.submissions) == 1


def test_older_unbudgeted_request_does_not_starve_approved_original(work, monkeypatch):
    with work.factory() as db:
        current = db.get(MacControlTask, work.task_id)
        db.add(
            MacControlTask(
                id="f" * 32,
                actor=repair.REPAIR_ACTOR,
                request_key="older-unbudgeted-original",
                request_digest=current.request_digest,
                request_json=current.request_json,
                state="queued",
                reason="",
                para_task_id="",
                attempt_id="",
                device_id="",
                lease_until=0,
                snapshot_json="{}",
                created_at=0,
                updated_at=0,
            )
        )
        db.commit()
    original.approve(work)
    monkeypatch.setattr(repair.time, "time", lambda: 1_000_000_000.0)
    before = list(work.reads)
    repair.sync(work.factory)
    assert work.reads == before and not work.writes and not work.submissions
    sync = repair.sync

    def rotate(factory):
        sync(factory)
        sync(factory)

    with monkeypatch.context() as scoped:
        scoped.setattr(repair, "sync", rotate)
        original.start(work)
    assert work.grant["request_id"] == work.request_id
    assert work.grant["kind"] == repair.REPAIR_KIND and work.grant["schema"] == repair.SCHEMA
    assert len(work.writes) == len(work.submissions) == 1
    with work.factory() as db:
        old = db.get(MacControlTask, "f" * 32)
        assert old.state == "awaiting_approval" and not old.attempt_id


def test_worker_recovery_reads_beyond_three_pages_without_filters():
    seen = []

    def github(_method, path):
        assert "event=" not in path and "branch=" not in path
        page = int(path.rsplit("=", 1)[1])
        seen.append(page)
        return {
            "total_count": 301,
            "workflow_runs": [
                {"id": i, "display_title": "original" if i == 301 else "other"}
                for i in range((page - 1) * 100 + 1, min(page * 100, 301) + 1)
            ],
        }

    assert repair._find_run(github, REPO, "original") == 301
    assert seen == [1, 2, 3, 4]


@pytest.mark.parametrize(
    "rows,total",
    [
        ([{"id": 1, "display_title": "same"}, {"id": 2, "display_title": "same"}], 2),
        ([{"id": 1, "display_title": "same"}], 2),
        ([{"id": 1, "display_title": "same"}, {"id": 1, "display_title": "same"}], 2),
    ],
)
def test_worker_recovery_requires_complete_unique_run_inventory(rows, total):
    assert (
        repair._find_run(lambda *_: {"workflow_runs": rows, "total_count": total}, REPO, "same")
        is None
    )


@pytest.mark.parametrize("mutation", ["duplicate", "attempt", "run", "source", "inventory"])
def test_original_publication_requires_one_complete_native_publisher(work, monkeypatch, mutation):
    original.approve(work)
    original.start(work)
    original.call_model(work, monkeypatch)
    original.candidate(work)
    work.run.update(status="completed", conclusion="success")
    work.jobs[0].update(status="completed", conclusion="success")
    job = {**work.jobs[0], "id": 102, "name": "publish-candidate"}
    work.jobs.append(job)
    if mutation == "duplicate":
        work.jobs.append({**job, "id": 103, "conclusion": "failure"})
    elif mutation != "inventory":
        job[{"attempt": "run_attempt", "run": "run_id", "source": "head_sha"}[mutation]] = (
            "0" * 40 if mutation == "source" else 2
        )
    if mutation == "inventory":

        def github(method, path, body=None):
            result = deepcopy(work.github(method, path, body))
            if "/jobs?" in path:
                result["total_count"] += 1
            return result

        monkeypatch.setattr(customer_ticket_github, "github", github)
    repair.sync(work.factory)
    observed = work.client.get(work.status_url, headers=work.auth).json()
    assert observed["finished"] is False
    task = work.client.get(
        f"/api/service/mac-control/tasks/{work.task_id}", headers=work.auth
    ).json()["task"]
    assert not task["terminal"] and not task["execution"].get("reports")
    assert portfolio.portfolio_status(work.decision_id)["tasks"]["a"]["status"] == "running"
    assert original.company.totals(work.company_id)["slots"] == 1
    assert len(work.writes) == len(work.submissions) == 1
