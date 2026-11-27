"""Bounded, non-executing goal review over host-owned requests and receipts.

Xiaox alone decides the next action. This adapter cannot plan, dispatch tools,
change approvals, or mark a task complete without deterministic receipt checks.
"""

from __future__ import annotations

import copy
import json
import math
import re
import time
from collections.abc import Callable
from contextlib import ExitStack
from typing import TYPE_CHECKING, Any, cast

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from app.application.agent_runtime.goal_verification_task import (
    current_review_inputs as _current_review_inputs,
)
from app.application.agent_runtime.goal_verification_task import (
    restore_review_repair,
    review_repair_checkpoint,
)
from app.application.agent_runtime.instructions import GOAL_REVIEW_RULES as _RULES
from app.domain.task_lifecycle import goal_review_models as review_protocol
from app.domain.task_lifecycle.agent_runtime_contract import (
    GOAL_PROTOCOL,
    REPAIRABLE_GOAL_REVIEW_ERRORS,
    canonical_digest,
    goal_answers,
    goal_evidence_snapshot,
    goal_report_coverage,
    goal_source_catalogue,
    plan_navigation_entries,
    planned_tool_calls,
    review_schema,
    runtime_file_evidence,
    valid_compensation_review,
    validate_goal_review,
    validate_runtime_goal,
)
from app.domain.task_lifecycle.agent_runtime_results import model_unsettled, receipt_state

if TYPE_CHECKING:
    from app.application.agent_runtime.plan_delivery import PlanVerdict


_REFERENCE_PREFIX = re.compile(r"^\[原文消息 #[^\]]*\]\n?")
_LANGUAGE_MENTION = re.compile(
    r"英文|英语|中文|汉语|简体|繁体|日文|日语|韩文|韩语|德文|德语|法文|法语|"
    r"西班牙文|西班牙语|俄文|俄语|葡萄牙语|English|Chinese|Japanese|Korean|German|"
    r"French|Spanish|Russian|Portuguese",
    re.IGNORECASE,
)
_REVISION_CUE = re.compile(
    r"(?:再|更)(?:正式|简洁|详细|礼貌|专业|口语|生动)"
    r"|(?:润色|重写|改写|缩写|扩写|调整|修改|补充|完善)"
    r"(?:一下|一遍)?(?:这封|该|上述|上一版|这个)?(?:邮件|正文|文案|回复|回答|内容|方案|措辞|语气|格式)",
)


def _dominant_script(text: str) -> str:
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if cjk >= 8 and cjk * 4 >= latin:
        return "zh"
    if latin >= 40 and latin * 4 >= cjk:
        return "en"
    return ""


def _established_language(request: dict[str, Any]) -> str:
    if _LANGUAGE_MENTION.search(str(request.get("text") or "")):
        return ""
    for row in reversed(request.get("history") or []):
        if isinstance(row, dict) and row.get("role") == "assistant":
            content = _REFERENCE_PREFIX.sub("", str(row.get("content") or ""))
            if script := _dominant_script(content):
                return script
    return ""


def language_continuity_feedback(request: dict[str, Any], response: str) -> str:
    """Reject a revised deliverable that silently switches its established language."""
    if not _REVISION_CUE.search(str(request.get("text") or "")):
        return ""
    expected = _established_language(request)
    actual = _dominant_script(response)
    if not expected or not actual or expected == actual:
        return ""
    name = "英文" if expected == "en" else "中文"
    return f"上一版成稿使用{name}，本轮未要求更换成稿语言；请沿用{name}重写完整成稿。"


def _finish_report(report: dict[str, Any]) -> dict[str, Any]:
    return {**report, "report_digest": canonical_digest(report)}


def _review_evidence_view(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Send outcome facts once; keep full receipts for host-side verification."""
    view = []
    for row in rows:
        receipt = row["receipt"]
        verification = receipt.get("verification") or {}
        calls = []
        for call in receipt.get("tool_calls") or []:
            item = {
                key: call.get(key) for key in ("tool_id", "action", "status", "output", "error")
            }
            if call.get("params") != row.get("params"):
                item["params"] = call.get("params")
            calls.append(item)
        view.append(
            {
                "evidence_id": row["evidence_id"],
                "tool_id": row["tool_id"],
                "action": row["action"],
                "params": row["params"],
                "read_only": row["read_only"],
                "state": row["state"],
                "receipt": {
                    key: receipt.get(key)
                    for key in (
                        "success",
                        "verified",
                        "status",
                        "message",
                        "pending_approval",
                        "needs_user_input",
                        "reconciliation_required",
                    )
                }
                | {
                    "verification": {
                        "status": verification.get("status"),
                        "accepted": verification.get("accepted"),
                        "steps": [
                            {key: step.get(key) for key in ("status", "accepted", "code", "checks")}
                            for step in verification.get("steps") or []
                        ],
                    },
                    "tool_calls": calls,
                    "artifacts": [
                        {
                            key: artifact.get(key)
                            for key in (
                                "artifact_id",
                                "artifact_type",
                                "name",
                                "uri",
                                "mime_type",
                            )
                        }
                        | {"sha256": (artifact.get("metadata") or {}).get("sha256")}
                        for artifact in receipt.get("artifacts") or []
                    ],
                },
            }
        )
    return view


def _file_citation_catalogue(
    file_evidence: dict[str, dict[str, Any]],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, tuple[str, str]],
]:
    documents = {}
    sources: dict[str, tuple[str, str]] = {}
    for identity, source in file_evidence.items():
        blocks = {}
        for block in review_protocol.verbatim_blocks(source["text"]):
            block_id = f"s{len(sources) + 1}"
            sources[block_id] = (identity, block)
            blocks[block_id] = block
        documents[identity] = {key: value for key, value in source.items() if key != "text"}
        documents[identity]["blocks"] = blocks
    return documents, sources


def _resolve_file_citations(
    review: dict[str, Any],
    sources: dict[str, tuple[str, str]],
    responses: dict[str, str],
) -> None:
    for goal in review["goals"]:
        if "file_citations" in goal:
            for cite in goal["file_citations"]:
                identity, source = sources[cite.pop("source_block_id")]
                cite.update(
                    evidence_id=identity,
                    source_excerpt=source,
                    response_excerpt=responses[cite.pop("response_block_id")],
                )


def _verify_plan_capabilities(
    binding: Any,
    calls: list[dict[str, Any]],
    *,
    require_documented_params: bool = False,
) -> tuple[list[dict[str, str]], str]:
    from app.application.agent_orchestrator.param_references import (
        host_reference_params,
        unresolved_placeholders,
        validate_plan_references,
    )
    from app.application.agent_orchestrator.tool_spec import validate_tool_call
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, validate_plan_graph
    from app.infrastructure.xiaox.binding import XiaoxBindingError
    from app.infrastructure.xiaox.tools import XiaoxToolBridge, action_schema_violation

    if len(calls) > 64:
        return [], "单次方案最多核对 64 项动作，请保留未核对项目"
    nodes = [
        WorkflowNode(
            **{key: call[key] for key in ("node_id", "tool_id", "action", "params", "depends_on")}
        )
        for call in calls
    ]
    if error := validate_plan_graph(
        PlanGraph(binding.run.run_id, binding.run.message, nodes=nodes)
    ):
        return [], error
    proofs: list[dict[str, str]] = []
    for node, call in zip(nodes, calls, strict=True):
        identity = f"{node.tool_id}.{node.action}"
        try:
            params = XiaoxToolBridge.action_parameters(call)
            spec = XiaoxToolBridge.authorized_action_spec(binding, call)
        except XiaoxBindingError as exc:
            return [], f"方案动作 {identity}：{exc}。请按当前账号能力目录和契约修订。"
        if (node.tool_id, node.action) != (spec.tool_id, spec.action):
            return [], f"方案动作 {identity} 与真实契约标识不一致"
        schema = spec.input_schema
        properties = schema.get("properties")
        if (
            require_documented_params
            and isinstance(properties, dict)
            and schema.keys().isdisjoint(
                {
                    "additionalProperties",
                    "patternProperties",
                    "unevaluatedProperties",
                    "allOf",
                    "anyOf",
                    "oneOf",
                    "$ref",
                }
            )
            and params.keys() - properties.keys()
        ):
            return [], f"方案动作 {identity} 包含契约中未登记的参数"
        host_params, _ = host_reference_params(node.tool_id, node.action, params)
        dependencies = set(node.depends_on)
        if error := validate_plan_references(host_params, dependencies):
            return [], f"方案动作 {identity}：{error}"
        validation = validate_tool_call(
            node.tool_id,
            node.action,
            params,
            allow_references_from=dependencies,
            resolved_spec=spec,
        )
        if not validation.ok:
            return [], f"方案动作 {identity}：{validation.message}"
        if not unresolved_placeholders(host_params) and (
            violation := action_schema_violation(spec, params)
        ):
            return [], f"方案动作 {identity} 参数不符合当前契约，字段路径 {violation['path']}"
        if call["approval_required"] != spec.approval_required:
            return [], f"方案动作 {identity} 的审批说明与当前契约不符"
        proofs.append({"call_digest": canonical_digest(call), "schema_digest": spec.schema_digest})
    return proofs, ""


def verify_runtime_goal(
    binding: Any,
    config: Any,
    *,
    rows: list[dict[str, Any]],
    output: str,
    consume_format_retry: Callable[[], bool] | None = None,
    plan_delivery: PlanVerdict | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    replay_response: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Tool-free review; one extra format request requires the original task's budget."""
    from openai import APIError, APITimeoutError, DefaultHttpxClient, OpenAI
    from openai.types.responses import ResponseInputParam

    from app.application.agent_runtime.verification_budget import (
        JOB_HEADER,
        VERIFIER_VERSION,
        active_verification_job_id,
        phase_deadline,
    )
    from app.application.tool_execution_deadline import remaining_invocation_seconds

    validate_runtime_goal(binding.run)
    contract = copy.deepcopy(binding.run.metadata["runtime_goal_contract"])
    answers = goal_answers(binding.run)
    if contract["scope"].get("plan_delivery_version") == 1:
        output = plan_delivery.output if plan_delivery else ""
    snapshot = goal_evidence_snapshot(contract, rows, output, answers)
    report: dict[str, Any] = {
        "protocol": GOAL_PROTOCOL,
        "verifier_version": VERIFIER_VERSION,
        "goal_digest": contract["digest"],
        "evidence_digest": snapshot["digest"],
        "response_digest": canonical_digest(output),
        "status": "unavailable",
        "mode": "business",
        "accepted": False,
        "review": None,
        "feedback": "原任务的完整目标尚未核验，不能报告全部完成。",
        "error_code": "goal_verification_unavailable",
        "attempts": [],
    }
    input_identity = {
        key: report[key] for key in ("goal_digest", "evidence_digest", "response_digest")
    }
    if replay_response is not None and (
        replay_response.get("state") != "response_received"
        or replay_response.get("verifier_version") != VERIFIER_VERSION
        or replay_response.get("input") != input_identity
        or not isinstance(replay_response.get("response"), dict)
        or replay_response.get("response_digest")
        != canonical_digest(replay_response.get("response"))
    ):
        report.update(
            error_code="goal_verification_evidence_changed",
            feedback="原核验响应与当前目标或结果版本不一致，不能复用旧证据。",
        )
        return _finish_report(report)
    try:
        repair_context = restore_review_repair(binding.run, replay_response, input_identity)
    except ValueError:
        report.update(
            error_code="goal_verification_evidence_changed",
            feedback="原核验报告修复前提已变化，不能复用修正结果。",
        )
        return _finish_report(report)
    if repair_context:
        report.update(
            review=repair_context["review"],
            error_code="goal_verification_invalid_gap",
            feedback="\n".join(repair_context["wire"]["errors"]),
        )
    states = {receipt_state(row) for row in rows}
    if model_unsettled(binding.metadata) or states & {
        "unknown",
        "claimed",
        "queued",
        "planning",
        "running",
        "retrying",
        "submitted",
        "accepted",
        "waiting_user",
        "waiting_approval",
        "pending_approval",
        "waiting_auth",
    }:
        report.update(
            error_code="goal_evidence_pending", feedback="原任务仍有执行、审批或计量待核对。"
        )
        return _finish_report(report)
    if snapshot["conflicts"]:
        report.update(
            error_code="goal_evidence_conflict", feedback="原任务的执行回执身份冲突，不能核验完成。"
        )
        return _finish_report(report)
    if repair_context and replay_response is None:
        return _finish_report(report)
    if contract["scope"].get("plan_delivery_version") == 1:
        if not plan_delivery or not plan_delivery.proof:
            unavailable = bool(plan_delivery and plan_delivery.unavailable)
            report.update(
                status="unavailable" if unavailable else "needs_work",
                error_code="plan_delivery_unavailable" if unavailable else "plan_delivery_invalid",
                feedback=(plan_delivery.error or output)
                if plan_delivery
                else "方案缺少可核对的交付。",
            )
            return _finish_report(report)
        report["plan_delivery"] = plan_delivery.proof
    file_evidence = runtime_file_evidence(contract, snapshot)
    stale_files: set[str] = set()
    if file_evidence is not None and (
        recalled := {
            key
            for key, source in file_evidence.items()
            if source["origin"] == "conversation_uploads"
        }
    ):
        from app.application.agent_runtime.conversation_attachments import recalled_attachment_view

        verified = recalled_attachment_view(binding.run, binding.context)
        views = verified if isinstance(verified, list) else [verified] if verified else []
        stale_files = recalled - {view["upload_id"] for view in views}
        file_evidence = {
            key: source for key, source in file_evidence.items() if key not in stale_files
        }
    previous = binding.run.metadata.get("runtime_goal_verification")
    if (
        isinstance(previous, dict)
        and previous.get("verifier_version") == VERIFIER_VERSION
        and previous.get("status") in {"verified", "needs_work"}
    ):
        coverage = goal_report_coverage(contract, rows, output, answers, previous)
        # 旧通过报告只有在当前证据上重新通过才能复用；其余同摘要结果只能沿用作未完成结论。
        if coverage["completed"]:
            if any(
                citation["evidence_id"] in stale_files
                for goal in previous["review"]["goals"]
                for citation in goal.get("file_citations", [])
            ):
                report.update(
                    status="needs_work",
                    error_code="goal_file_source_unavailable",
                    feedback="原附件来源已无法核对，请在本轮重新提供可读取的文件。",
                )
                return _finish_report(report)
            calls = planned_tool_calls(previous["review"])
            if not calls or _verify_plan_capabilities(binding, calls) == (
                previous.get("plan_capabilities"),
                "",
            ):
                return copy.deepcopy(previous)
        if (
            previous.get("status") == "needs_work"
            and contract["scope"].get("requested_deliverable") != "action_plan"
            and previous.get("evidence_digest") == snapshot["digest"]
            and previous.get("response_digest") == canonical_digest(output)
            and previous.get("report_digest")
            == canonical_digest(
                {key: value for key, value in previous.items() if key != "report_digest"}
            )
        ):
            if not valid_compensation_review(
                previous.get("review"),
                contract,
                snapshot,
                output,
                file_evidence=file_evidence,
            ):
                invalid = {
                    key: copy.deepcopy(value)
                    for key, value in previous.items()
                    if key != "report_digest"
                }
                invalid.update(
                    status="unavailable",
                    accepted=False,
                    error_code="goal_verification_invalid_gap",
                )
                return _finish_report(invalid)
            return copy.deepcopy(previous)
    route = binding.metadata.get("runtime_config") or {}
    mimo_reasoning = str(
        route.get("upstream_vendor") or ""
    ).strip().casefold() == "xiaomi" and config.model.casefold().startswith("mimo-")
    started = time.monotonic()
    verification_job = active_verification_job_id(binding.run, binding.metadata)
    if binding.metadata.get("verification_budget") and not verification_job:
        report.update(
            error_code="goal_verification_task_missing",
            feedback="目标核验没有原任务的持久核验授权，不能消耗预留资源。",
        )
        return _finish_report(report)
    persisted_deadline = phase_deadline(binding.run, binding.metadata)
    seconds = min(float(config.turn_timeout_seconds), persisted_deadline - time.time(), 90.0)
    # Verification can outlast a normal tool RPC; the original task still bounds it.
    request_limit = seconds
    capacity = int(config.context_window) - int(config.auto_compact_token_limit or 0)
    if (
        not math.isfinite(persisted_deadline)
        or not math.isfinite(seconds)
        or seconds <= 0
        or not math.isfinite(request_limit)
        or request_limit <= 0
        or capacity <= 0
    ):
        report.update(
            error_code="goal_verification_budget_exhausted",
            feedback="目标核验预算不足，原任务未确认完成。",
        )
        return _finish_report(report)
    deadline = started + seconds
    request_view = {
        key: value for key, value in contract["request"].items() if key != "context_evidence"
    }
    action_catalog: dict[str, list[str]] | None = None
    if contract["scope"].get("requested_deliverable") == "action_plan":
        from app.infrastructure.xiaox.tools import XiaoxToolBridge

        action_catalog = {}
        for spec in XiaoxToolBridge.visible_actions(binding, []):
            action_catalog.setdefault(spec.tool_id, []).append(spec.action)
    documents, source_blocks = _file_citation_catalogue(file_evidence or {})
    response_blocks = (
        {
            f"r{index}": block
            for index, block in enumerate(review_protocol.verbatim_blocks(output), start=1)
        }
        if source_blocks
        else {}
    )
    schema = review_schema(
        contract,
        answers=answers,
        action_catalog=action_catalog,
        file_evidence=file_evidence,
        receipt_ids=tuple(row["evidence_id"] for row in snapshot["evidence"]),
        source_block_ids=tuple(source_blocks),
        response_block_ids=tuple(response_blocks),
    )
    # Source policy belongs to deterministic host validation, not format retry.
    # Keep the full policy in the advertised schema; validate wire citations here.
    wire_schema = copy.deepcopy(schema)
    assessment = wire_schema["$defs"]["GoalAssessment"]
    assessment["properties"]["source_id"].pop("enum")
    assessment["allOf"] = [
        rule for rule in assessment["allOf"] if "source_id" not in rule["if"]["properties"]
    ]
    wire_validator = Draft202012Validator(wire_schema) if file_evidence is not None else None
    payload = {
        "task": "verify_runtime_goal",
        "rules": list(_RULES),
        "original_request": request_view,
        "source_catalogue": goal_source_catalogue(contract, answers),
        "host_constraints": contract["scope"].get("constraints") or {},
        **(
            {"requested_deliverable": contract["scope"]["requested_deliverable"]}
            if "requested_deliverable" in contract["scope"]
            else {}
        ),
        "answers": answers,
        "evidence": _review_evidence_view(snapshot["evidence"]),
        "response": output,
        "output_schema": schema,
    }
    if repair_context:
        payload["review_repair"] = repair_context["wire"]
    if file_evidence is not None:
        payload["file_evidence"] = documents
    if response_blocks:
        payload["response_blocks"] = response_blocks
    if entries := plan_navigation_entries(contract):
        payload["desktop_navigation"] = entries
    if plan_delivery and plan_delivery.proof:
        payload["verified_plan_delivery"] = plan_delivery.proof
        # This branch reviews the system-rendered plan, not whether its steps were executed.
        payload["output_schema"]["$defs"]["GoalAssessment"]["properties"]["status"][
            "description"
        ] = (
            "按已由宿主绑定并渲染的方案覆盖原始要求来判定。方案步骤无需已执行，"
            "实际执行回执不属于本次交付条件。"
        )
    # Reserve output within the qualified route limit; bill every attempt.
    payload_size = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    output_estimate = max(
        # MiMo bills internal reasoning against the same output allowance.
        8192 if mimo_reasoning else 2048,
        1024 + len(contract["request"]["text"]) + 384 * len(snapshot["evidence"]),
        min(32768, math.ceil(payload_size / 8)),
    )
    if capacity < 512:
        report.update(
            error_code="goal_verification_budget_exhausted",
            feedback="模型路由可用输出容量不足以提交核验报告，原任务保持未完成。",
        )
        return _finish_report(report)
    error = ""
    format_failure = False
    repair_review = repair_context["review"] if repair_context else None
    with ExitStack() as clients:
        client = None
        for attempt in range(1 if repair_context else 2):
            remaining = remaining_invocation_seconds(deadline - time.monotonic())
            if not math.isfinite(remaining) or remaining <= 0:
                format_failure = False
                report.update(
                    error_code="goal_verification_timeout",
                    feedback="目标核验已达时限，原任务未确认完成。",
                )
                break
            if attempt and (consume_format_retry is None or not consume_format_retry()):
                break
            if attempt and not _current_review_inputs(binding, contract, snapshot, rows, output):
                report.update(
                    error_code="goal_verification_evidence_changed",
                    feedback="报告修复前原目标或证据已变化，不能再次使用旧输入。",
                )
                return _finish_report(report)
            messages = [
                {"role": "system", "content": "独立核对原始目标及宿主证据；只读，不执行、不授权。"},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False, allow_nan=False),
                },
            ]
            if error:
                messages.append(
                    {
                        "role": "user",
                        "content": "上次核验格式未通过："
                        + error
                        + "。使用紧凑JSON、最短原文source及简短reason，不重复整个回执；保留全部目标和缺口，不得通过省略或合并不同效果缩短报告。若容量不足，在uncovered_sources明确未核对范围并保持未完成。",
                    }
                )
            diagnostic: dict[str, Any] = {"attempt": attempt + 1}
            output_budget = min(capacity, output_estimate * (attempt + 1))
            diagnostic["max_output_tokens"] = output_budget
            report["attempts"].append(diagnostic)
            try:
                if replay_response is not None:
                    raw = copy.deepcopy(replay_response["response"])
                    replay_response = None
                    diagnostic["replayed_settled_response"] = True
                else:
                    if on_progress is not None:
                        on_progress(
                            {
                                "state": "requesting",
                                "input": input_identity,
                                "verifier_version": VERIFIER_VERSION,
                                "attempt": attempt + 1,
                                "review_repair": repair_context,
                            }
                        )
                    if client is None:
                        client = clients.enter_context(
                            OpenAI(
                                api_key=config.provider_token,
                                base_url=config.provider_url,
                                max_retries=0,
                                timeout=min(request_limit, seconds),
                                http_client=DefaultHttpxClient(
                                    trust_env=False, follow_redirects=False
                                ),
                            )
                        )
                    response = client.responses.create(
                        model=config.model,
                        input=cast(ResponseInputParam, messages),
                        tools=[],
                        store=False,
                        max_output_tokens=output_budget,
                        timeout=min(request_limit, remaining),
                        extra_headers={JOB_HEADER: verification_job} if verification_job else None,
                    )
                    raw = response.model_dump()
            except APIError as exc:
                # The gateway owns unknown billing/transport outcomes. Never
                # turn a lost response into another speculative request.
                diagnostic["state"] = (
                    "request_timeout" if isinstance(exc, APITimeoutError) else "transport_error"
                )
                format_failure = False
                report.update(
                    error_code="goal_verification_transport_error",
                    feedback="目标核验请求未完成，请核对原任务计量状态。",
                )
                break
            if on_progress is not None:
                on_progress(
                    {
                        "state": "response_received",
                        "input": input_identity,
                        "verifier_version": VERIFIER_VERSION,
                        "attempt": attempt + 1,
                        "response": raw,
                        "response_digest": canonical_digest(raw),
                        "review_repair": repair_context,
                    }
                )
            diagnostic.update(response_id=raw.get("id"), response_status=raw.get("status"))
            if not _current_review_inputs(binding, contract, snapshot, rows, output):
                diagnostic["state"] = "evidence_changed"
                report.update(
                    error_code="goal_verification_evidence_changed",
                    feedback="核验期间原目标或证据已变化，不能复用旧报告。",
                )
                return _finish_report(report)
            if remaining_invocation_seconds(deadline - time.monotonic()) <= 0:
                diagnostic["state"] = "expired"
                format_failure = False
                report.update(
                    error_code="goal_verification_timeout",
                    feedback="目标核验已达时限，原任务未确认完成。",
                )
                break
            items = raw.get("output")
            if not isinstance(items, list) or any(
                not isinstance(item, dict)
                or item.get("type") not in {"message", "reasoning"}
                or item.get("status") not in (None, "completed")
                or (
                    item.get("type") == "message"
                    and (
                        not isinstance(item.get("content"), list)
                        or any(
                            not isinstance(part, dict)
                            or part.get("type") != "output_text"
                            or not isinstance(part.get("text"), str)
                            for part in item["content"]
                        )
                    )
                )
                for item in items
            ):
                diagnostic["state"] = "invalid_output"
                format_failure = False
                report.update(
                    error_code="goal_verification_format_invalid",
                    feedback="核验返回拒绝、工具请求或非法内容，原任务未确认完成。",
                )
                break
            if raw.get("status") != "completed":
                diagnostic["state"] = "incomplete"
                format_failure = False
                report.update(
                    error_code=(
                        "goal_verification_budget_exhausted"
                        if raw.get("status") == "incomplete" and output_budget == capacity
                        else "goal_verification_format_invalid"
                    ),
                    feedback="核验输出未完整结束，原任务及全部待核对目标已保留。",
                )
                break
            try:
                output_text = "".join(
                    part["text"]
                    for item in items
                    if item["type"] == "message"
                    for part in item["content"]
                )
                decoded = json.loads(
                    review_protocol.review_json_text(output_text),
                    object_pairs_hook=review_protocol.unique_json_object,
                )
                json.dumps(decoded, allow_nan=False)
                if isinstance(decoded, dict) and isinstance(decoded.get("goals"), list):
                    if len(decoded["goals"]) > 64:
                        diagnostic["state"] = "goal_limit_exceeded"
                        report.update(
                            error_code="goal_verification_goal_limit_exceeded",
                            feedback="原任务超过单次64项目标核验范围；全部原文及回执已保留，不能将部分核验当作全部完成。",
                        )
                        return _finish_report(report)
                decoded = review_protocol.normalize_review_provenance(decoded, contract)
                wire_review = copy.deepcopy(decoded)
                if wire_validator is not None:
                    wire_defects = review_protocol.review_schema_defects(
                        wire_validator.iter_errors(decoded)
                    )
                    if wire_defects:
                        diagnostic["validation_errors"] = wire_defects
                        raise ValueError("Invalid goal review schema")
                    _resolve_file_citations(decoded, source_blocks, response_blocks)
                review, errors = validate_goal_review(
                    decoded, contract, snapshot, output, file_evidence=file_evidence
                )
            except (ValueError, TypeError, ValidationError):
                diagnostic["state"] = "invalid_format"
                error = "JSON或字段格式无效，请严格按output_schema完整输出"
                if format_defects := diagnostic.get("validation_errors"):
                    error += "：" + json.dumps(format_defects, ensure_ascii=False)
                format_failure = True
                continue
            diagnostic["state"] = "reviewed"
            if repair_review is not None and (
                review_protocol.review_judgments(review)
                != review_protocol.review_judgments(repair_review)
                or not review_protocol.preserves_source_bindings(
                    repair_review, review, payload["source_catalogue"]
                )
            ):
                diagnostic["state"] = "repair_changed_judgment"
                report.update(feedback="核验来源修复改变了原判断或遗漏目标，原任务保持未完成。")
                return _finish_report(report)
            if errors:
                _, defects = validate_goal_review(
                    review,
                    contract,
                    snapshot,
                    output,
                    file_evidence=file_evidence,
                    require_completion=False,
                )
                if defects and all(
                    item.startswith(REPAIRABLE_GOAL_REVIEW_ERRORS) for item in defects
                ):
                    diagnostic.update(state="invalid_provenance", validation_errors=defects)
                    report.update(
                        status="unavailable",
                        review=review,
                        error_code="goal_verification_invalid_gap",
                        feedback="\n".join(defects),
                    )
                    repair_review = review
                    payload["review_repair"] = {
                        "review": wire_review,
                        "errors": defects,
                        "allowed_fields": ["goal_id", "source_id", "source"],
                    }
                    repair_context = review_repair_checkpoint(
                        input_identity, review, payload["review_repair"]
                    )
                    error = (
                        "来源或目标标识无效；仅修正review_repair指定字段，所有判断和缺口保持不变"
                    )
                    format_failure = False
                    continue
            if (
                plan_delivery
                and plan_delivery.proof
                and (review["plan_content"] != plan_delivery.proof["kind"])
            ):
                errors.append("方案的能力声明未通过与交付类型一致的核对。")
            calls = planned_tool_calls(review)
            if calls and not errors:
                proofs, plan_error = _verify_plan_capabilities(binding, calls)
                if plan_error:
                    errors.append(plan_error)
                else:
                    report["plan_capabilities"] = proofs
            mode = (
                "business"
                if any(goal["kind"] in {"read", "write"} for goal in review["goals"])
                else "reply"
            )
            continuity = language_continuity_feedback(contract["request"], output)
            if continuity:
                # The host rule is authoritative for a hard language constraint;
                # drop the reviewer's contrary language claims from the retry input.
                review["feedback"] = ""
                review["violations"] = [
                    item
                    for item in review["violations"]
                    if "沿用" not in item and "语言" not in item
                ]
                review["violations"].append(continuity)
            complete = not (errors or review["violations"] or review["uncovered_sources"])
            complete = complete and all(goal["status"] != "unmet" for goal in review["goals"])
            feedback = "\n".join(
                [*errors, *review["violations"], *review["uncovered_sources"], review["feedback"]]
            ).strip()
            report.update(
                status="verified" if complete else "needs_work",
                mode=mode,
                accepted=complete,
                review=review,
                feedback=feedback
                or (
                    "原始目标已逐项核验。"
                    if complete
                    else "原始目标仍有未完成项，请根据已有回执继续。"
                ),
                error_code="" if complete else "goal_verification_required",
            )
            if not complete and not valid_compensation_review(
                review,
                contract,
                snapshot,
                output,
                file_evidence=file_evidence,
            ):
                # Invalid provenance or evidence is a review defect, never an
                # instruction to dispatch an invented "missing" operation.
                report.update(
                    status="unavailable",
                    error_code="goal_verification_invalid_gap",
                )
            return _finish_report(report)
    if format_failure:
        report.update(
            error_code="goal_verification_format_invalid",
            feedback="目标核验格式无效，原任务未确认完成。",
        )
    return _finish_report(report)
