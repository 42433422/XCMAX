"""Customer-bound outcomes, commercial attribution and measured training feedback."""

import json
import os
from uuid import uuid4

import pytest

from modstore_server import retort_evolution as service
from modstore_server import retort_github_workspace as workspace
from modstore_server.api.deps import require_admin
from modstore_server.app import app
from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.models import IncidentEvent, RetortEvolutionRun, User, get_session_factory
from tests import test_retort_evolution as evolution_fixtures

setup = evolution_fixtures.setup
read = evolution_fixtures.read


def test_feedback_selection_scans_past_already_used_candidates(setup, monkeypatch):
    from modstore_server import retort_customer_feedback as feedback
    from modstore_server.models_cs import CustomerServiceSession, CustomerServiceTicket

    with get_session_factory()() as db:
        customer = User(username=uuid4().hex, password_hash="test-only", is_admin=False)
        db.add(customer)
        db.flush()
        session = CustomerServiceSession(user_id=customer.id)
        db.add(session)
        db.flush()
        tickets = [
            CustomerServiceTicket(
                user_id=customer.id,
                session_id=session.id,
                ticket_no=f"{uuid4()}",
                submitter_type="customer",
                intent="product_issue",
                status="open",
                summary="真实问题",
                evidence_json="{}",
            )
            for _ in range(21)
        ]
        db.add_all(tickets)
        db.flush()
        monkeypatch.setattr(
            feedback, "_eligible", lambda _db, item, _domain: item.user_id == customer.id
        )
        selected = feedback._candidates(db, "platform", {(item.id, "") for item in tickets[1:]})
        assert [item["ticket_id"] for item in selected.values()] == [tickets[0].id]


@pytest.mark.parametrize("boundary", ["selection", "private_context", "release_readback"])
@pytest.mark.parametrize(
    "hold", ["revoked", "admin_revoked", "pending_classification", "needs_review"]
)
def test_feedback_respects_persisted_intake_hold_at_each_boundary(setup, boundary, hold):
    from modstore_server import retort_customer_feedback as feedback
    from modstore_server.customer_ticket_human_ops import (
        accept_ticket,
        assign_ticket,
        revoke_ticket_dispatch,
    )
    from modstore_server.models_cs import (
        CustomerServiceAuditLog,
        CustomerServiceMessage,
        CustomerServiceSession,
        CustomerServiceTicket,
    )

    request_id = str(uuid4())
    with get_session_factory()() as db:
        customer = User(username=uuid4().hex, password_hash="test-only", is_admin=False)
        db.add(customer)
        db.flush()
        session = CustomerServiceSession(user_id=customer.id)
        db.add(session)
        db.flush()
        evidence = {"issue_domain": "platform", "resolution": {"state": "received"}}
        ticket = CustomerServiceTicket(
            user_id=customer.id,
            session_id=session.id,
            ticket_no=str(uuid4()),
            submitter_type="customer",
            intent="product_issue",
            status="open",
            summary="首次导入未成功",
            evidence_json=json_dumps(evidence),
        )
        db.add(ticket)
        db.flush()
        source = {
            "ticket_id": ticket.id,
            "ticket_no": ticket.ticket_no,
            "domain": "platform",
            "revision": "",
            "context_sha256": feedback._reproduction_digest(feedback._raw_reproduction(db, ticket)),
        }
        db.add(
            RetortEvolutionRun(
                id=request_id,
                user_id=setup["user"].id,
                status="delivered",
                protocol_json="{}",
                effects_json=json_dumps({"customer_feedback": source}),
            )
        )
        db.commit()
        assert feedback._eligible(db, ticket, "platform")
        if hold == "admin_revoked":
            admin = db.get(User, setup["user"].id)
            assign_ticket(db, ticket, admin, admin.id, "人工核对原反馈")
            accept_ticket(db, ticket, admin, "开始核对")
            revoke_ticket_dispatch(
                db, ticket, admin, request={"request_id": str(uuid4()), "note": "停止自动派发"}
            )
            assert ticket.status == "processing" and ticket.closed_at is None
        else:
            # Persisted holds also govern historical rows with no current assignee.
            evidence.update(
                {
                    "revoked": {"dispatch_revocation": {"request_id": str(uuid4())}},
                    "pending_classification": {"classification_status": "pending_verification"},
                    "needs_review": {"intake_review": {"disposition": "needs_review"}},
                }[hold]
            )
            ticket.evidence_json = json_dumps(evidence)
            db.commit()
        ticket_id = ticket.id
        before = (ticket.status, ticket.evidence_json, ticket.lock_version)
        audit_count = db.query(CustomerServiceAuditLog).filter_by(ticket_id=ticket_id).count()
        if boundary == "selection":
            candidates = feedback._candidates(db, "platform", set())
            assert ticket_id not in {row["ticket_id"] for row in candidates.values()}
        elif boundary == "private_context":
            with pytest.raises(ValueError, match="feedback_execution_ticket_unavailable"):
                feedback._selected_execution_context(db, db.get(RetortEvolutionRun, request_id))
    if boundary == "release_readback":
        impact = feedback.read_impact(
            request_id,
            {"status": "deployment_verified", "release_sha": "c" * 40, "deployment_run_id": 205},
        )
        assert impact["reason"] == "awaiting_ticket_release_binding"
    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, ticket_id)
        assert (ticket.status, ticket.evidence_json, ticket.lock_version) == before
        assert db.query(CustomerServiceMessage).filter_by(ticket_id=ticket_id).count() == 0
        assert (
            db.query(CustomerServiceAuditLog).filter_by(ticket_id=ticket_id).count() == audit_count
        )


@pytest.mark.parametrize(
    "customer_decision",
    [
        "resolved",
        "reopen",
        "resolved_then_reopen",
        "completed_then_reopen",
        "completion_race_then_reopen",
    ],
)
def test_feedback_run_binds_original_customer_and_production_release(
    setup, monkeypatch, customer_decision
):
    from datetime import UTC, datetime

    from modstore_server.api.deps import get_current_user
    from modstore_server.models_cs import (
        CustomerServiceMessage,
        CustomerServiceSession,
        CustomerServiceTicket,
    )

    ticket_no = f"isolated-feedback-{uuid4()}"
    with get_session_factory()() as db:
        customer = User(username=uuid4().hex, password_hash="test-only", is_admin=False)
        db.add(customer)
        db.flush()
        session = CustomerServiceSession(user_id=customer.id)
        db.add(session)
        db.flush()
        db.add(
            CustomerServiceTicket(
                user_id=customer.id,
                session_id=session.id,
                ticket_no=ticket_no,
                submitter_type="customer",
                intent="product_issue",
                status="open",
                summary="首次导入未成功。联系 test-private@example.com",
                evidence_json=json_dumps(
                    {
                        "issue_domain": "platform",
                        "resolution": {"state": "received", "route": "shared_core"},
                    }
                ),
            )
        )
        db.commit()
        ticket = db.query(CustomerServiceTicket).filter_by(ticket_no=ticket_no).one()
        ticket_id = ticket.id
        db.refresh(customer)
        db.expunge(customer)

    with open(os.environ["MODSTORE_RETORT_PROTOCOLS"], encoding="utf-8") as fh:
        templates = json.load(fh)
    templates["restore"]["customer_feedback"] = {
        "domain": "platform",
        "surface": "shared_web",
        "goal": "验证首次导入反馈并恢复正确路径",
    }
    if customer_decision == "resolved_then_reopen":
        from modstore_server import retort_feedback_measurements

        templates["restore"]["customer_feedback"]["growthbook"] = {
            "project": "prod",
            "metric": "first_import",
            "minimum_users": 100,
        }
        monkeypatch.setattr(
            retort_feedback_measurements,
            "experiment_measurement",
            lambda *_, **__: {"status": "running"},
        )
    with open(os.environ["MODSTORE_RETORT_PROTOCOLS"], "w", encoding="utf-8") as fh:
        json.dump(templates, fh)

    def model(messages, **kwargs):
        assert "首次导入未成功" in messages[1]["content"]
        assert "test-private@example.com" not in messages[1]["content"]
        assert ticket_no not in messages[1]["content"]
        return {"ok": True, "content": '{"candidate": 1}'}

    monkeypatch.setattr(service, "reflect", model)
    client, request_id = setup["client"], str(uuid4())
    base = "/api/retort-evolution"
    body = {"request_id": request_id, "template_id": "restore", "source": "customer_feedback"}
    response = client.post(base, json=body)
    assert response.status_code == 200, response.text
    assert client.post(base, json=body).json()["id"] == request_id
    selected = read(client, request_id)
    assert selected["status"] == "awaiting_dispatch_approval"
    assert selected["effects"]["customer_feedback"]["ticket_id"] == ticket_id
    assert selected["effects"]["customer_feedback"]["allocated_worker_slots"] == 1
    assert ticket_no not in selected["snapshot"]["plan"]["public_body"]
    approval_context = selected["snapshot"]["plan"]["private_customer_feedback"]
    assert "首次导入未成功" in approval_context["reproduction"][0]
    assert "test-private@example.com" not in json.dumps(approval_context)

    from modstore_server import retort_customer_feedback as feedback
    from modstore_server.dot_ticket_dispatch import DoltIncidentContractError, _incident_prompt

    with get_session_factory()() as db:
        run = db.get(RetortEvolutionRun, request_id)
        protocol = json_loads(run.protocol_json, {})
        effects = json_loads(run.effects_json, {})
        event = IncidentEvent(
            event_type="ops.retort.evolution",
            source="retort",
            fingerprint=str(uuid4()),
            payload_json="{}",
        )
        db.add(event)
        db.flush()
        run.event_id, run.status = event.id, "waiting_execution"
        effects.update(
            authorization={
                "approved": True,
                "digest": selected["snapshot"]["pending"][0]["digest"],
            },
            plan=selected["snapshot"]["plan"],
            optimization=selected["snapshot"]["optimization"],
            run_id=100,
            issue_number=20,
        )
        run.effects_json = json_dumps(effects)
        payload = {
            "retort_run_id": request_id,
            "user_id": run.user_id,
            "github_workspace": {
                "retort_run_id": request_id,
                "request_id": request_id,
                "repository": protocol["repository"],
                "source_sha": protocol["source_sha"],
                "run_id": 100,
                "issue_number": 20,
            },
        }
        db.flush()
        private = feedback.private_execution_context(db, event.id, payload)
        assert not workspace.authorized_incident(db, payload, event.id)
        run.status = "waiting_credential_isolation"
        assert workspace.authorized_incident(db, payload, event.id, read_only=True)
        effects["plan"]["private_customer_feedback"]["reproduction"] = ["not approved"]
        run.effects_json = json_dumps(effects)
        with pytest.raises(ValueError, match="not_approved"):
            feedback.private_execution_context(db, event.id, payload)
        effects["plan"]["private_customer_feedback"] = private
        run.effects_json = json_dumps(effects)
        with pytest.raises(ValueError, match="not_authorized"):
            feedback.private_execution_context(db, event.id + 1, payload)
        ticket = db.get(CustomerServiceTicket, ticket_id)
        ticket.summary = "选题之后被替换的内容"
        db.flush()
        with pytest.raises(ValueError, match="context_changed"):
            feedback.private_execution_context(db, event.id, payload)
        db.rollback()
    assert private["intent"] == "product_issue"
    assert "首次导入未成功" in private["reproduction"][0]
    assert "test-private@example.com" not in json.dumps(private, ensure_ascii=False)
    assert ticket_no not in json.dumps(private, ensure_ascii=False)
    for tool in ("dolt", "codex", "opencode"):
        for role in ("scout", "fix", "verify", "escalation_review"):
            with pytest.raises(DoltIncidentContractError, match=feedback.CREDENTIAL_BLOCK):
                _incident_prompt(
                    {
                        "role": role,
                        "source": {},
                        "handoffs": [],
                        "review": {},
                        "customer_feedback": private,
                    },
                    {},
                    tool,
                )

    assert (
        client.post(
            f"{base}/{request_id}/decision",
            json={"digest": selected["snapshot"]["pending"][0]["digest"], "approved": True},
        ).status_code
        == 200
    )
    assert read(client, request_id)["status"] == "waiting_credential_isolation"
    for _ in range(2):
        service.tick()
        paused = read(client, request_id)
        assert paused["status"] == "waiting_credential_isolation"
        assert paused["snapshot"]["execution"]["reason"] == feedback.CREDENTIAL_BLOCK
        assert paused["snapshot"]["pending"] == [{"kind": "execution", "request_id": request_id}]
    assert not [call for call in setup["calls"] if call[0] == "POST"]
    status = workspace.worker_status(request_id)
    assert status["kind"] == feedback.REPAIR_KIND and status["finished"] is False
    assert status["conclusion"] == "unknown"

    # Only already-completed historical executions may continue to release readback.
    workspace._save(request_id, run_id=100, issue_number=20)
    monkeypatch.setattr(service.ComponentPorts, "collect", lambda _self, _: {"status": "completed"})
    monkeypatch.setattr(
        service.ComponentPorts,
        "verify",
        lambda _self, _: {"status": "checks_passed", "target_sha": "b" * 40},
    )
    monkeypatch.setattr(
        service.ComponentPorts, "delivery", lambda _self, _: {"status": "waiting_delivery"}
    )

    def approve():
        status = read(client, request_id)
        digest = status["snapshot"]["pending"][0]["digest"]
        result = client.post(
            f"{base}/{request_id}/decision", json={"digest": digest, "approved": True}
        )
        assert result.status_code == 200, result.text

    def resume():
        result = client.post(f"{base}/{request_id}/resume")
        assert result.status_code == 200, result.text
        return read(client, request_id)

    assert resume()["status"] == "awaiting_acceptance"
    approve()
    assert resume()["status"] == "waiting_delivery"
    with get_session_factory()() as db:
        assert db.get(CustomerServiceTicket, ticket_id).status == "open"

    delivery = {
        "status": "deployment_verified",
        "merge_sha": "a" * 40,
        "release_sha": "c" * 40,
        "deployment_run_id": 205,
        "verified_at": datetime.now(UTC).isoformat(),
    }
    monkeypatch.setattr(service.ComponentPorts, "delivery", lambda _self, _: delivery)
    assert resume()["status"] == "delivered"
    assert resume()["status"] == "waiting_customer_impact"
    assert resume()["status"] == "waiting_customer_impact"
    with get_session_factory()() as db:
        assert db.get(CustomerServiceTicket, ticket_id).status == "awaiting_customer"
        assert db.query(CustomerServiceMessage).filter_by(ticket_id=ticket_id).count() == 1

    decision_path = f"/api/customer-service/issues/{ticket_id}/decision"
    decision = {
        "decision": (
            "resolved" if customer_decision.endswith("then_reopen") else customer_decision
        ),
        "note": "已按原业务路径复测成功",
        "idempotency_key": str(uuid4()),
    }
    app.dependency_overrides[get_current_user] = lambda: setup["user"]
    assert client.post(decision_path, json=decision).status_code == 404
    app.dependency_overrides[get_current_user] = lambda: customer
    result = client.post(decision_path, json=decision)
    assert result.status_code == 200, result.text
    if customer_decision.endswith("then_reopen"):
        previous_dispatches = len([call for call in setup["calls"] if call[0] == "POST"])

        def reopen():
            reopened = client.post(
                decision_path,
                json={
                    "decision": "reopen",
                    "note": "原问题再次出现",
                    "idempotency_key": str(uuid4()),
                },
            )
            assert reopened.status_code == 200, reopened.text

        if customer_decision == "completion_race_then_reopen":
            remember = service.ComponentPorts.remember

            def reopen_after_impact_read(port, state):
                result = remember(port, state)
                reopen()
                return result

            with monkeypatch.context() as race:
                race.setattr(service.ComponentPorts, "remember", reopen_after_impact_read)
                assert resume()["status"] == "impact_recheck"
        else:
            assert resume()["status"] == (
                "completed"
                if customer_decision == "completed_then_reopen"
                else "waiting_customer_impact"
            )
            reopen()
        if customer_decision in {"completed_then_reopen", "completion_race_then_reopen"}:
            assert read(client, request_id)["status"] == "impact_recheck"
            assert service.accepted_knowledge() == []
            # Reopen and graph advancement survive independent SQLite sessions;
            # the first tick re-enters the existing impact interrupt.
            service.tick()
            assert read(client, request_id)["status"] == "delivered"
            assert (
                len([call for call in setup["calls"] if call[0] == "POST"]) == previous_dispatches
            )
    if customer_decision == "reopen" or customer_decision.endswith("then_reopen"):
        with get_session_factory()() as db:
            ticket = db.get(CustomerServiceTicket, ticket_id)
            evidence = json_loads(ticket.evidence_json, {})
            evidence["resolution"]["state"] = "processing"
            ticket.evidence_json = json_dumps(evidence)
            db.commit()
    final = resume()
    if customer_decision == "reopen" or customer_decision.endswith("then_reopen"):
        assert final["status"] == "waiting_recovery"
        assert final["snapshot"]["impact"]["release_sha"] == "c" * 40
        assert final["effects"]["recovery"]["reason"] == "recovery_not_authorized"
        assert service.accepted_knowledge() == []
        lessons = service.outcome_knowledge()
        assert lessons[0]["outcome"] == "rejected"
        assert lessons[0]["customer_impact"]["reason"] == "original_customer_reopened"
        assert "ticket_id" not in lessons[0]["customer_impact"]
        if customer_decision in {"completed_then_reopen", "completion_race_then_reopen"}:
            from modstore_server import retort_feedback_recovery

            recoveries = []

            def recovered(recovery_request_id, _state):
                recoveries.append(recovery_request_id)
                return {"status": "rollback_verified", "restored_release_sha": "a" * 40}

            monkeypatch.setattr(retort_feedback_recovery, "recover_release", recovered)
            terminal = resume()
            assert terminal["status"] == "customer_impact_rejected"
            assert terminal["snapshot"]["pending"] == []
            with get_session_factory()() as db:
                updated_at = db.get(RetortEvolutionRun, request_id).updated_at
            recovered_count, dispatches = len(recoveries), list(setup["calls"])
            for _ in range(3):
                assert service.tick()["processed"] == 0
                assert service.advance_run(request_id) == terminal["snapshot"]
            assert len(recoveries) == recovered_count
            assert setup["calls"] == dispatches
            with get_session_factory()() as db:
                assert db.get(RetortEvolutionRun, request_id).updated_at == updated_at
        return
    assert final["status"] == "completed"
    assert final["snapshot"]["impact"]["release_sha"] == "c" * 40
    assert final["snapshot"]["impact"]["status"] == "customer_impact_verified"
    assert final["snapshot"]["impact"]["commercial"]["status"] == "not_configured"


def test_growthbook_requires_same_run_production_exposure_and_valid_sample():
    from modstore_server.retort_feedback_measurements import _snapshot

    sha = "c" * 40
    spec = {"id": "exp_feedback", "project": "prod", "metric": "first_import", "minimum_users": 100}
    delivery = {
        "merge_sha": "a" * 40,
        "release_sha": sha,
        "deployment_completed_at": "2026-01-01T00:00:00Z",
        "verified_at": "2026-01-04T00:00:00Z",
    }
    result = {
        "experiment": {
            "id": spec["id"],
            "project": "prod",
            "type": "standard",
            "status": "stopped",
            "trackingKey": "xcagi-retort-run",
            "tags": [f"xcagi-release-{sha}"],
        },
        "result": {
            "id": "snapshot_feedback",
            "experimentId": spec["id"],
            "dateStart": "2026-01-02T00:00:00Z",
            "dateUpdated": "2026-01-03T00:00:00Z",
            "dimension": {"type": "none"},
            "results": [
                {
                    "totalUsers": 120,
                    "checks": {"srm": 0.9},
                    "metrics": [
                        {
                            "metricId": "first_import",
                            "variations": [
                                {"users": 60},
                                {
                                    "users": 60,
                                    "analyses": [
                                        {"percentChange": 0.12, "ciLow": 0.02, "ciHigh": 0.22}
                                    ],
                                },
                            ],
                        }
                    ],
                }
            ],
        },
    }
    observed = _snapshot(result, spec, "run", delivery)
    assert (
        _snapshot(
            result,
            spec,
            "run",
            {"merge_sha": "a" * 40, "release_sha": sha, "verified_at": "2026-01-01T00:00:00Z"},
        )["status"]
        == "unbound"
    )
    assert observed["status"] == "measured"
    assert observed["decision"] == "promote"
    assert observed["lift"] == 0.12
    assert _snapshot(result, spec, "other-run", delivery)["status"] == "unbound"
    result["result"]["results"][0]["checks"]["srm"] = 0.0001
    assert _snapshot(result, spec, "run", delivery)["status"] == "sample_unverified"


def test_commercial_evidence_uses_successful_job_bound_not_poll_time(monkeypatch):
    from datetime import UTC, datetime

    from modstore_server import customer_value_evidence
    from modstore_server.retort_feedback_measurements import commercial_measurement

    observed = []

    def ledger(**kwargs):
        observed.append(kwargs["delivery_scope"])
        return {
            "value_ledger_ready": True,
            "paid_acceptance_count": 1,
            "verified_paid_amount_cents": 500,
        }

    monkeypatch.setattr(customer_value_evidence, "build_customer_value_evidence", ledger)
    delivery = {
        "identity": {"artifact_sha256": "a" * 64},
        "deployment_completed_at": "2026-01-01T00:00:00Z",
        "verified_at": "2026-01-04T00:00:00Z",
    }
    assert commercial_measurement(17, delivery)["status"] == "verified"
    assert observed == [(17, "a" * 64, datetime(2026, 1, 1, tzinfo=UTC))]
    del delivery["deployment_completed_at"]
    assert commercial_measurement(17, delivery)["status"] == "release_artifact_unavailable"
    assert len(observed) == 1


def test_training_service_submits_frozen_candidate_only_to_original_approval(
    setup, tmp_path, monkeypatch
):
    import base64
    import hashlib
    from pathlib import Path

    from modstore_server import capability_trainer as trainer

    monkeypatch.setenv("XCAGI_LLM_MODEL", "approved-model")
    monkeypatch.setenv("XCAGI_LLM_BASE_URL", "https://platform.test/v1")
    token = "training-service-fixture-" + "t" * 32
    monkeypatch.setenv(
        "MODSTORE_PARA_DISPATCH_TOKEN_SHA256", hashlib.sha256(token.encode()).hexdigest()
    )
    built = trainer.build_config(
        out_dir=tmp_path / "bundle",
        baseline_prompt="baseline",
        candidate_prompt="candidate",
        cases=[{"task": "private reproduction"}],
    )
    bundle = json.loads(Path(built["bundle"]).read_bytes())
    result = {
        "metadata": {"promptfooVersion": trainer.PROMPTFOO_VERSION},
        "results": {
            "prompts": [
                {"raw": Path(built[key]).read_bytes().decode()} for key in ("baseline", "candidate")
            ],
            "results": [
                {
                    "promptIdx": i,
                    "testIdx": 0,
                    "success": bool(i),
                    "failureReason": 0 if i else 1,
                    "gradingResult": {"pass": bool(i)},
                    "error": None if i else "Deterministic assertion failed",
                    "provider": {"id": bundle["provider_id"]},
                    "vars": {"task": "private reproduction", "case_id": bundle["case_ids"][0]},
                }
                for i in (0, 1)
            ],
        },
    }
    templates_path = Path(os.environ["MODSTORE_RETORT_PROTOCOLS"])
    templates = json.loads(templates_path.read_bytes())
    with get_session_factory()() as db:
        other = User(username=uuid4().hex, password_hash="test-only")
        db.add(other)
        db.commit()
        cohort = [setup["user"].id, other.id]
    templates["restore"]["training_candidate"] = {
        "employee_id": "help-desk",
        "owner_id": setup["user"].id,
        "goal": "Improve observed support execution",
        "prompt_path": "catalog/help-desk@1.0.0/prompt.txt",
        "growthbook": {
            "project": "prod",
            "metric": "success",
            "minimum_users": 2,
            "stats_engine": "frequentist",
            "lifecycle": {
                "employee_id": "help-desk",
                "surface": "employee_prompt",
                "cohort_user_ids": cohort,
                "datasource_id": "warehouse",
                "assignment_query_id": "actual-exposures",
                "duration_hours": 24,
                "coverage": 0.1,
            },
        },
    }
    templates_path.write_text(json.dumps(templates))
    sample = {"run_id": "real-failure", "task": "private reproduction"}
    monkeypatch.setattr(
        trainer,
        "mine",
        lambda *_, **__: [{"employee_id": "help-desk", "samples": [sample]}],
    )
    calls = []

    def github(method, path, body=None):
        calls.append((method, path))
        assert method == "GET"
        return (
            {"sha": "a" * 40}
            if path.endswith("/commits/main")
            else {"encoding": "base64", "content": base64.b64encode(b"baseline").decode()}
        )

    monkeypatch.setattr("modstore_server.customer_ticket_github.github", github)
    body = {
        "request_key": "training-fixture-1",
        "employee_id": "help-desk",
        "source_sha": "a" * 40,
        "failure_run_ids": ["real-failure"],
        "workflow_run_id": 77,
        "bundle_json": Path(built["bundle"]).read_bytes().decode(),
        "result_json": json.dumps(result, indent=2) + "\n",
        "files": {
            key: Path(built[key]).read_bytes().decode()
            for key in ("baseline", "candidate", "config", "tests")
        },
    }
    client, endpoint = setup["client"], "/api/service/mac-control/training/candidates"
    auth = {"Authorization": f"Bearer {token}"}
    assert client.post(endpoint, json=body).status_code == 401
    assert (
        client.post(
            endpoint, headers=auth, json={**body, "failure_run_ids": ["invented"]}
        ).status_code
        == 409
    )
    assert (
        client.post(endpoint, headers=auth, json={**body, "source_sha": "b" * 40}).status_code
        == 409
    )
    for wrong_input in (None, "Different easier task"):
        sample["task"] = wrong_input
        invalid = client.post(endpoint, headers=auth, json=body)
        assert invalid.status_code == 409 and "training_reproduction_source_unbound" in invalid.text
    sample["task"] = "private reproduction"
    response = client.post(endpoint, headers=auth, json=body)
    assert response.status_code == 202, response.text
    request_id = response.json()["request_id"]
    assert response.json()["approval_required"] is True
    assert client.post(endpoint, headers=auth, json=body).json()["request_id"] == request_id
    current = read(client, request_id)
    assert current["status"] == "awaiting_dispatch_approval"
    assert current["snapshot"]["has_customer_feedback"] is True
    assert (
        current["snapshot"]["plan"]["feedback_policy"]["growthbook"]["lifecycle"][
            "offline_evidence"
        ]["verdict"]
        == "candidate_for_approval"
    )
    assert "private reproduction" not in current["snapshot"]["plan"]["public_body"]
    private = current["effects"]["training_candidate"]["private_evidence"]
    assert private["result_json"] == body["result_json"]
    assert not [call for call in setup["calls"] if call[0] == "POST"]
    assert (
        client.post(endpoint, headers=auth, json={**body, "workflow_run_id": 78}).status_code == 409
    )
    conflict = client.post(
        endpoint, headers=auth, json={**body, "request_key": "training-fixture-2"}
    )
    assert conflict.status_code == 409 and "surface_already_reserved" in conflict.text
    # Two independent request IDs must not reserve one surface concurrently.
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    with get_session_factory()() as db:
        db.get(RetortEvolutionRun, request_id).status = "cancelled"
        db.commit()
    barrier = Barrier(2)
    request = {
        key: templates["restore"][key] for key in ("criterion_ids", "checks", "container_image")
    }
    request.update(
        title="Training reservation",
        goal="Bounded experiment",
        repository="example/product",
        source_sha="a" * 40,
    )

    def reserve(_index):
        barrier.wait(timeout=5)
        try:
            return service.create_run(
                {**request, "request_id": str(uuid4())},
                setup["user"].id,
                training_candidate=current["effects"]["training_candidate"],
            )
        except (ValueError, TimeoutError):
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(result is not None for result in pool.map(reserve, (0, 1))) == 1
    with get_session_factory()() as db:
        db.get(User, setup["user"].id).account_state = "disabled"
        db.commit()
    unavailable = client.post(endpoint, headers=auth, json=body)
    assert unavailable.status_code == 409 and "training_owner_unavailable" in unavailable.text
    app.dependency_overrides.pop(require_admin)
    denied = client.post(
        f"/api/retort-evolution/{request_id}/decision",
        headers=auth,
        json={"approved": True, "digest": current["snapshot"]["pending"][0]["digest"]},
    )
    assert denied.status_code in {401, 403}
