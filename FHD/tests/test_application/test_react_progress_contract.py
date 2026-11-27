"""Original ReAct failure, evidence admission and SQL recovery regressions."""

import asyncio
import copy
import json

import pytest

from app.domain.task_lifecycle.agent_runtime_contract import canonical_digest
from app.domain.task_lifecycle.react_progress import (
    CONTROL_KEY,
    admit_turn,
    ensure_control,
    note_no_progress,
    output_channel,
    receipt_facts,
    review_signature,
)
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.goal_verification_task import review_task as review_task
from tests.fixtures.xiaox_runtime import (
    Bridge,
    Store,
    Transport,
    completed,
    receipt,
)
from tests.fixtures.xiaox_runtime import (
    setup_runtime as setup_runtime,
)


def test_stalled_business_prose_does_not_spend_another_review(setup_runtime):
    invoke, _ = setup_runtime
    store = Store()
    store.review_kind = "write"
    store.review_missing = True
    transport = Transport(store, completed("文件已写好"))
    result = asyncio.run(invoke(store, transport, tool_bridge=Bridge()))
    events = [event.event_type for event in store.run.events]
    assert events.count("runtime.goal.verification.started") == 1
    assert events.count("runtime.recovery.strategy_changed") == 3
    assert len(transport.inputs) == 4
    assert all(schema is None for schema in transport.schemas)
    assert not result["ok"] and result["artifacts"] == []
    assert result["error_code"] == "react_no_progress_exhausted"
    saved = store.run.metadata["xiaox_runtime"][CONTROL_KEY]
    assert saved["no_progress"] == 3 and saved["route_switch_unavailable"]
    assert saved["repair"]["required_channel"] == "host_tools"
    assert saved["repair"]["tasks"][0]["requirement"] == store.run.message


def test_memory_json_is_quarantined_and_native_tools_can_finish_original_goal(setup_runtime):
    invoke, _ = setup_runtime
    store = Store()
    store.review_kind = "read"
    store.review_missing = True

    class Recovering(Transport):
        async def stream_turn(self, text, *, goal_feedback=None, output_schema=None):
            step = len(self.inputs)
            if step == 1:
                self.events = completed(
                    '{"capability":"memory_v2.propose_candidate","params":{"head_fact":"已完成"}}'
                )
            elif step == 2:
                store.rows.append(receipt())
                store.review_missing = False
                self.events = completed("实际查询已回读。")
            async for value in super().stream_turn(
                text, goal_feedback=goal_feedback, output_schema=output_schema
            ):
                yield value

    transport = Recovering(store, completed("查询已完成"))
    result = asyncio.run(invoke(store, transport, tool_bridge=Bridge()))
    events = [event.event_type for event in store.run.events]
    assert events.count("runtime.goal.verification.started") == 2
    assert events.count("runtime.output.quarantined") == 1
    assert result["ok"] and result["output"] == "实际查询已回读。"
    assert "head_fact" not in result["output"]
    candidate = store.run.metadata["xiaox_runtime"][CONTROL_KEY]["quarantined_outputs"][0]
    assert candidate["channel"] == "memory_candidate" and candidate["trusted"] is False


def test_ordinary_json_reply_does_not_require_tools_or_enter_repair(setup_runtime):
    invoke, _ = setup_runtime
    store = Store()
    transport = Transport(store, completed('{"answer":42}'))
    result = asyncio.run(invoke(store, transport, completion_mode="reply"))
    assert result["ok"] and result["output"] == '{"answer":42}'
    assert len(transport.inputs) == 1
    assert not store.run.metadata["xiaox_runtime"][CONTROL_KEY].get("repair")


def test_native_tool_loop_interrupt_changes_strategy_without_resetting_invocation_budget(
    setup_runtime,
):
    invoke, _ = setup_runtime

    class LoopStore(Store):
        def authenticate(self, token, audience="mcp"):
            if (token, audience) == ("mcp-token", "mcp"):
                return self.get(self.run.run_id)
            return super().authenticate(token, audience)

    store = LoopStore()
    store.review_missing = True

    class LoopTransport(Transport):
        async def interrupt(self):
            assert not store.run.metadata["xiaox_runtime"]["revoked"]
            store.log.append("soft-interrupt")

        async def stream_turn(self, text, *, goal_feedback=None, output_schema=None):
            step = len(self.inputs)
            if step == 1:
                store.run.metadata["xiaox_runtime"].update(
                    tool_call_limit={"reason": "tool_loop_detected"}, tool_invocation_count=100
                )
            elif step == 2:
                store.rows.append(receipt())
                store.review_missing = False
            async for value in super().stream_turn(
                text, goal_feedback=goal_feedback, output_schema=output_schema
            ):
                yield value

    result = asyncio.run(invoke(store, LoopTransport(store), tool_bridge=Bridge()))
    assert result["ok"] and store.log.count("soft-interrupt") == 1
    assert store.run.metadata["xiaox_runtime"]["tool_invocation_count"] == 100
    assert "tool_call_limit" not in store.run.metadata["xiaox_runtime"]
    events = [event.event_type for event in store.run.events]
    assert events.count("runtime.goal.verification.started") == 2
    assert events.count("runtime.recovery.strategy_changed") == 1


@pytest.mark.parametrize("internal", [False, True])
def test_sql_verification_admission_rejects_unchanged_business_or_internal_output(
    review_task, internal
):
    from app.application.agent_runtime import goal_verification_task as checkpoint
    from app.infrastructure.xiaox.binding import XiaoxBindingError

    state = review_task

    def finish_without_new_facts(run, metadata):
        control = ensure_control(metadata, 24)
        control["repair"] = {"tasks": [{"evidence": "host_receipt", "completed": False}]}
        control["last_review_signature"] = review_signature(run, [], state.output)
        run.metadata[checkpoint.JOB_KEY]["state"] = "needs_work"

    state.store.update(state.run_id, finish_without_new_facts)
    before = state.store.get(state.run_id)
    output = '{"capability":"memory_v2.propose_candidate"}' if internal else "完成啦，换了一种说法"
    with pytest.raises(XiaoxBindingError, match="内部协议|没有新执行证据"):
        checkpoint.begin_verification(
            state.store, state.run_id, generation=state.generation, rows=[], output=output
        )
    after = state.store.get(state.run_id)
    assert after.run.metadata[checkpoint.JOB_KEY] == before.run.metadata[checkpoint.JOB_KEY]
    assert after.metadata.get("model_requests", {}) == {}


def test_repeated_read_ids_failed_calls_and_memory_do_not_manufacture_progress():
    original = receipt()
    replay = receipt(child_run_id="new-child", child_task_id="new-task")
    replay["call_id"] = "new-call"
    failed = receipt(status="failed", verified=False, success=False)
    memory = receipt()
    memory["tool_id"] = "memory_v2"
    memory["fingerprint"] = canonical_digest(
        {"tool_id": "memory_v2", "action": memory["action"], "params": memory["params"]}
    )
    assert receipt_facts([original]) == receipt_facts([original, replay, failed, memory])
    changed = copy.deepcopy(replay)
    changed["receipt"]["tool_calls"][0]["output"]["row_count"] = 4
    assert len(receipt_facts([original, changed])) == 2


def test_sql_restart_preserves_repair_counters_and_original_budget(trusted_actor):
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.infrastructure.xiaox.binding import XiaoxBindingStore
    from tests.test_application.test_xiaox_binding import make_binding

    actor = trusted_actor()
    store, run, grant = make_binding(actor)

    def checkpoint(current, metadata):
        ensure_control(metadata, 24)
        admit_turn(metadata)
        note_no_progress(current, metadata, [], "memory_candidate")
        admit_turn(metadata)

    store.update(run.run_id, checkpoint, generation=grant.binding.metadata["generation"])
    before = store.get(run.run_id).metadata[CONTROL_KEY]
    store.close(run.run_id, "waiting_user")
    recovered = XiaoxBindingStore(SQLAlchemyAgentRunRepository(session_factory=actor.factory))
    new_grant = recovered.create(run.run_id)
    assert new_grant.binding.metadata[CONTROL_KEY] == before
    assert ensure_control(new_grant.binding.metadata, 1000) == before
    assert before["execution_turns"] == 1 and before["repair_turns"] == 1
    assert before["strategy_switches"] == 1 and before["no_progress"] == 1


def test_business_review_signature_ignores_rewording_but_accepts_new_original_answers():
    store = Store()
    metadata = store.create(store.run.run_id, runtime_config={}).binding.metadata
    ensure_control(metadata, 24)
    metadata[CONTROL_KEY]["repair"] = {"tasks": [{"evidence": "host_receipt", "completed": False}]}
    store.run.metadata["xiaox_runtime"] = metadata
    assert review_signature(store.run, [], "已完成") == review_signature(store.run, [], "全部完成")
    before = review_signature(store.run, [], "已完成")
    store.run.metadata["runtime_goal_digest"] = "changed-by-host"
    assert review_signature(store.run, [], "已完成") != before


@pytest.mark.parametrize(
    "body,channel",
    [
        ('{"capability":"memory_v2.propose_candidate","params":{}}', "memory_candidate"),
        ('{"capability":"sales.create","params":{}}', "action_proposal"),
        ('{"goals":[],"violations":[],"feedback":"done"}', "verification"),
        ('{"revenue":12}', "reply"),
        ('{"capability":"analysis","score":12}', "reply"),
    ],
)
def test_role_protocols_are_disjoint(body, channel):
    assert output_channel(body) == channel


def test_corrupt_saved_budget_is_rejected_instead_of_replenished():
    metadata = {}
    saved = ensure_control(metadata, 24)
    saved["repair_turns"] = 100
    with pytest.raises(ValueError, match="original budget"):
        ensure_control(metadata, 1000)
    assert saved["repair_turns"] == 100 and saved["limits"]["repair"] == 6


def test_review_format_correction_does_not_consume_a_second_assessment():
    from app.application.agent_runtime.verification_budget import verification_reserve

    metadata = {
        "verification_budget": {
            "accounting": "evidence_revision",
            "model_calls": 3,
            "max_model_calls": 3,
            "per_call_cost_units": 5,
        },
        "model_requests": {
            "assessment": {"purpose": "verification", "verification_job_id": "same-evidence"},
            "format-repair": {"purpose": "verification", "verification_job_id": "same-evidence"},
        },
    }
    assert verification_reserve(metadata) == (2, 10)
    metadata["model_requests"]["new-assessment"] = {
        "purpose": "verification",
        "verification_job_id": "new-evidence",
    }
    assert verification_reserve(metadata) == (1, 5)
