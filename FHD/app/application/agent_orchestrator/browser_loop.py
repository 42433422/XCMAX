"""Append observed browser actions to the original AgentRun and LangGraph plan.

This adapter never calls an execution tool: every new node returns through the
ordinary permission, approval, billing, lease and checkpoint boundaries.
"""

from __future__ import annotations

import copy
import re
import time
from typing import Any

from app.application.agent_orchestrator.browser_loop_model import request_browser_decision
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.run_usage import RunUsageLedger
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec, validate_tool_call
from app.application.tools.mcp.browser_policy import (
    BROWSER_ACTIONS,
    MAX_BROWSER_DECISIONS,
    MAX_BROWSER_SECONDS,
    MAX_BROWSER_STEPS,
    browser_action_allowed,
    browser_execution_contract,
)
from app.application.tools.mcp.registry import browser_server_config
from app.application.workflow.workflow_types import (
    PlanGraph,
    WorkflowNode,
    plan_from_dict,
    plan_to_dict,
    validate_plan_graph,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

_OBSERVATIONS = frozenset({"browser_snapshot", "browser_wait_for", "browser_take_screenshot"})


def initialize_browser_run(run: AgentRun, plan: PlanGraph) -> str:
    """Only a locally configured browser server can opt a plan into this adapter."""
    configured = [
        node
        for node in plan.nodes
        if node.tool_id.startswith("mcp__") and browser_server_config(node.tool_id)
    ]
    if not configured:
        return ""
    if browser_execution_contract(plan) is None:
        return "浏览器任务须从一个 HTTP(S) 导航或内联快照节点开始，禁止预先猜测后续动作或传入本地文件路径"
    run.metadata["browser_loop"] = {
        "tool_id": configured[0].tool_id,
        "goal": run.message,
        "deadline_at": time.time() + MAX_BROWSER_SECONDS,
        "decisions": 0,
        "phase": "execute",
        "mutated": configured[0].action == "browser_navigate",
        "before_mutation": "",
    }
    return ""


def browser_round_ready(run: AgentRun) -> bool:
    return bool(
        isinstance(run.metadata.get("browser_loop"), dict)
        and run.status == "running"
        and run.steps
        and run.steps[-1].status == "pending"
    )


def browser_round_expired(run: AgentRun) -> bool:
    state = run.metadata.get("browser_loop")
    if isinstance(state, dict) and time.time() >= float(state.get("deadline_at", 0)):
        return _block(run, "browser_deadline_exceeded", "浏览器任务已到原始期限，未执行新动作")
    return False


def _block(run: AgentRun, code: str, message: str) -> bool:
    run.status, run.error = "blocked", code
    run.metadata["browser_loop"]["phase"] = "blocked"
    run.final_output = {
        "message": message,
        "error_code": code,
        "node_outputs": {step.node_id: step.output for step in run.steps},
    }
    run.add_event("browser.blocked", message, {"error_code": code})
    return True


def _append(run: AgentRun, action: str, params: dict[str, Any], *, question: bool = False) -> str:
    state = run.metadata["browser_loop"]
    plan = plan_from_dict(run.metadata.get("plan"))
    if plan is None or len(run.steps) >= MAX_BROWSER_STEPS:
        raise ValueError("browser_step_limit")
    tool_id = "clarify" if question else str(state["tool_id"])
    spec = get_tool_action_spec(tool_id, action)
    if not question:
        if action not in BROWSER_ACTIONS or spec is None:
            raise ValueError("browser_action_not_allowed")
        if not browser_action_allowed(action, params):
            raise ValueError("browser_parameters_not_allowed")
        validation = validate_tool_call(tool_id, action, params)
        if not validation.ok:
            raise ValueError("browser_action_schema_invalid")
    node_id = f"browser_step_{len(run.steps) + 1:03d}"
    node = WorkflowNode(
        node_id=node_id,
        tool_id=tool_id,
        action=action,
        params=copy.deepcopy(params),
        risk=spec.risk if spec else "low",
        idempotent=spec.idempotent if spec else True,
        depends_on=[run.steps[-1].node_id],
        description=str(params.get("question") or action),
    )
    plan.nodes.append(node)
    if validate_plan_graph(plan):
        raise ValueError("browser_graph_invalid")
    run.steps.append(
        AgentStep(
            node_id=node.node_id,
            tool_id=node.tool_id,
            action=node.action,
            params=copy.deepcopy(node.params),
            risk=node.risk,
            idempotent=node.idempotent,
            depends_on=list(node.depends_on),
            description=node.description,
        )
    )
    run.metadata["plan"] = plan_to_dict(plan)
    run.status, run.error = "running", ""
    run.add_event(
        "browser.node_appended",
        "根据实际页面向原任务追加一个待审核步骤",
        {"node_id": node_id, "tool_id": tool_id, "action": action},
    )
    return node_id


def _handoff(run: AgentRun, question: str) -> bool:
    _append(run, "ask", {"question": question}, question=True)
    run.metadata["browser_loop"]["phase"] = "handoff"
    return True


def _snapshot_text(output: dict[str, Any]) -> str:
    """Use only the actual accessibility snapshot, never echoed code/URL/messages."""
    content = str(output.get("content") or "")
    match = re.search(r"### Snapshot\s*\n```(?:yaml)?\s*\n(.*?)\n```", content, re.S)
    return match.group(1) if match else ""


def _targets_observed(params: dict[str, Any], snapshot: str) -> bool:
    targets = [params["target"]] if "target" in params else []
    if isinstance(params.get("fields"), list):
        targets.extend(
            field["target"]
            for field in params["fields"]
            if isinstance(field, dict) and "target" in field
        )
    if not targets:
        return True
    # Refs are node metadata, not quoted labels or text values after a YAML colon.
    prefixes = [
        re.sub(r'"(?:\\.|[^"\\])*"', "", line).split(":", 1)[0] for line in snapshot.splitlines()
    ]
    refs = set(re.findall(r"\[ref=([A-Za-z0-9_]+)\]", "\n".join(prefixes)))
    return all(isinstance(target, str) and target in refs for target in targets)


def _actions(run: AgentRun) -> list[dict[str, Any]]:
    result = []
    for action in sorted(BROWSER_ACTIONS):
        spec = get_tool_action_spec(str(run.metadata["browser_loop"]["tool_id"]), action)
        if spec is not None:
            result.append(
                {
                    "action": action,
                    "description": spec.description,
                    "input_schema": spec.input_schema,
                }
            )
    return result


def advance_browser_run(run: AgentRun, context: dict[str, Any], usage: RunUsageLedger) -> bool:
    """True suspends normal terminal handling; False permits verified completion."""
    state = run.metadata.get("browser_loop")
    if not isinstance(state, dict):
        return False
    if time.time() >= float(state.get("deadline_at", 0)):
        return _block(run, "browser_deadline_exceeded", "浏览器任务已到原始期限，请核对现有回执")
    if len(run.steps) >= MAX_BROWSER_STEPS:
        return _block(run, "browser_step_limit", "浏览器任务已到步骤上限，请核对现有回执")
    if browser_server_config(str(state.get("tool_id") or "")) is None:
        return _block(run, "browser_unavailable", "原浏览器服务已停用，不能继续旧任务")
    last = run.steps[-1]
    if last.status != "completed":
        return _block(run, "browser_receipt_missing", "浏览器步骤缺少真实完成回执")
    try:
        if last.tool_id == "clarify":
            _append(run, "browser_snapshot", {})
            state["phase"] = "observe"
            return True
        generation = last.output.get("session_id")
        if (
            last.output.get("success") is not True
            or not isinstance(generation, str)
            or not generation
            or state.get("session_id") not in {None, generation}
        ):
            return _block(
                run,
                "browser_session_mismatch",
                "浏览器会话回执不一致，不能重放旧页面动作",
            )
        state["session_id"] = generation
        if last.action != "browser_snapshot":
            _append(run, "browser_snapshot", {})
            state["phase"] = "observe"
            return True
        snapshot = _snapshot_text(last.output)
        if not snapshot:
            return _handoff(run, "页面没有可用的可访问性快照，请检查登录或页面状态后继续。")
        verification = state.get("verification")
        if isinstance(verification, dict) and not verification.get("snapshot_node_id"):
            verify = next(
                (step for step in run.steps if step.node_id == verification.get("node_id")),
                None,
            )
            if (
                verify is None
                or verify.action != "browser_wait_for"
                or verify.output.get("success") is not True
                or verify.output.get("session_id") != generation
                or last.depends_on != [verify.node_id]
                or str(verification.get("text") or "") not in snapshot
            ):
                state.pop("verification", None)
                return _handoff(run, "等待条件后页面仍未读回指定结果，请核对页面后继续。")
            verification.update(snapshot_node_id=last.node_id, session_id=generation)
            run.add_event(
                "browser.text_verified",
                "指定页面文本已通过实际等待和新快照验证",
                {"goal": run.message, **verification},
            )
        if int(state.get("decisions", 0)) >= MAX_BROWSER_DECISIONS:
            return _block(run, "browser_decision_limit", "浏览器模型决策已到上限，请核对现有回执")
        state["decisions"] = int(state.get("decisions", 0)) + 1
        decision = request_browser_decision(
            run,
            context,
            observation={
                "snapshot_node_id": last.node_id,
                "page": snapshot[:24_000],
                "truncated": len(snapshot) > 24_000,
            },
            actions=_actions(run),
            usage=usage,
        )
        if decision is None:
            return _handoff(run, "模型暂不可用，浏览器任务已保留；恢复模型后确认继续。")
        if time.time() >= float(state["deadline_at"]):
            return _block(run, "browser_deadline_exceeded", "浏览器任务已到原始期限，未执行新动作")
        if decision.mode == "wait":
            return _handoff(run, decision.reason)
        if decision.mode == "finish":
            if (
                not isinstance(verification, dict)
                or decision.evidence_node_id != verification.get("node_id")
                or verification.get("snapshot_node_id") != last.node_id
                or verification.get("session_id") != generation
                or not isinstance(verification.get("text"), str)
                or not verification["text"]
                or verification["text"] not in snapshot
            ):
                return _block(
                    run,
                    "browser_finish_unverified",
                    "模型声明完成但没有独立的页面验证回执",
                )
            state["phase"] = "verified"
            state["result"] = {
                "scope": "visible_page_text",
                "message": "页面文本已验证",
                "goal": run.message,
                **verification,
            }
            return False
        if decision.mode == "verify":
            if state.get("mutated") and decision.assertion in str(
                state.get("before_mutation") or ""
            ):
                return _handoff(
                    run,
                    "指定验证文本在操作前已存在，请核对实际结果并提供可区分的结果证据。",
                )
            node_id = _append(run, "browser_wait_for", {"text": decision.assertion})
            state["verification"] = {"text": decision.assertion, "node_id": node_id}
            state["phase"] = "verify"
            return True
        if not _targets_observed(decision.params, snapshot[:24_000]):
            return _block(
                run,
                "browser_target_unobserved",
                "模型选择的目标不在本次可见页面快照中，未执行新动作",
            )
        if decision.action not in _OBSERVATIONS:
            state.update(before_mutation=snapshot[:24_000], mutated=True)
        state.pop("verification", None)
        _append(run, decision.action, decision.params)
        state["phase"] = "execute"
        return True
    except RECOVERABLE_ERRORS as exc:
        code = str(exc) if str(exc).startswith("browser_") else "browser_decision_invalid"
        return _block(run, code, "浏览器决策或参数未通过校验，未执行新动作")
