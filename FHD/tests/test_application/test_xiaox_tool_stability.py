"""Original SQL-task limits and observable progress, without external model calls."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.infrastructure.xiaox import binding as binding_module
from app.infrastructure.xiaox.binding import XiaoxBindingError, XiaoxBindingStore
from app.infrastructure.xiaox.tools import XiaoxToolBridge
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_xiaox_binding import make_binding
from tests.test_application.test_xiaox_tools import bridge_setup as bridge_setup
from tests.test_application.test_xiaox_workbook_write import workbook_runtime as workbook_runtime


def test_rejected_mcp_preflights_use_original_sql_budget_and_loop_detector(bridge_setup):
    state = bridge_setup
    for index in range(8):
        result = state.bridge.reject_invalid_arguments(
            state.grant.mcp_token,
            "execute_action",
            {"call_id": str(index), "params": {}},
            [{"path": "$.params", "validator": "required", "missing": ["input"]}],
        )
        assert result["status"] == "not_started" and not result["verified"]
    saved = state.store.get(state.run.run_id)
    assert saved.metadata["tool_invocation_count"] == 8
    assert saved.metadata["tool_call_limit"]["reason"] == "tool_loop_detected"
    assert saved.metadata["calls"] == {}
    with pytest.raises(XiaoxBindingError, match="重复"):
        state.store.authenticate(state.grant.model_token, "model")


def test_schema_feedback_includes_all_matching_variant_defects_without_values():
    import json

    from jsonschema import Draft202012Validator

    from app.infrastructure.xiaox.tool_schemas import schema_violations

    schema = {
        "type": "object",
        "properties": {
            "nodes": {
                "type": "array",
                "items": {
                    "oneOf": [
                        {
                            "properties": {
                                "phase": {"const": "format"},
                                "width": {"type": "integer"},
                            },
                            "required": ["width", "height"],
                        },
                        {"properties": {"phase": {"const": "write"}}, "required": ["cell"]},
                    ]
                },
            }
        },
    }
    data = {"nodes": [{"phase": "format", "width": "PRIVATE"} for _ in range(20)]}
    violations = schema_violations(Draft202012Validator(schema).iter_errors(data))
    assert len(violations) == 16
    assert {item["validator"] for item in violations} == {"type", "required"}
    assert all("cell" not in item.get("missing", []) for item in violations)
    assert "PRIVATE" not in json.dumps(violations)


@pytest.mark.parametrize("period", [1, 2, 4])
def test_repeated_discovery_stops_without_claiming_business_success(
    bridge_setup, monkeypatch, period
):
    state = bridge_setup
    # Catalog discovery has its own SDK/authority suite; isolate its empty result
    # here while retaining the actual authenticated bridge and SQL CAS counter.
    monkeypatch.setattr(
        "app.application.capability_catalog.authorized_tool_specs", lambda *a, **kw: {}
    )
    for index in range(8 * period):
        result = state.bridge.invoke(
            state.grant.mcp_token, "capability_search", {"query": f"missing-tool-{index % period}"}
        )
        assert result["capabilities"] == []
    saved = state.store.get(state.run.run_id)
    assert saved.metadata["tool_call_limit"]["reason"] == "tool_loop_detected"
    assert saved.metadata["tool_call_limit"]["period"] == period
    assert saved.metadata["calls"] == {} and saved.run.status == "running"
    with pytest.raises(XiaoxBindingError) as error:
        state.store.authenticate(state.grant.model_token, "model")
    assert error.value.code == "tool_loop_detected"
    with pytest.raises(XiaoxBindingError) as error:
        state.bridge.invoke(state.grant.mcp_token, "capability_search", {"query": "another"})
    assert error.value.code == "tool_loop_detected"


def test_tool_count_is_atomic_and_survives_restart_and_new_grant(trusted_actor, monkeypatch):
    actor = trusted_actor()
    store, run, grant = make_binding(actor)
    monkeypatch.setattr(binding_module, "_MAX_TOOL_INVOCATIONS", 3)

    def admit(index):
        try:
            store.admit_tool_invocation(
                run.run_id,
                "task_evidence",
                {"call_id": str(index)},
                generation=grant.binding.metadata["generation"],
            )
            return "admitted"
        except XiaoxBindingError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(admit, range(5)))
    assert outcomes.count("admitted") == 3
    assert outcomes.count("tool_call_budget_exhausted") == 2
    store.close(run.run_id, "waiting_user")
    reopened = XiaoxBindingStore(SQLAlchemyAgentRunRepository(session_factory=actor.factory))
    renewed = reopened.create(run.run_id)
    assert renewed.binding.metadata["tool_invocation_count"] == 3
    with pytest.raises(XiaoxBindingError) as error:
        reopened.admit_tool_invocation(
            run.run_id, "capability_describe", {}, generation=renewed.binding.metadata["generation"]
        )
    assert error.value.code == "tool_call_budget_exhausted"
    assert reopened.get(run.run_id).metadata["tool_invocation_count"] == 3


def _observe(store, run, grant, index, *, value=1, status="completed", name="execute_action"):
    arguments = {"tool_id": "customers", "action": "query", "params": {}, "call_id": str(index)}
    result = {
        "task_id": f"task-{index}",
        "run_id": f"child-{index}",
        "child_updated_at": str(index),
        "success": status == "completed",
        "verified": status == "completed",
        "status": status,
        "tool_calls": [
            {
                "call_id": f"fresh-{index}",
                "tool_id": "customers",
                "action": "query",
                "params": {},
                "status": status,
                "output": {"success": True, "data": {"value": value}},
            }
        ],
    }
    store.admit_tool_invocation(
        run.run_id, name, arguments, generation=grant.binding.metadata["generation"]
    )
    store.observe_tool_result(
        run.run_id, name, arguments, result, generation=grant.binding.metadata["generation"]
    )


def test_fresh_read_call_ids_cannot_disguise_repeated_unchanged_results(trusted_actor):
    actor = trusted_actor()
    store, run, grant = make_binding(actor)
    for index in range(7):
        _observe(store, run, grant, index)
    reopened = XiaoxBindingStore(SQLAlchemyAgentRunRepository(session_factory=actor.factory))
    _observe(reopened, run, grant, 7)
    assert reopened.get(run.run_id).metadata["tool_call_limit"]["reason"] == "tool_loop_detected"
    assert not reopened.get(run.run_id).run.metadata.get("non_retryable")


def test_native_and_generic_read_share_original_sql_progress_budget(workbook_runtime):
    state = workbook_runtime
    description = state.bridge.invoke(
        state.grant.mcp_token,
        "capability_describe",
        {"tool_id": "excel_analysis", "action": "read"},
    )["capability"]
    params = {"file_path": state.upload["upload_id"], "header_row": 1}
    bridge = state.bridge
    for index in range(8):
        if index == 4:
            bridge = XiaoxToolBridge(
                XiaoxBindingStore(
                    SQLAlchemyAgentRunRepository(session_factory=state.actor.factory)
                ),
                state.bridge.orchestrator,
            )
        common = {"call_id": f"alias-read-{index}", "schema_digest": description["schema_digest"]}
        name, arguments = (
            ("execute_excel_read", {**common, **params})
            if index % 2 == 0
            else (
                "execute_action",
                {**common, "tool_id": "excel_analysis", "action": "read", "params": params},
            )
        )
        result = bridge.invoke(state.grant.mcp_token, name, arguments)
        assert result["success"] is True and result["verified"] is True, result
        assert result["status"] == "completed"
        child = state.repository.get(result["run_id"])
        assert child.user_id == str(state.actor.user_id)
        assert child.steps[0].tool_id == "excel_analysis" and child.steps[0].action == "read"
        assert child.steps[0].params == params
    saved = bridge.store.get(state.parent.run_id)
    assert saved.metadata["tool_invocation_count"] == 9  # One description, eight actual reads.
    assert saved.metadata["tool_call_limit"]["reason"] == "tool_loop_detected"
    assert saved.metadata["tool_call_limit"]["period"] == 1
    calls = saved.metadata["calls"]
    with pytest.raises(XiaoxBindingError) as error:
        bridge.invoke(
            state.grant.mcp_token,
            "execute_excel_read",
            {**common, **params, "call_id": "ninth-read"},
        )
    assert error.value.code == "tool_loop_detected"
    assert bridge.store.get(state.parent.run_id).metadata["calls"] == calls
    assert bridge.store.get(state.parent.run_id).metadata["tool_invocation_count"] == 9


@pytest.mark.parametrize(
    "name", ["execute_excel_read", "execute_excel_structure", "execute_employee"]
)
def test_native_action_cannot_drop_caller_supplied_authority(bridge_setup, name):
    state = bridge_setup
    with pytest.raises(XiaoxBindingError) as error:
        state.bridge.invoke(
            state.grant.mcp_token, name, {"call_id": "identity-override", "tenant_id": 999}
        )
    assert error.value.code == "identity_override"
    saved = state.store.get(state.run.run_id)
    assert saved.metadata["tool_invocation_count"] == 1
    assert saved.metadata["calls"] == {}
    assert len(state.store.repository.list_recent()) == 1


def test_changing_business_results_do_not_trigger_loop_detection(trusted_actor):
    store, run, grant = make_binding(trusted_actor())
    for index in range(40):
        _observe(store, run, grant, index, value=index)
    saved = store.get(run.run_id)
    assert "tool_call_limit" not in saved.metadata
    assert len(saved.metadata["tool_observation_history"]) <= 32
    assert saved.metadata["tool_invocation_count"] == 40


def test_async_business_progress_breaks_repeated_descriptions_but_polling_is_bounded(trusted_actor):
    store, run, grant = make_binding(trusted_actor())
    for index in range(10):
        store.observe_tool_result(
            run.run_id,
            "capability_describe",
            {"tool_id": "customers", "action": "query"},
            {"success": True, "capability": {"input_schema": {}}},
            generation=grant.binding.metadata["generation"],
        )
        _observe(store, run, grant, index, status="running")
        for _ in range(10):
            _observe(store, run, grant, index, status="running", name="task_evidence")
        _observe(store, run, grant, index, value=index, name="task_evidence")
    saved = store.get(run.run_id)
    assert "tool_call_limit" not in saved.metadata
    assert saved.metadata["tool_invocation_count"] == 120


def test_polling_unchanged_receipt_cannot_reset_a_discovery_loop(trusted_actor):
    store, run, grant = make_binding(trusted_actor())
    _observe(store, run, grant, 0, name="task_evidence")
    for _ in range(8):
        store.observe_tool_result(
            run.run_id,
            "capability_search",
            {"query": "same"},
            {"capabilities": []},
            generation=grant.binding.metadata["generation"],
        )
        _observe(store, run, grant, 0, name="task_evidence")
    assert store.get(run.run_id).metadata["tool_call_limit"]["reason"] == "tool_loop_detected"


def test_cancelled_task_cannot_admit_or_observe_late_results(trusted_actor):
    store, run, grant = make_binding(trusted_actor())
    store.admit_tool_invocation(
        run.run_id, "capability_search", {}, generation=grant.binding.metadata["generation"]
    )
    store.repository.request_task_control(run.run_id, "cancel", requested_by=run.user_id)
    with pytest.raises(XiaoxBindingError) as error:
        store.observe_tool_result(
            run.run_id,
            "capability_search",
            {},
            {"capabilities": []},
            generation=grant.binding.metadata["generation"],
        )
    assert error.value.code == "cancelled"
    with pytest.raises(XiaoxBindingError) as error:
        _observe(store, run, grant, 0)
    assert error.value.code == "cancelled"
    assert store.get(run.run_id).metadata["tool_invocation_count"] == 1
    assert "tool_observation_history" not in store.get(run.run_id).metadata
