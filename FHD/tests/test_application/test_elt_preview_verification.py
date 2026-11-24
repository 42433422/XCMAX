"""Native preview admission binds single, batch and companion source identities."""

import copy

import pytest

from app.application.agent_orchestrator.result_verification import (
    bind_execution_receipt,
    freeze_verification_contract,
    verify_step_result,
)
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_agent_user_decision_pause import native_preview as native_preview


def verify(actor, params, output):
    step = AgentStep(
        "preview", "elt_import", "preview", params=copy.deepcopy(params), attempt_count=1
    )
    call = ToolCall(
        step.step_id,
        step.node_id,
        step.tool_id,
        step.action,
        params=copy.deepcopy(params),
        metadata={"attempt_count": 1},
    )
    run = AgentRun(
        user_id=str(actor.user_id),
        message="review",
        steps=[step],
        tool_calls=[call],
        metadata={"runtime_context": dict(actor.context)},
    )
    context = {
        **actor.context,
        "run_id": run.run_id,
        "step_id": step.step_id,
        "node_id": step.node_id,
    }
    freeze_verification_contract(
        run, step, call, get_tool_action_spec(step.tool_id, step.action), context
    )
    step.output, call.output = copy.deepcopy(output), copy.deepcopy(output)
    call.status = "completed"
    bind_execution_receipt(call)
    return verify_step_result(run=run, step=step, call=call, context=context)


@pytest.mark.parametrize("wrong_run", [False, True])
def test_review_existing_is_bound_to_the_requested_native_run(
    trusted_actor, native_preview, wrong_run
):
    actor = trusted_actor(role="admin")
    receipt = native_preview(actor)
    original_id = receipt["data"]["run_id"]
    if wrong_run:
        receipt = native_preview(actor)
    for key in ("requires_user_decision", "question", "resume_params"):
        receipt.pop(key)
    receipt["data"].pop("executable")
    receipt["data"].update(preview_only=True, requires_user_confirmation=True)
    report = verify(actor, {"run_id": original_id}, receipt)
    assert report["accepted"] is (not wrong_run)
    if not wrong_run:
        assert report["checks"][0]["evidence"]["business_effect_verified"] is False


@pytest.mark.parametrize("change", [None, "missing", "duplicate", "summary", "scope"])
def test_batch_requires_every_original_owned_preview(trusted_actor, native_preview, change):
    actor = trusted_actor(role="admin")
    paths = ["@uploads/first.xlsx", "@uploads/second.xlsx"]
    items = [
        {"file_path": path, **native_preview(actor, file_name=path.rsplit("/", 1)[1])}
        for path in paths
    ]
    output = {
        "success": True,
        "batch": True,
        "run_ids": [],
        "file_count": 2,
        "ready_count": 2,
        "needs_decision_count": 2,
        "deferred_count": 0,
        "truncated": False,
        "requires_user_decision": True,
        "question": "仅继续有效行？",
        "resume_params": {"valid_rows_only": True},
        "data": {
            "run_id": "",
            "run_ids": [],
            "file_count": 2,
            "ready_count": 2,
            "needs_decision_count": 2,
            "executable": False,
        },
        "results": items,
    }
    if change == "missing":
        items.pop()
    elif change == "duplicate":
        items[1] = {**items[0], "file_path": paths[1]}
    elif change == "summary":
        output["data"]["executable"] = True
    elif change == "scope":
        items[1]["file_path"] = "@uploads/unapproved.xlsx"
    assert verify(actor, {"file_paths": paths}, output)["accepted"] is (change is None)


@pytest.mark.parametrize("changed_child", [False, True])
def test_linked_companion_has_its_own_owned_manifest(trusted_actor, native_preview, changed_child):
    from app.application.elt.preview_confirmation import publish_preview
    from app.application.elt.service_history import HistoryServiceMixin
    from app.application.elt.service_support import dump_json
    from app.db.models.elt import EltRun
    from app.domain.shared_services.tools_workflow_elt import _companion_summary, _summary
    from app.infrastructure.tenant_scope import tenant_scope

    actor = trusted_actor(role="admin")
    receipt, linked = native_preview(actor), native_preview(actor)
    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        parent = db.get(EltRun, receipt["data"]["run_id"])
        child = db.get(EltRun, linked["data"]["run_id"])
        parent.target_type, child.target_type = "shipment_records", "customer_products"
        parent.summary_json = dump_json({"linked_customer_products_preview": {"run_id": child.id}})
        child.draft_json = dump_json({"linked_preview": {"parent_run_id": parent.id}})
        publish_preview(db, parent)
        publish_preview(db, child)
        receipt["data"].update(_summary(HistoryServiceMixin().run_dict(parent)))
        receipt["data"]["customer_products"] = _companion_summary(
            HistoryServiceMixin().run_dict(child)
        )
        if changed_child:
            child.owner_user_id = 999999
    assert verify(actor, {"file_path": "@uploads/宗南.xlsx"}, receipt)["accepted"] is (
        not changed_child
    )
