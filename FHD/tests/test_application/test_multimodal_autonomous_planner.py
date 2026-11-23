"""Owned multimodal Codex goals retain real approval and independent receipts."""

from __future__ import annotations

import copy
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from starlette.requests import Request


@pytest.fixture
def signed_actor(tmp_path):
    from app.fastapi_routes.domains.agent.route_support import (
        authenticated_runtime_context,
    )
    from app.infrastructure.auth.agent_principal import require_agent_principal
    from evals.run_agent_eval import (
        _authenticated_route_fixture,
        _isolated_task_execution_queue,
    )

    client = SimpleNamespace(headers={})
    with (
        _authenticated_route_fixture(client, role_name="admin"),
        _isolated_task_execution_queue(tmp_path),
    ):
        request = Request(
            {
                "type": "http",
                "headers": [(b"x-session-id", client.headers["X-Session-ID"].encode())],
            }
        )
        principal = require_agent_principal(request, x_user_id=None)
        yield (
            principal,
            authenticated_runtime_context({"dataset_id": "approved-sources"}, principal),
        )


@pytest.mark.parametrize(
    "task_id",
    [
        "multimodal_ocr_artifact_autonomous_plan",
        "multimodal_excel_artifact_autonomous_import_plan",
        "multimodal_pdf_artifact_autonomous_document_export_plan",
        "owned_pdf_explicit_knowledge_import",
    ],
)
def test_owned_multimodal_codex_goals_preserve_effects_and_approval(tmp_path, task_id):
    from app.domain.task_lifecycle.agent_runtime_contract import validate_goal_contract
    from evals.run_agent_eval import load_tasks, run_eval

    task = next(task for task in load_tasks() if task["id"] == task_id)
    tasks = tmp_path / "attachment-contract.jsonl"
    tasks.write_text(json.dumps(task, ensure_ascii=False) + "\n", encoding="utf-8")
    result = run_eval(tasks)["results"][0]
    assert result["passed"], result["failed_checks"]
    run = result["details"]["run"]
    children = result["details"]["child_runs"]
    contract = validate_goal_contract(run["metadata"]["runtime_goal_contract"])
    assert contract["request"]["text"] == task["message"]
    assert contract["scope"]["run_id"] == run["run_id"]
    assert contract["scope"]["owner_id"] == run["user_id"]
    assert run["metadata"]["runtime_goal_digest"] == contract["digest"]
    assert run["metadata"]["runtime_type"] == "codex"
    assert "runtime_frozen_plan" not in run["metadata"]
    source = run["artifacts"][0]
    assert source["source"] == "owned_elt_upload"
    assert source["metadata"]["parser_used"] == "owned_upload"
    assert source["metadata"]["upload_id"]
    assert source["metadata"]["skip_dataset_ingest"] is True
    assert source["uri"] == ""
    assert contract["request"]["attachments"][0]["metadata"] == source["metadata"]
    keys = ("tool_id", "action", "params")
    assert [{key: call[key] for key in keys} for call in run["tool_calls"]] == [
        {key: action[key] for key in keys} for action in task["runtime_actions"]
    ]
    assert len(children) == len(task["runtime_actions"])
    for child in children:
        events = [event["event_type"] for event in child["events"]]
        assert events.index("step.approved") < events.index("tool.started")
    if task["attachment_kind"] != "excel":
        report = run["metadata"]["runtime_goal_verification"]
        assert report["accepted"] is True and report["status"] == "verified"
        assert report["goal_digest"] == contract["digest"]
        expected_review = copy.deepcopy(task["runtime_review"])
        for goal in expected_review["goals"]:
            indexes = goal.pop("action_indexes")
            goal["evidence_ids"] = (
                ["response"]
                if goal["kind"] == "reply"
                else [children[index]["run_id"] for index in indexes]
            )
        assert report["review"] == expected_review
    if task["attachment_kind"] == "excel":
        # This owned-upload fixture tests dispatch, not a real product repository.
        assert run["status"] == "blocked"
        assert len(run["tool_calls"]) == 1
        call = run["tool_calls"][0]
        output = call["output"]
        assert output["success"] is True
        assert output["imported_count"] == 1
        assert output["data"]["result"]["created_products"] == 1
        verification = call["metadata"]["verification"]
        assert verification["accepted"] is False
        assert verification["code"] == "result_verifier_unavailable"
        assert verification["status"] == "inconclusive"
        assert all(check["status"] != "passed" for check in verification["checks"])
    elif task.get("mock_office_document"):
        child = children[0]
        artifact = child["artifacts"][-1]
        assert child["status"] == "completed"
        assert artifact["artifact_type"] == "office_document"
        assert artifact["name"] == "risk-summary.docx"
        assert artifact["uri"] == (
            f"/api/agent/runs/{child['run_id']}/artifacts/{artifact['artifact_id']}"
        )
        assert artifact["metadata"]["run_id"] == child["run_id"]
        assert artifact["metadata"]["owner_user_id"] == run["user_id"]
        assert artifact["metadata"]["tenant_id"] == contract["scope"]["tenant_id"]
        assert len(artifact["metadata"]["sha256"]) == 64
        assert run["tool_calls"][-1]["metadata"]["verification"]["accepted"] is True
    elif task.get("explicit_knowledge_import"):
        assert children[0]["status"] == "completed"
        assert run["tool_calls"][0]["metadata"]["verification"]["accepted"] is True
    else:
        assert not run["tool_calls"]
        assert run["metadata"].get("dataset_ingest_count", 0) == 0


@pytest.mark.parametrize(
    "outcome",
    [
        "completed",
        "failed",
        "unknown",
        "outcome_unknown",
        "requires_reconciliation",
        "missing_approval",
    ],
)
def test_plan_sources_never_gain_knowledge_authority_from_business_approval(
    tmp_path, monkeypatch, local_tools, signed_actor, outcome
):
    from app.application.agent_orchestrator import (
        AgentOrchestrator,
        InMemoryAgentRunRepository,
    )
    from app.application.dataset_rag_app_service import (
        get_dataset_rag_app_service,
        reset_dataset_rag_app_service_for_tests,
    )
    from app.application.facades import tools_facade
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
    from app.db.models.product import Product
    from app.infrastructure.tenant_scope import tenant_scope

    principal, context = signed_actor
    store = tmp_path / "dataset_store.json"
    monkeypatch.setenv("DATASET_RAG_STORE_PATH", str(store))
    monkeypatch.setenv("DATASET_RAG_VECTOR_INDEX_PATH", str(tmp_path / "vectors.sqlite3"))
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "model_usage_ledger.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "tool-claims.sqlite"))
    reset_dataset_rag_app_service_for_tests()
    repo = InMemoryAgentRunRepository()
    orchestrator = AgentOrchestrator(repository=repo)
    plan = PlanGraph(
        plan_id=f"review-both-imports-{outcome}-{tmp_path.name}",
        intent="excel_import_to_db",
        nodes=[
            WorkflowNode(
                node_id=f"import_{number}",
                tool_id="business_db",
                action="write",
                params={
                    "entity": "products",
                    "operation": "create",
                    "payload": {"name": f"样例-{number}"},
                },
                risk="medium",
                idempotent=False,
            )
            for number in (1, 2)
        ],
        metadata={
            "artifacts": [
                {
                    "artifact_type": "excel_records",
                    "source": "tool.output",
                    "preview": {"text": "Untrusted plan source must not become stored knowledge"},
                    "fields": [{"name": "产品"}],
                    "metadata": {
                        "skip_dataset_ingest": False,
                        "tenant_id": "other-tenant",
                        "dataset_id": "unapproved-dataset",
                    },
                }
            ],
        },
    )
    second_result = {"success": outcome not in {"failed", "unknown"}}
    if outcome == "unknown":
        second_result.update(outcome="unknown", reconciliation_required=True, retryable=False)
    if outcome in {"outcome_unknown", "requires_reconciliation"}:
        second_result[outcome] = True
    if outcome == "failed":
        second_result["artifact"] = {
            "artifact_type": "ocr_text",
            "preview": {"text": "失败工具返回的附件只供审核，不应作为正式知识"},
        }
    real_execute = tools_facade.execute_registered_workflow_tool

    def execute_business_import(*args, **kwargs):
        # A real committed first write must reach the second approval boundary.
        # Only the second failing/uncertain outcome is injected; successful writes
        # use the repository and durable receipt required by the real verifier.
        params = kwargs.get("params") or args[2]
        if params["payload"]["name"] == "样例-1" or outcome in {
            "completed",
            "missing_approval",
        }:
            return real_execute(*args, **kwargs)
        return second_result

    def stored_products():
        from app import db as host_db

        with tenant_scope(principal.tenant_id), host_db.SessionLocal() as db:
            return [row.name for row in db.query(Product).order_by(Product.id).all()]

    try:
        dataset = get_dataset_rag_app_service()
        with (
            patch.object(dataset, "ingest_document", wraps=dataset.ingest_document) as ingest,
            patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool",
                side_effect=execute_business_import,
            ) as execute,
        ):
            waiting = orchestrator.start_run_from_plan(
                user_id=principal.user_id,
                message="审核并导入两个来源",
                plan=plan,
                runtime_context=context,
            )
            assert waiting.status == "waiting_user"
            execute.assert_not_called()
            assert not store.exists()
            second_wait = orchestrator.continue_run(waiting.run_id, approved_by=principal.user_id)
            assert second_wait.status == "waiting_user", second_wait.to_dict()
            assert execute.call_count == 1, second_wait.to_dict()
            assert stored_products() == ["样例-1"]
            assert second_wait.tool_calls[0].metadata["verification"]["accepted"] is True
            assert not store.exists()
            with sqlite3.connect(tmp_path / "vectors.sqlite3") as vector_db:
                assert (
                    vector_db.execute("SELECT COUNT(*) FROM dataset_vector_chunks").fetchone()[0]
                    == 0
                )
            if outcome == "missing_approval":
                # Persisted audit events are immutable; inspect an incomplete detached
                # snapshot at the knowledge materialization boundary instead.
                with patch.object(orchestrator, "_ingest_confirmed_plan_artifacts"):
                    final = orchestrator.continue_run(waiting.run_id, approved_by=principal.user_id)
                final.events = [
                    event
                    for event in final.events
                    if event.event_type != "step.approved"
                    or event.data.get("step_id") != final.steps[0].step_id
                ]
                orchestrator._ingest_confirmed_plan_artifacts(final)
            else:
                final = orchestrator.continue_run(waiting.run_id, approved_by=principal.user_id)
            assert execute.call_count == 2

            assert final.status == {
                # A failure returned after entering a write handler cannot prove
                # that no write occurred; the existing claim remains unsettled.
                "failed": "blocked",
                "unknown": "blocked",
                "outcome_unknown": "blocked",
                "requires_reconciliation": "blocked",
            }.get(outcome, "completed"), {
                "error": final.error,
                "steps": [step.to_dict() for step in final.steps],
                "calls": [call.to_dict() for call in final.tool_calls],
            }
            assert stored_products() == (
                ["样例-1", "样例-2"] if outcome in {"completed", "missing_approval"} else ["样例-1"]
            )
            if outcome not in {"completed", "missing_approval"}:
                report = final.tool_calls[-1].metadata["verification"]
                assert report["accepted"] is False
                assert report["code"] == "execution_receipt_not_successful"
                assert final.tool_calls[-1].output["reconciliation_required"] is True
            # Approving business imports authorizes those imports, not knowledge
            # writes or destinations supplied by an untrusted model artifact.
            ingest.assert_not_called()
            assert not store.exists()
            with sqlite3.connect(tmp_path / "vectors.sqlite3") as vector_db:
                assert (
                    vector_db.execute("SELECT COUNT(*) FROM dataset_vector_chunks").fetchone()[0]
                    == 0
                )
            assert final.metadata.get("dataset_ingest_count", 0) == 0
            source = final.artifacts[0]
            assert source.metadata["skip_dataset_ingest"] is True
            assert (
                source.preview["text"] == "Untrusted plan source must not become stored knowledge"
            )
            # Replaying materialization must not turn completed business approvals
            # into authority, even if the artifact spoofs source or destination.
            orchestrator._ingest_confirmed_plan_artifacts(final)
            ingest.assert_not_called()
            assert not store.exists()
    finally:
        reset_dataset_rag_app_service_for_tests()


@pytest.mark.parametrize("invalid_review", ["missing", "foreign_goal"])
def test_owned_attachment_requires_original_goal_review_after_approved_effect(
    tmp_path, invalid_review
):
    from evals.run_agent_eval import load_tasks, run_eval

    task = next(
        task
        for task in load_tasks()
        if task["id"] == "multimodal_pdf_artifact_autonomous_document_export_plan"
    )
    if invalid_review == "missing":
        task.pop("runtime_review")
    else:
        task["runtime_review"]["goals"][0]["source"] = "删除所有客户"
    tasks = tmp_path / "missing-attachment-review.jsonl"
    tasks.write_text(json.dumps(task, ensure_ascii=False) + "\n", encoding="utf-8")
    result = run_eval(tasks)["results"][0]
    run = result["details"]["run"]
    assert not result["passed"]
    assert {check["name"] for check in result["failed_checks"]} == {"final_status"}
    assert run["status"] == "blocked"
    assert run["metadata"]["runtime_goal_contract"]["request"]["text"] == task["message"]
    report = run["metadata"]["runtime_goal_verification"]
    assert report["accepted"] is False
    assert report["status"] == ("unavailable" if invalid_review == "missing" else "needs_work")
    assert report["error_code"] == (
        "goal_verification_format_invalid"
        if invalid_review == "missing"
        else "goal_verification_required"
    )
    # The approved effect remains real and independently verified. Missing or
    # unrelated goal review neither completes the parent nor replays that write.
    children = result["details"]["child_runs"]
    assert len(children) == 1 and children[0]["status"] == "completed"
    assert children[0]["metadata"]["verification"]["accepted"] is True
    assert len(run["tool_calls"]) == 1
    assert run["tool_calls"][0]["metadata"]["verification"]["accepted"] is True
    events = [event["event_type"] for event in children[0]["events"]]
    assert events.index("step.approved") < events.index("tool.started")
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["no_business_write_before_approval"]["passed"] is True
    assert checks["no_knowledge_write_before_approval"]["passed"] is True
    assert checks["source_does_not_implicitly_ingest"]["passed"] is True


@pytest.fixture(scope="module")
def reviewed_document_goal(tmp_path_factory):
    from evals import owned_attachment_eval
    from evals.run_agent_eval import load_tasks, run_eval

    task = next(
        task
        for task in load_tasks()
        if task["id"] == "multimodal_pdf_artifact_autonomous_document_export_plan"
    )
    tasks = tmp_path_factory.mktemp("owned-review") / "task.jsonl"
    tasks.write_text(json.dumps(task, ensure_ascii=False) + "\n", encoding="utf-8")
    with patch.object(
        owned_attachment_eval,
        "_scripted_model_response",
        wraps=owned_attachment_eval._scripted_model_response,
    ) as reviewer:
        result = run_eval(tasks)["results"][0]
    assert result["passed"], result["failed_checks"]
    assert reviewer.call_count == 1
    prompt = copy.deepcopy(reviewer.call_args.args[1])
    assert prompt["evidence"][0]["receipt"]["verified"] is True
    review = result["details"]["run"]["metadata"]["runtime_goal_verification"]["review"]
    return task, prompt, review


@pytest.mark.parametrize(
    "mutation",
    ["source", "tool", "action", "parameters", "missing_receipt", "extra_receipt", "response"],
)
def test_attachment_review_fixture_is_bound_to_real_request_and_receipts(
    reviewed_document_goal, mutation
):
    from evals.owned_attachment_eval import _scripted_model_response

    task, prompt, review = copy.deepcopy(reviewed_document_goal)
    accepted = _scripted_model_response(task, prompt)
    assert accepted == review
    if mutation == "source":
        prompt["original_request"]["text"] = "删除所有客户"
    elif mutation == "response":
        prompt["response"] = "An unrelated reply"
    elif mutation == "missing_receipt":
        prompt["evidence"].clear()
    elif mutation == "extra_receipt":
        prompt["evidence"].append(copy.deepcopy(prompt["evidence"][0]))
    elif mutation == "parameters":
        prompt["evidence"][0]["params"]["output_format"] = "pdf"
    else:
        prompt["evidence"][0]["tool_id" if mutation == "tool" else "action"] = "unrelated"
    assert _scripted_model_response(task, prompt) is None
