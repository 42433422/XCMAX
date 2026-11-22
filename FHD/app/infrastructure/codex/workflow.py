"""Frozen host graphs and read-only verification through the existing LangGraph runtime."""

from __future__ import annotations

import copy
from typing import Any

from app.application.agent_orchestrator.param_references import resolve_references
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from app.application.workflow.workflow_types import plan_from_dict, validate_plan_graph
from app.domain.task_lifecycle.agent_runtime_contract import frozen_workflow_operation
from app.domain.task_lifecycle.results import (
    execution_result_envelopes,
    execution_result_error,
    execution_result_outcome_unknown,
)
from app.infrastructure.codex.binding import CodexBindingError, canonical_digest

WORKFLOW_TOOL = "xcmax_workflow"
WORKFLOW_ACTION = "execute"


def frozen_plan(binding: Any, digest: str):
    saved = binding.run.metadata.get("runtime_frozen_plan")
    if not isinstance(saved, dict) or canonical_digest(saved) != digest:
        raise CodexBindingError("goal_mismatch", "工作流不属于宿主冻结目标")
    operation = frozen_workflow_operation(saved)
    if operation not in (binding.run.metadata.get("runtime_expected_operations") or []):
        raise CodexBindingError("goal_mismatch", "工作流缺少原任务冻结义务")
    plan = plan_from_dict(saved)
    if plan is None or validate_plan_graph(plan):
        raise CodexBindingError("goal_changed", "原任务冻结图已失效")
    return plan


def verified_step(step: Any, record: Any) -> bool:
    """A successful step needs its independently persisted matching tool call."""
    return bool(
        step is not None
        and record is not None
        and step.status == record.status == "completed"
        and (record.node_id, record.tool_id, record.action, record.params, record.output)
        == (step.node_id, step.tool_id, step.action, step.params, step.output)
        and step.output.get("success") is True
        and not execution_result_error(step.output)
        and not execution_result_outcome_unknown(step.output)
        and not any(
            isinstance(row.get("status_code"), int) and row["status_code"] >= 400
            for row in execution_result_envelopes(step.output)
        )
    )


def _reference_plan(original: Any, current: Any, child: Any, steps: dict, latest: dict):
    """Apply only original reference selections proven by host amendment records.

    The parent graph stays frozen. Added interaction nodes cannot dispatch a tool;
    their candidates must be reproduced from verified dependency receipts, and
    only the original owner's recorded selection can concretize that reference.
    """
    from app.application.agent_orchestrator.clarification import (
        _ambiguous_field,
        _candidate_rows,
    )
    from app.application.agent_orchestrator.param_references import (
        AmbiguousReference,
        UnresolvedReference,
        _lookup,
        substitute_selected_reference,
    )

    effective = copy.deepcopy(original)
    nodes = {node.node_id: node for node in effective.nodes}
    saved = {node.node_id: node for node in current.nodes}
    extras = set(saved) - set(nodes)
    proofs = child.metadata.get("reference_clarifications", {})
    if not isinstance(proofs, dict) or len(proofs) != len(extras):
        raise CodexBindingError("evidence_mismatch", "新增节点缺少原宿主的引用澄清凭据")
    if any(
        not isinstance(proof, dict) or type(proof.get("sequence")) is not int
        for proof in proofs.values()
    ):
        raise CodexBindingError("evidence_mismatch", "引用澄清凭据无效")
    seen: set[str] = set()
    for index, (step_id, proof) in enumerate(
        sorted(proofs.items(), key=lambda item: item[1]["sequence"])
    ):
        question_id = proof.get("node_id")
        question = steps.get(question_id)
        node = nodes.get(proof.get("target_node_id"))
        params = proof.get("question_params")
        if (
            proof.get("version") != 1
            or proof["sequence"] != index
            or question_id not in extras - seen
            or question is None
            or question.step_id != step_id
            or step_id in latest
            or node is None
            or node.params != proof.get("target_params")
            or not isinstance(params, dict)
            or params.get("target_node_id") != node.node_id
            or params.get("answer_key") != "confirmed"
        ):
            raise CodexBindingError("evidence_mismatch", "引用澄清已偏离原业务节点")
        detail = params.get("clarification")
        if not isinstance(detail, dict) or detail.get("reason") != "ambiguous_target":
            raise CodexBindingError("evidence_mismatch", "只允许原引用的多候选澄清")
        sources = {}
        for source in node.depends_on:
            source_step = steps[source]
            if not verified_step(source_step, latest.get(source_step.step_id)):
                raise CodexBindingError("evidence_mismatch", "澄清候选缺少已核验的前序回执")
            sources[source] = source_step.output
        if proof.get("source_outputs") != {
            source: canonical_digest(output) for source, output in sources.items()
        }:
            raise CodexBindingError("evidence_mismatch", "澄清候选的前序回执已变化")
        spec = get_tool_action_spec(node.tool_id, node.action)
        ambiguities: list[AmbiguousReference] = []
        resolve_references(
            node.params, sources, [], spec.input_schema if spec else None, ambiguities
        )
        if not ambiguities or ambiguities[0].path != detail.get("reference"):
            raise CodexBindingError("evidence_mismatch", "澄清未指向原图的未决引用")
        ambiguity = ambiguities[0]
        destination = _ambiguous_field(node.params, ambiguity.path)
        if (
            not destination
            or detail.get("field_path") != destination
            or detail.get("field") != str(destination[-1])
            or detail.get("node_id") != node.node_id
        ):
            raise CodexBindingError("evidence_mismatch", "澄清不得更换原参数字段")
        try:
            candidates = _candidate_rows(
                ambiguity.rows,
                [
                    _lookup(sources, ambiguity.path, ambiguity.expected_type, selected_row=row)
                    for row in ambiguity.rows[:20]
                ],
            )
        except UnresolvedReference as exc:
            raise CodexBindingError("evidence_mismatch", "澄清候选无法从原回执推导") from exc
        if (
            not candidates
            or detail.get("candidates") != candidates
            or question.output.get("candidates") != candidates
            or question.output.get("target_node_id") != node.node_id
            or question.output.get("question") != params.get("question")
        ):
            raise CodexBindingError("evidence_mismatch", "澄清候选与原前序回执不一致")
        expected_params = copy.deepcopy(params)
        answer = proof.get("answer")
        if answer is None:
            if (
                question.status != "waiting_user"
                or question.output.get("requires_confirmation") is not True
                or child.status == "completed"
            ):
                raise CodexBindingError("evidence_mismatch", "未答复的澄清不能完成")
        else:
            if (
                not isinstance(answer, dict)
                or answer.get("answered_by") != child.user_id
                or not isinstance(answer.get("parameters"), dict)
                or set(answer["parameters"]) != {"id"}
                or question.status != "completed"
                or question.output.get("answer_confirmed") is not True
                or question.output.get("requires_confirmation") is not False
            ):
                raise CodexBindingError("evidence_mismatch", "澄清缺少原用户的确定选择")
            selected = [
                candidate
                for candidate in candidates
                if str(candidate["id"]) == str(answer["parameters"]["id"])
            ]
            if len(selected) != 1:
                raise CodexBindingError("evidence_mismatch", "选择不属于原澄清候选")
            parent: Any = node.params
            for key in destination[:-1]:
                parent = parent[key]
            parent[destination[-1]] = substitute_selected_reference(
                parent[destination[-1]], ambiguity.path, selected[0]["source_value"]
            )
            if node.params != answer.get("result_params"):
                raise CodexBindingError("evidence_mismatch", "答复改动超出原引用的唯一选择")
            expected_params.update(target_node_id="", clarification={})
        actual = saved[question_id]
        if (
            (actual.tool_id, actual.action, actual.depends_on, actual.next, actual.branches)
            != ("clarify", "ask", [], None, [])
            or (question.tool_id, question.action, question.depends_on) != ("clarify", "ask", [])
            or actual.params != expected_params
            or question.params != expected_params
        ):
            raise CodexBindingError("evidence_mismatch", "澄清节点不得改变业务图的执行路径")
        seen.add(question_id)
    return effective


def validate_workflow_receipt(binding: Any, call: dict[str, Any], child: Any) -> bool:
    """Verify identities, resolved parameters, conditional coverage and actual calls.

    A second LangGraph run dispatches *only stored receipts*. It cannot invoke a
    business tool, so missing evidence or an incorrectly skipped branch fails
    without replaying an effect. The same scheduler owns execution and routing
    semantics; this adapter does not invent a second graph executor.
    """
    from app.infrastructure.workflow.langgraph_runtime import XCAGILangGraphRuntime

    digest = str((call.get("params") or {}).get("plan_digest") or "")
    original = frozen_plan(binding, digest)
    if (
        canonical_digest(frozen_workflow_operation(binding.run.metadata["runtime_frozen_plan"]))
        != call["fingerprint"]
    ):
        raise CodexBindingError("evidence_mismatch", "工作流回执不属于原操作")
    current = plan_from_dict(child.metadata.get("plan"))
    if current is None or current.plan_id != original.plan_id or validate_plan_graph(current):
        raise CodexBindingError("evidence_mismatch", "业务图已偏离原冻结计划")
    nodes = {node.node_id: node for node in original.nodes}
    saved_nodes = {node.node_id: node for node in current.nodes}
    steps = {step.node_id: step for step in child.steps}
    if (
        not set(nodes) <= set(saved_nodes)
        or set(saved_nodes) != set(steps)
        or len(child.steps) != len(steps)
    ):
        raise CodexBindingError("evidence_mismatch", "业务图节点与原义务不一致")
    latest = {record.step_id: record for record in child.tool_calls}
    original = _reference_plan(original, current, child, steps, latest)
    nodes = {node.node_id: node for node in original.nodes}
    outputs = {
        key: copy.deepcopy(step.output) for key, step in steps.items() if step.status == "completed"
    }
    for node_id, node in nodes.items():
        actual, step = saved_nodes[node_id], steps[node_id]
        if (
            (actual.tool_id, actual.action, actual.depends_on, actual.next, actual.branches)
            != (node.tool_id, node.action, node.depends_on, node.next, node.branches)
            or (step.tool_id, step.action, step.depends_on)
            != (node.tool_id, node.action, node.depends_on)
            or actual.params != step.params
        ):
            raise CodexBindingError("evidence_mismatch", "业务图动作或顺序已变化")
        spec = get_tool_action_spec(node.tool_id, node.action)
        problems: list[str] = []
        concrete = resolve_references(
            node.params,
            {key: outputs[key] for key in node.depends_on if key in outputs},
            problems,
            spec.input_schema if spec else None,
        )
        if step.params != node.params and (problems or step.params != concrete):
            raise CodexBindingError("evidence_mismatch", "业务参数不能由原图及前序回执推导")
        if step.status == "completed" and (problems or step.params != concrete):
            raise CodexBindingError("evidence_mismatch", "已执行参数缺少确定的前序回执")
    if child.status != "completed":
        return False

    reached: set[str] = set()

    def receipt(tool_id: str, action: str, params: dict[str, Any]) -> dict[str, Any]:
        state = params.get("_runtime_context") or {}
        node_id = str(state.get("_langgraph_node_id") or "")
        step = steps.get(node_id)
        record = latest.get(step.step_id) if step is not None else None
        if (
            step is None
            or not verified_step(step, record)
            or (step.tool_id, step.action) != (tool_id, action)
        ):
            return {"success": False, "retryable": False, "error_code": "receipt_missing"}
        reached.add(node_id)
        return copy.deepcopy(step.output)

    replay = XCAGILangGraphRuntime(tool_dispatcher=receipt).run(
        original,
        max_retries=0,
        parallel=False,
        runtime_context={"source": "codex_receipt_verification"},
    )
    completed = {key for key in nodes if steps[key].status == "completed"}
    skipped = {key for key in nodes if steps[key].status == "skipped"}
    return (
        replay.success
        and reached == completed
        and reached | skipped == set(nodes)
        and set(replay.final_context.get("blocked") or []) == skipped
    )
