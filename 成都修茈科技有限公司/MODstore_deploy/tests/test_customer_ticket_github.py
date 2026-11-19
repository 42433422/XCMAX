"""Public issue submission has durable receipts; GitHub completion is not acceptance."""

import uuid

import pytest
from fastapi import HTTPException

from modstore_server import customer_ticket_github as bridge
from modstore_server.api.deps import require_admin
from modstore_server.app import app
from modstore_server.models import User, get_session_factory
from modstore_server.models_cs import (
    CustomerServiceAction,
    CustomerServiceSession,
    CustomerServiceTicket,
)


@pytest.fixture
def ticket(client, monkeypatch):
    monkeypatch.setenv("MODSTORE_GITHUB_TOKEN", "test-only-never-published")
    monkeypatch.setenv("MODSTORE_GITHUB_REPOSITORY", "42433422/XCMAX")
    monkeypatch.setenv("MODSTORE_PARA_GITHUB_DEVICE_ID", "github-worker-test")
    monkeypatch.setenv("MODSTORE_PARA_GITHUB_API_BASE", "https://para.example.test")
    monkeypatch.setenv("MODSTORE_PARA_GITHUB_AUTH_TOKEN", "test-only-para")
    with get_session_factory()() as db:
        from modstore_server.db.mac_control import MacControlSyncLease

        db.query(MacControlSyncLease).filter_by(id="github-worker").delete()
        user = User(username=uuid.uuid4().hex, password_hash="x", is_admin=True)
        owner = User(username=uuid.uuid4().hex, password_hash="x", is_admin=False)
        db.add_all([user, owner])
        db.flush()
        session = CustomerServiceSession(user_id=owner.id, channel="customer_issue_intake")
        db.add(session)
        db.flush()
        row = CustomerServiceTicket(
            user_id=owner.id,
            session_id=session.id,
            ticket_no=uuid.uuid4().hex,
            intent="product_issue",
            status="open",
            title="PRIVATE CUSTOMER TITLE",
            summary="PRIVATE IDENTITY AND ATTACHMENT",
            evidence_json='{"private":"support-bundle"}',
        )
        db.add(row)
        db.commit()
        db.refresh(user)
        db.refresh(row)
        ident = row.id
        db.expunge(user)
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[require_admin] = lambda: user
    yield ident
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous)


@pytest.fixture
def isolated_publisher_stub(monkeypatch):
    """Exercise downstream contracts only; production intentionally has no publisher."""
    from modstore_server import para_github_runner

    monkeypatch.setattr(para_github_runner, "publisher_capability", lambda: {"available": True})


DRAFT = {
    "title": "员工图谱显示故障",
    "body": "复现步骤：打开员工图谱。预期：员工节点正常展示。实际：节点空白。验收：重新打开有节点。",
    "confirm_public": True,
}


def test_publish_idempotent_and_private_source_never_sent(client, ticket, monkeypatch):
    sent = []

    def github(method, path, body=None):
        sent.append((method, path, body))
        return {"number": 123}

    monkeypatch.setattr(bridge, "github", github)
    path = f"/api/customer-service/tickets/{ticket}/github"
    for _ in range(2):
        result = client.post(path, json=DRAFT)
        assert result.status_code == 200, result.text
        assert result.json()["number"] == 123
    assert len(sent) == 1
    assert "PRIVATE" not in str(sent) and "support-bundle" not in str(sent)
    with get_session_factory()() as db:
        row = db.get(CustomerServiceTicket, ticket)
        assert row.status == "open" and row.summary == "PRIVATE IDENTITY AND ATTACHMENT"
        assert db.query(CustomerServiceAction).filter_by(ticket_id=ticket).count() == 1


def test_unknown_create_is_never_replayed_and_can_reconcile(client, ticket, monkeypatch):
    bodies = []

    def timeout(method, path, body=None):
        bodies.append(body)
        raise HTTPException(502, "uncertain")

    monkeypatch.setattr(bridge, "github", timeout)
    path = f"/api/customer-service/tickets/{ticket}/github"
    assert client.post(path, json=DRAFT).status_code == 502
    assert client.post(path, json=DRAFT).json()["status"] == "unknown"
    assert len(bodies) == 1

    def readback(method, path, body=None):
        assert method == "GET"
        if "issues?" in path:
            return [{"number": 123, "body": bodies[0]["body"]}]
        if path.endswith("issues/123"):
            return {"number": 123, "state": "closed"}
        return []

    monkeypatch.setattr(bridge, "github", readback)
    result = client.post(path + "/reconcile", json={})
    assert result.status_code == 200, result.text
    assert result.json()["issue"]["number"] == 123
    with get_session_factory()() as db:
        assert db.get(CustomerServiceTicket, ticket).status == "open"


def test_publish_requires_admin_public_review_and_open_product_ticket(client, ticket, monkeypatch):
    monkeypatch.setattr(bridge, "github", lambda *args: pytest.fail("must not publish"))
    path = f"/api/customer-service/tickets/{ticket}/github"
    assert client.post(path, json={**DRAFT, "confirm_public": False}).status_code == 422
    with get_session_factory()() as db:
        row = db.get(CustomerServiceTicket, ticket)
        row.status = "resolved"
        db.commit()
    assert client.post(path, json=DRAFT).status_code == 409

    def denied():
        raise HTTPException(403, "admin required")

    app.dependency_overrides[require_admin] = denied
    assert client.get(path).status_code == 403
    assert client.get("/api/customer-service/github/workspace").status_code == 403


@pytest.mark.usefixtures("isolated_publisher_stub")
def test_legacy_unknown_execution_blocks_cloud_start(client, ticket, monkeypatch):
    from modstore_server import customer_ticket_execution

    monkeypatch.setattr(
        customer_ticket_execution, "_current_claim", lambda *args: (1, {"ok": False})
    )
    monkeypatch.setattr(bridge, "github", lambda *args: {"number": 123})
    path = f"/api/customer-service/tickets/{ticket}/github"
    client.post(path, json=DRAFT)
    result = client.post(path + "/start", json={"request_id": str(uuid.uuid4())})
    assert result.status_code == 409 and "原执行任务" in result.text


def test_issue_links_original_owner_work_order_without_changing_status(client, ticket, monkeypatch):
    from modstore_server.work_order_api import (
        CandidateBody,
        _create_candidate,
        _find_by_issue,
    )

    with get_session_factory()() as db:
        row = db.get(CustomerServiceTicket, ticket)
        candidate = _create_candidate(
            db,
            CandidateBody(
                source="client_ai_product_issue",
                dedup_key=uuid.uuid4().hex,
                reason="product_defect",
                context={"customer_reported": True, "customer_user_id": row.user_id},
            ),
        )
        row.evidence_json = bridge.json_dumps({"work_order_id": candidate["wo_id"]})
        db.commit()
    monkeypatch.setattr(bridge, "github", lambda *args: {"number": 987})
    response = client.post(f"/api/customer-service/tickets/{ticket}/github", json=DRAFT)
    assert response.status_code == 200, response.text
    with get_session_factory()() as db:
        view = _find_by_issue(db, 987)
        assert view and view["wo_id"] == candidate["wo_id"]
        assert db.get(CustomerServiceTicket, ticket).status == "open"


@pytest.mark.usefixtures("isolated_publisher_stub")
def test_start_uses_existing_employee_outbox_once_without_model_or_workflow_dispatch(
    client, ticket, monkeypatch
):
    from modstore_server.eventing import db_outbox

    calls = []

    def github(method, path, body=None):
        calls.append((method, path))
        assert "/actions/" not in path
        return {"number": 123} if method == "POST" else {"state": "open"}

    monkeypatch.setattr(bridge, "github", github)
    path = f"/api/customer-service/tickets/{ticket}/github"
    client.post(path, json=DRAFT)
    request = {"request_id": str(uuid.uuid4())}
    first = client.post(path + "/start", json=request)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "queued"
    assert (
        client.post(path + "/start", json={"request_id": str(uuid.uuid4())}).json() == first.json()
    )
    rows = [r for r in db_outbox.fetch_pending(limit=100) if r.payload.get("ticket_id") == ticket]
    assert len(rows) == 1
    assert rows[0].payload["github_workspace"]["issue_number"] == 123
    with get_session_factory()() as db:
        action = (
            db.query(CustomerServiceAction)
            .filter_by(ticket_id=ticket, action_type=bridge.RUN_ACTION)
            .one()
        )
        assert rows[0].payload["github_workspace"]["action_id"] == action.id
    assert len([c for c in calls if c[0] == "POST"]) == 1


@pytest.mark.usefixtures("isolated_publisher_stub")
def test_no_cloud_para_binding_means_no_dispatch(client, ticket, monkeypatch):
    monkeypatch.delenv("MODSTORE_PARA_GITHUB_DEVICE_ID")
    monkeypatch.setattr(bridge, "github", lambda *args: {"number": 123})
    path = f"/api/customer-service/tickets/{ticket}/github"
    client.post(path, json=DRAFT)
    response = client.post(path + "/start", json={"request_id": str(uuid.uuid4())})
    assert response.status_code == 503 and "GitHub 临时" in response.text
    with get_session_factory()() as db:
        assert (
            db.query(CustomerServiceAction)
            .filter_by(ticket_id=ticket, action_type=bridge.RUN_ACTION)
            .count()
            == 0
        )


def test_private_mod_does_not_enter_public_shared_repair(client, ticket, monkeypatch):
    with get_session_factory()() as db:
        db.get(CustomerServiceTicket, ticket).evidence_json = '{"issue_domain":"custom"}'
        db.commit()
    monkeypatch.setattr(bridge, "github", lambda *args: pytest.fail("private Mod must not publish"))
    result = client.post(f"/api/customer-service/tickets/{ticket}/github", json=DRAFT)
    assert result.status_code == 409


@pytest.mark.usefixtures("isolated_publisher_stub")
def test_github_runner_acknowledgement_then_original_outbox_incident(client, ticket, monkeypatch):
    from datetime import UTC, datetime

    import httpx

    from modstore_server import customer_issue_intake as intake
    from modstore_server import incident_bus
    from modstore_server import para_github_runner as runner
    from modstore_server.eventing import db_outbox
    from modstore_server.models import IncidentEvent

    request_id = str(uuid.uuid4())
    posts = []

    def github(method, path, body=None):
        if method == "POST":
            posts.append(path)
            return {} if path.endswith("dispatches") else {"number": 123}
        if path.endswith("issues/123"):
            return {"state": "open"}
        if "?event=" in path:
            return {
                "workflow_runs": [
                    {
                        "id": 456,
                        "head_branch": "main",
                        "display_title": f"para-workspace-{request_id}",
                    }
                ]
            }
        return {"status": "in_progress", "run_attempt": 1}

    monkeypatch.setattr(bridge, "github", github)
    path = f"/api/customer-service/tickets/{ticket}/github"
    client.post(path, json=DRAFT)
    client.post(path + "/start", json={"request_id": request_id})
    record = next(
        r for r in db_outbox.fetch_pending(limit=100) if r.payload.get("ticket_id") == ticket
    )
    real_client = httpx.Client
    device = {
        "id": "github-worker-test",
        "status": "online",
        "lastSeen": datetime.now(UTC).isoformat(),
        "tools": [{"toolName": "codex", "status": "idle"}],
        "capabilities": {
            "github_actions": True,
            "github_request_id": request_id,
            "github_run_id": "456",
            "github_run_attempt": "1",
        },
    }
    monkeypatch.setattr(
        runner.httpx,
        "Client",
        lambda **kw: real_client(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(200, json={"devices": [device]})
            )
        ),
    )
    observed = []

    def publish(kind, payload, *, source, fingerprint, dedupe_minutes, inbox_key):
        eid, _ = intake._persist_incident(
            kind, payload, source, fingerprint, dedupe_minutes, inbox_key
        )
        observed.append((eid, payload))
        return eid

    monkeypatch.setattr(incident_bus, "publish", publish)
    first = intake.dispatch_issue_event(record.to_envelope())
    assert first["skipped"] and not first["ok"] and not observed
    assert intake.dispatch_issue_event(record.to_envelope())["ok"]
    assert len([p for p in posts if p.endswith("dispatches")]) == 1
    eid, payload = observed[0]
    assert payload["github_workspace"]["public_summary"].startswith(DRAFT["body"])
    from modstore_server.incident_team_dispatch import member_runtime_input

    public_runtime = member_runtime_input(
        employee_id="original-code-employee",
        role="fix",
        event_id=eid,
        team_plan={},
        payload=payload,
        event_type="ops.intake.customer_ticket",
        source="customer_ticket",
        route={},
        attempt_id=uuid.uuid4().hex,
    )
    assert "PRIVATE" not in str(public_runtime)
    assert public_runtime["incident"]["summary"].startswith(DRAFT["body"])
    from modstore_server import para_delegate_handler

    request = para_delegate_handler._build_request(
        task=DRAFT["body"],
        input_data=public_runtime,
        employee_id="original-code-employee",
    )
    assert request["title"].startswith("[xcmax:") and request["max_attempts"] == 1
    assert "PRIVATE" not in para_delegate_handler._build_para_prompt(request)
    with get_session_factory()() as db:
        assert bridge.authorized_incident(db, payload, eid)
        assert not bridge.authorized_incident(db, payload, eid + 1)
        event = db.get(IncidentEvent, eid)
        attempt = uuid.uuid4().hex
        event.payload_json = bridge.json_dumps(
            {
                **payload,
                "_team_claim": {
                    "team": [
                        {
                            "role": "fix",
                            "employee_id": "original-code-employee",
                            "attempt_id": attempt,
                            "status": "dispatching",
                        }
                    ]
                },
            }
        )
        db.commit()
        runtime = {
            "_trusted_incident_team_execution": True,
            "event_id": eid,
            "role": "fix",
            "attempt_id": attempt,
            "github_workspace": payload["github_workspace"],
        }
        assert runner.authorized_dispatch(runtime, "original-code-employee")
        assert not runner.authorized_dispatch(runtime, "other-employee")
        assert not runner.authorized_dispatch(
            {**runtime, "attempt_id": uuid.uuid4().hex}, "original-code-employee"
        )
        event.payload_json = bridge.json_dumps(
            {
                **payload,
                "_team_claim": {
                    "ok": True,
                    "team": [
                        {
                            "role": "fix",
                            "employee_id": "original-code-employee",
                            "ok": True,
                            "status": "completed",
                        }
                    ],
                },
            }
        )
        db.commit()
        status = runner.run_status(db, request_id)
        assert status["finished"] and status["conclusion"] == "success"
        assert status["jobs"][0]["employee_id"] == "original-code-employee"
        assert "PRIVATE" not in str(status)


@pytest.mark.usefixtures("isolated_publisher_stub")
def test_uncertain_workflow_dispatch_is_not_replayed(client, ticket, monkeypatch):
    from modstore_server import para_github_runner as runner
    from modstore_server.eventing import db_outbox

    path = f"/api/customer-service/tickets/{ticket}/github"
    monkeypatch.setattr(bridge, "github", lambda *a: {"number": 123, "state": "open"})
    client.post(path, json=DRAFT)
    client.post(path + "/start", json={"request_id": str(uuid.uuid4())})
    record = next(
        r for r in db_outbox.fetch_pending(limit=100) if r.payload.get("ticket_id") == ticket
    )
    posts = []

    def github(method, path, body=None):
        if method == "POST":
            posts.append(path)
            raise HTTPException(502, "unknown")
        return {"workflow_runs": []}

    monkeypatch.setattr(bridge, "github", github)
    with get_session_factory()() as db:
        for _ in range(3):
            assert not runner.ensure_runner(db, record.payload)
        assert len(posts) == 1
        assert (
            db.query(CustomerServiceAction)
            .filter_by(ticket_id=ticket, action_type=bridge.RUN_ACTION)
            .one()
            .status
            == "unknown"
        )


@pytest.mark.parametrize("before_slot_claim", [False, True])
def test_revocation_fences_github_runner_at_slot_claim(
    client, ticket, monkeypatch, isolated_publisher_stub, before_slot_claim
):
    from modstore_server import customer_issue_intake as intake
    from modstore_server import para_github_runner as runner
    from modstore_server.db.mac_control import MacControlSyncLease
    from modstore_server.eventing import db_outbox

    posts = []

    def github(method, path, body=None):
        if method == "POST":
            posts.append(path)
        return {"number": 123, "state": "open"}

    monkeypatch.setattr(bridge, "github", github)
    path = f"/api/customer-service/tickets/{ticket}"
    admin = app.dependency_overrides[require_admin]()
    assert (
        client.post(
            f"{path}/assign", json={"assignee_id": admin.id, "reason": "接手原工单"}
        ).status_code
        == 200
    )
    assert client.post(f"{path}/github", json=DRAFT).status_code == 200
    assert (
        client.post(f"{path}/github/start", json={"request_id": str(uuid.uuid4())}).status_code
        == 200
    )
    record = next(
        row for row in db_outbox.fetch_pending(limit=100) if row.payload.get("ticket_id") == ticket
    )
    original_claim = runner._claim_worker_slot

    def claim_and_revoke(db, row):
        if not before_slot_claim:
            assert original_claim(db, row)
        result = client.post(
            f"{path}/dispatch-revoke",
            json={"request_id": str(uuid.uuid4()), "note": "原单保留，此次不再启动临时执行器。"},
        )
        assert result.status_code == 200, result.text
        assert result.json()["ticket"]["status"] == "open"
        assert (
            result.json()["ticket"]["dispatch_revocation"]["execution_stop"]["state"]
            == "dispatch_blocked"
        )
        return original_claim(db, row) if before_slot_claim else True

    monkeypatch.setattr(runner, "_claim_worker_slot", claim_and_revoke)
    result = intake.dispatch_issue_event(record.to_envelope())
    assert result["status"] == "blocked" and result["reason"] == "ticket_dispatch_revoked"
    assert not any(path.endswith("/dispatches") for path in posts)
    with get_session_factory()() as db:
        slot = db.get(MacControlSyncLease, "github-worker")
        assert not slot.owner


def test_github_fix_receipt_is_bound_to_pushed_branch_and_commit(ticket, monkeypatch):
    from modstore_server.para_github_runner import verified_code_identity

    value = {
        "source": "executor_git_readback",
        "pushed": True,
        "branch": "devfleet/codex/test",
        "commit_sha": "a" * 40,
        "archive_sha256": "b" * 64,
    }
    snapshot = {
        "subtasks": [{"branch": value["branch"]}],
        "logs_tail": [{"content": bridge.json_dumps(value)}],
    }
    monkeypatch.setattr(bridge, "github", lambda *args: {"object": {"sha": "a" * 40}})
    assert verified_code_identity(snapshot)["commit_sha"] == "a" * 40
    monkeypatch.setattr(bridge, "github", lambda *args: {"object": {"sha": "c" * 40}})
    with pytest.raises(ValueError, match="不一致"):
        verified_code_identity(snapshot)
    snapshot["subtasks"] = [{"branch": "unrelated"}]
    with pytest.raises(ValueError, match="缺少"):
        verified_code_identity(snapshot)


def test_worker_slot_keeps_pending_jobs_in_management_until_prior_run_is_settled(
    ticket, monkeypatch
):
    from modstore_server import para_github_runner as runner

    with get_session_factory()() as db:
        original = db.get(CustomerServiceTicket, ticket)
        actions = [
            bridge.build_action(
                db,
                ticket_id=ticket,
                user_id=original.user_id,
                action_type=bridge.RUN_ACTION,
                target_type="github",
                target_id=str(i),
                request={"repository": "42433422/XCMAX"},
            )
            for i in range(2)
        ]
        db.commit()
        assert runner._claim_worker_slot(db, actions[0])
        assert runner._claim_worker_slot(db, actions[0])
        assert not runner._claim_worker_slot(db, actions[1])  # Unknown dispatch remains owned.
        receipt = {
            "run_id": 123,
            "receipts": [{"state": "running", "requires_reconciliation": True}],
        }
        monkeypatch.setattr(bridge, "_execution", lambda *args: (receipt, []))
        monkeypatch.setattr(bridge, "github", lambda *args: {"status": "completed"})
        assert not runner._claim_worker_slot(
            db, actions[1]
        )  # Ending the VM is not task settlement.
        receipt["receipts"] = [{"state": "completed", "completed": True}]
        monkeypatch.setattr(bridge, "github", lambda *args: {"status": "in_progress"})
        assert not runner._claim_worker_slot(db, actions[1])
        monkeypatch.setattr(bridge, "github", lambda *args: {"status": "completed"})
        assert runner._claim_worker_slot(db, actions[1])
        assert actions[0].status == "runner_stopped"


@pytest.mark.parametrize("intent", ["product_issue", "custom_delivery"])
def test_private_prerequisite_only_publishes_reviewed_summary(client, ticket, monkeypatch, intent):
    with get_session_factory()() as db:
        row = db.get(CustomerServiceTicket, ticket)
        row.intent = intent
        row.evidence_json = bridge.json_dumps(
            {
                "issue_domain": "custom",
                "shared_core_prerequisite": "PRIVATE prerequisite",
            }
        )
        db.commit()
    sent = []
    monkeypatch.setattr(
        bridge,
        "github",
        lambda method, path, body=None: sent.append(body) or {"number": 124},
    )
    response = client.post(f"/api/customer-service/tickets/{ticket}/github", json=DRAFT)
    assert response.status_code == 200, response.text
    assert len(sent) == 1 and "PRIVATE" not in str(sent)
    with get_session_factory()() as db:
        row = db.get(CustomerServiceTicket, ticket)
        assert row.intent == intent and "PRIVATE" in row.summary


@pytest.mark.parametrize(
    "evidence",
    [
        {"shared_core_prerequisite": ""},
        {"shared_core_prerequisite": {"unsafe": "not text"}},
        {
            "shared_core_prerequisite": "host fix",
            "shared_core_prerequisite_release": "released",
        },
    ],
)
def test_private_prerequisite_rejects_missing_or_released_scope(
    client, ticket, monkeypatch, evidence
):
    with get_session_factory()() as db:
        row = db.get(CustomerServiceTicket, ticket)
        row.evidence_json = bridge.json_dumps({"issue_domain": "custom", **evidence})
        db.commit()
    monkeypatch.setattr(bridge, "github", lambda *a: pytest.fail("no external operation"))
    assert (
        client.post(f"/api/customer-service/tickets/{ticket}/github", json=DRAFT).status_code == 409
    )


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"continuation_pending": True},
        {
            "failure_handled_attempts": ["a"],
            "follow_up_intents": {"a": {"state": "dispatching"}},
        },
    ],
)
def test_failed_attempt_does_not_finish_before_recovery(extra):
    claim = {"team": [{"status": "failed", "attempt_id": "a"}], **extra}
    assert not bridge._settled(claim, [])


def test_finished_requires_recovery_and_outstanding_receipts_settled():
    claim = {
        "team": [{"status": "failed", "attempt_id": "a"}],
        "failure_handled_attempts": ["a"],
        "follow_up_intents": {"a": {"state": "completed"}},
    }
    assert bridge._settled(claim, [])
    assert not bridge._settled(claim, [{"state": "pending"}])
    assert not bridge._settled(claim, [{"state": "completed", "requires_reconciliation": True}])
    assert not bridge._settled({**claim, "team": [{"status": "dispatching"}]}, [])


def test_retry_prompt_keeps_public_boundary(monkeypatch):
    from modstore_server import incident_team_orchestrator as orchestrator

    class Captured(Exception):
        pass

    def capture(**kwargs):
        assert kwargs["payload"] == {
            "scope": "fhd",
            "issue_domain": None,
            "intent": None,
            "source": None,
            "title": DRAFT["title"],
            "summary": DRAFT["body"],
        }
        raise Captured

    monkeypatch.setattr(orchestrator, "_task_for_role", capture)
    with pytest.raises(Captured):
        orchestrator._retry_member(
            event_id=1,
            member={"role": "fix", "employee_id": "test"},
            team_plan={},
            payload={
                "scope": "fhd",
                "summary": "PRIVATE",
                "user_id": 999,
                "ticket_no": "PRIVATE",
                "github_workspace": {
                    "public_title": DRAFT["title"],
                    "public_summary": DRAFT["body"],
                },
            },
            event_type="test",
            source="test",
            uid=0,
            prev_results={},
        )


@pytest.mark.usefixtures("isolated_publisher_stub")
def test_private_prerequisite_start_keeps_private_delivery_and_scopes_host(
    client, ticket, monkeypatch
):
    from modstore_server.eventing import db_outbox

    with get_session_factory()() as db:
        row = db.get(CustomerServiceTicket, ticket)
        row.intent = "custom_delivery"
        row.evidence_json = bridge.json_dumps(
            {
                "issue_domain": "custom",
                "shared_core_prerequisite": "PRIVATE host requirement",
            }
        )
        db.commit()
    monkeypatch.setattr(
        bridge,
        "github",
        lambda method, path, body=None: {"number": 124, "state": "open"},
    )
    path = f"/api/customer-service/tickets/{ticket}/github"
    assert client.post(path, json=DRAFT).status_code == 200
    captured = []
    monkeypatch.setattr(
        db_outbox,
        "enqueue",
        lambda db, kind, key, payload, **kw: captured.append(payload),
    )
    response = client.post(path + "/start", json={"request_id": str(uuid.uuid4())})
    assert response.status_code == 200, response.text
    assert len(captured) == 1
    assert captured[0]["intake_source"] == "private_mod_prerequisite"
    assert captured[0]["resolution"]["route"] == "shared_core"
    assert captured[0]["delivery_managed_by"] == "custom_delivery"
    assert captured[0]["github_workspace"]["issue_number"] == 124
    with get_session_factory()() as db:
        row = db.get(CustomerServiceTicket, ticket)
        assert row.intent == "custom_delivery" and "PRIVATE" in row.summary


def test_unavailable_publisher_blocks_start_and_reports_capability(client, ticket, monkeypatch):
    from modstore_server import para_github_runner as runner
    from modstore_server.eventing import db_outbox

    monkeypatch.setenv("PARA_GITHUB_ISOLATED_PUBLISHER", "true")
    monkeypatch.setattr(
        runner,
        "publisher_capability",
        lambda: {
            "available": False,
            "status": "blocked",
            "reason": "blocked_isolated_publisher_required",
        },
    )
    monkeypatch.setattr(bridge, "github", lambda *args: {"number": 123})
    path = f"/api/customer-service/tickets/{ticket}/github"
    assert client.post(path, json=DRAFT).status_code == 200
    monkeypatch.setattr(bridge, "github", lambda *args: pytest.fail("No GitHub call after block"))
    response = client.post(path + "/start", json={"request_id": str(uuid.uuid4())})
    assert response.status_code == 503
    capability = runner.publisher_capability()
    assert capability == response.json()["detail"]
    assert capability["available"] is False
    assert capability["reason"] == "blocked_isolated_publisher_required"
    assert (
        client.get("/api/customer-service/github/workspace").json()["publisher_capability"]
        == capability
    )
    assert not [
        r for r in db_outbox.fetch_pending(limit=100) if r.payload.get("ticket_id") == ticket
    ]
    with get_session_factory()() as db:
        assert (
            db.query(CustomerServiceAction)
            .filter_by(ticket_id=ticket, action_type=bridge.RUN_ACTION)
            .count()
            == 0
        )


def test_existing_queued_dispatch_becomes_durable_block_without_external_calls(
    client, ticket, monkeypatch
):
    from modstore_server import customer_issue_intake as intake
    from modstore_server import para_github_runner as runner
    from modstore_server.eventing import db_outbox

    request_id = str(uuid.uuid4())
    monkeypatch.setattr(bridge, "github", lambda *args: {"number": 123, "state": "open"})
    path = f"/api/customer-service/tickets/{ticket}/github"
    assert client.post(path, json=DRAFT).status_code == 200
    with monkeypatch.context() as permitted:
        permitted.setattr(runner, "publisher_capability", lambda: {"available": True})
        assert client.post(path + "/start", json={"request_id": request_id}).status_code == 200
    record = next(
        r for r in db_outbox.fetch_pending(limit=100) if r.payload.get("ticket_id") == ticket
    )
    monkeypatch.setattr(
        runner,
        "publisher_capability",
        lambda: {
            "available": False,
            "status": "blocked",
            "reason": "blocked_isolated_publisher_required",
        },
    )
    monkeypatch.setattr(
        bridge,
        "github",
        lambda *args: pytest.fail("Blocked runner must not call GitHub"),
    )
    result = intake.dispatch_issue_event(record.to_envelope())
    assert result["status"] == "blocked"
    assert result["reason"] == "blocked_isolated_publisher_required"
    with get_session_factory()() as db:
        assert runner.ensure_runner(db, record.payload) is None
        status = runner.run_status(db, request_id)
        assert status["finished"] is True
        assert status["status"] == "blocked"
        assert status["reason"] == "blocked_isolated_publisher_required"
