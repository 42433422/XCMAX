"""A mode change stops new business writes while retaining completed call receipts."""

from __future__ import annotations

import json

import pytest

from modstore_server import workflow_nl_apply, workflow_nl_graph, xiaoc_life_store
from modstore_server.xiaoc_life_chat import manual_life_scope
from modstore_server.xiaoc_life_policy import LifePolicyError
from tests.test_workflow_nl_graph_skill_generation import (
    _bootstrap,
    _seed_user_workflow,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("is_admin", [True, False])
@pytest.mark.parametrize("downgrade_at", ["model_return", "before_commit"])
async def test_workflow_generation_rechecks_downgrade_before_business_writes(
    tmp_path, monkeypatch, is_admin, downgrade_at
):
    models = _bootstrap(tmp_path, monkeypatch)
    state = {"level": 3}
    monkeypatch.setattr(xiaoc_life_store, "read_state", lambda: dict(state))
    monkeypatch.setattr(workflow_nl_graph, "_catalog_lines", lambda *_: "")
    monkeypatch.setattr(workflow_nl_graph, "_eskill_catalog_lines", lambda *_: "")
    monkeypatch.setattr(
        "modstore_server.mod_scaffold_runner.resolve_llm_provider_model",
        lambda *_: ("test", "test-model", None),
    )
    payload = {
        "skill_blueprints": [
            {
                "temp_skill_id": "format",
                "name": "Generated after model call",
                "domain": "formatting",
                "static_logic": {
                    "type": "template_transform",
                    "template": "Value: ${value}",
                    "output_var": "formatted",
                },
            }
        ],
        "workflow": {
            "nodes": [
                {"temp_id": "start", "node_type": "start", "config": {}},
                {
                    "temp_id": "format",
                    "node_type": "eskill",
                    "config": {"temp_skill_id": "format"},
                },
                {"temp_id": "end", "node_type": "end", "config": {}},
            ],
            "edges": [
                {"source_temp_id": "start", "target_temp_id": "format"},
                {"source_temp_id": "format", "target_temp_id": "end"},
            ],
        },
    }
    calls = []

    async def completed_model_call(*args, **kwargs):
        calls.append("completed")
        if downgrade_at == "model_return":
            state["level"] = 1
        return {"ok": True, "content": json.dumps(payload), "usage": {"total_tokens": 12}}

    monkeypatch.setattr(workflow_nl_graph, "chat_dispatch_via_session", completed_model_call)
    validate = workflow_nl_apply._validate_uncommitted_graph

    def validate_then_downgrade(*args):
        report = validate(*args)
        if downgrade_at == "before_commit":
            state["level"] = 1
        return report

    monkeypatch.setattr(workflow_nl_apply, "_validate_uncommitted_graph", validate_then_downgrade)
    factory = models.get_session_factory()
    with factory() as session:
        user, workflow = _seed_user_workflow(session, models)
        user.is_admin = is_admin
        session.commit()
        workflow_id, user_id = workflow.id, user.id
        with manual_life_scope(user, 3):
            try:
                result = await workflow_nl_graph.apply_nl_workflow_graph(
                    session,
                    user,
                    workflow_id=workflow_id,
                    brief="Create a formatting workflow",
                    provider="test",
                    model="test-model",
                )
            except LifePolicyError:
                result = {"ok": False}

    # A fresh session observes committed business state, not pending ORM objects.
    with factory() as session:
        counts = (
            session.query(models.WorkflowNode).filter_by(workflow_id=workflow_id).count(),
            session.query(models.WorkflowEdge).filter_by(workflow_id=workflow_id).count(),
            session.query(models.ESkill).filter_by(user_id=user_id).count(),
            session.query(models.ESkillVersion).count(),
        )
    assert calls == ["completed"]  # Revocation must not replay the paid model call.
    assert result["ok"] is (not is_admin)
    assert counts == ((0, 0, 0, 0) if is_admin else (3, 2, 1, 1))


@pytest.mark.parametrize(
    "downgrade_at", ["model_return", "first_handler_return", "unknown_handler_return"]
)
def test_employee_revocation_retains_actual_outputs_and_completed_model_usage(
    tmp_path, monkeypatch, downgrade_at
):
    from modstore_server import employee_executor as facade
    from modstore_server import employee_executor_merged_mod2 as executor

    models = _bootstrap(tmp_path, monkeypatch)
    state = {"level": 3}
    monkeypatch.setattr(xiaoc_life_store, "read_state", lambda: dict(state))
    factory = models.get_session_factory()
    monkeypatch.setattr(facade, "get_session_factory", lambda: factory)
    monkeypatch.setattr(facade, "_get_executor_semaphore", lambda: None)
    monkeypatch.setattr(
        facade, "load_employee_pack_resolved", lambda *_a, **_k: {"pack_id": "test", "version": "1"}
    )
    model_calls, native_receipts = [], []

    def completed_model_phase(execution):
        model_calls.append("completed")
        execution.update(
            manifest={},
            config={"actions": {"handlers": ["direct_python", "direct_python"]}},
            handler_list=["direct_python", "direct_python"],
            reasoning={
                "reasoning": "{}",
                "input": {"suppress_employee_im": True},
                "llm_raw": {"usage": {"total_tokens": 17}},
            },
            perceived={},
            memory={},
            direct_only=False,
            runtime_policy={},
            _project_root="",
        )
        if downgrade_at == "model_return":
            state["level"] = 1
        return False, None

    def actual_direct_action(*_args):
        artifact = tmp_path / f"actual-{len(native_receipts)}.txt"
        artifact.write_text("the original action finished", encoding="utf-8")
        receipt = (
            {"handler": "direct_python", "status": "unknown", "requires_reconciliation": True}
            if downgrade_at == "unknown_handler_return"
            else {"handler": "direct_python", "ok": True, "output": str(artifact)}
        )
        native_receipts.append(receipt)
        state["level"] = 1
        return receipt

    monkeypatch.setattr(executor, "_execute_employee_phase_01", completed_model_phase)
    monkeypatch.setattr(facade, "_action_direct_python", actual_direct_action)
    monkeypatch.setattr(
        "modstore_server.employee_verification.run_verification",
        lambda *_a, **_k: pytest.fail("revoked work must not start verification tools"),
    )
    with factory() as session:
        owner = models.User(username="receipt-owner", password_hash="x", is_admin=True)
        session.add(owner)
        session.commit()
        owner_id = owner.id
        with manual_life_scope(owner, 3):
            try:
                result = facade.execute_employee_task(
                    "test",
                    "two original actions",
                    {"suppress_employee_im": True, "suppress_lifecycle_events": True},
                    user_id=owner_id,
                )
            except LifePolicyError:
                result = {}
    assert model_calls == ["completed"]
    assert len(native_receipts) == (0 if downgrade_at == "model_return" else 1)
    assert result.get("llm_tokens") == 17
    assert result["handler_failed"] is True
    receipt = result["result"]
    assert receipt["status"] == "blocked" and receipt["error"]
    assert receipt["outputs"][:-1] == native_receipts
    assert receipt["outputs"][-1]["executed"] is False
    if downgrade_at == "unknown_handler_return":
        from modstore_server.strategic_execution_receipts import evaluate_execution_receipt

        assert receipt["requires_reconciliation"] is True
        assert evaluate_execution_receipt(result).status == "unknown"
    with factory() as session:
        metric = session.query(models.EmployeeExecutionMetric).filter_by(user_id=owner_id).one()
        assert metric.status == (
            "outcome_unknown"
            if downgrade_at == "unknown_handler_return"
            else "blocked_by_life_policy"
        )
        assert metric.llm_tokens == 17
