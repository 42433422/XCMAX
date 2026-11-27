"""Immutable original goals, host scope and independent result evidence."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError

from app.domain.task_lifecycle.goal_review_models import (
    FileCitation as FileCitation,
)
from app.domain.task_lifecycle.goal_review_models import (
    GoalAssessment as GoalAssessment,
)
from app.domain.task_lifecycle.goal_review_models import (
    GoalReview as GoalReview,
)
from app.domain.task_lifecycle.goal_review_models import (
    PlannedNavigation as PlannedNavigation,
)
from app.domain.task_lifecycle.goal_review_models import (
    PlannedToolCall as PlannedToolCall,
)
from app.domain.task_lifecycle.goal_review_models import (
    PlanToolAction as PlanToolAction,
)
from app.domain.task_lifecycle.goal_review_models import (
    goal_source_catalogue as goal_source_catalogue,
)
from app.domain.task_lifecycle.results import (
    execution_result_error,
    execution_result_outcome_unknown,
)


class AgentRuntimeContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


GOAL_PROTOCOL = "xcmax.agent-goal.v2"
REPAIRABLE_GOAL_REVIEW_ERRORS = (
    "goal_id_duplicate:",
    "goal_source_unknown:",
    "goal_source_mismatch:",
)
_SCOPE_FIELDS = (
    "user_id",
    "actor_id",
    "tenant_id",
    "mod_id",
    "active_mod_id",
    "employee_id",
    "session_id",
    "conversation_id",
    "workspace_id",
    "parent_run_id",
    "parent_task_id",
    "root_run_id",
    "employee_tool_allowlist",
    "_employee_gate_contract",
)


def goal_scope(run: Any) -> dict[str, Any]:
    """Bind host identity and restrictions without copying authentication secrets."""
    context = run.metadata.get("runtime_context") or {}
    return {
        "run_id": run.run_id,
        "owner_id": run.user_id,
        "allowed_actions": copy.deepcopy(run.metadata.get("runtime_allowed_actions")),
        "entity_binding_digest": canonical_digest(context.get("enterprise_cognition")),
        **{key: copy.deepcopy(context.get(key)) for key in _SCOPE_FIELDS},
        "constraints": copy.deepcopy(context.get("_runtime_goal_constraints") or {}),
        **(
            {
                "requested_deliverable": "action_plan",
                **(
                    {"plan_delivery_version": 1}
                    if run.metadata.get("plan_delivery_version") == 1
                    else {}
                ),
            }
            if run.metadata.get("runtime_requested_deliverable") == "action_plan"
            else {}
        ),
    }


def build_goal_contract(
    run: Any,
    *,
    history: list[dict[str, Any]] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    context_evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Persist the user's request; this contract neither plans nor authorizes actions."""
    if not isinstance(run.message, str) or not run.message.strip():
        raise AgentRuntimeContractError("invalid_goal", "原始任务不能为空")
    historical = history if history is not None else run.metadata.get("_xiaox_history")
    request = {
        "text": run.message,
        "input_data": copy.deepcopy(run.metadata.get("_xiaox_input_data")),
        "attachments": copy.deepcopy(attachments or []),
        "context_evidence": copy.deepcopy(context_evidence or []),
        "history": [
            {"role": row["role"], "content": row["content"]}
            for row in historical or []
            if isinstance(row, dict)
            and row.get("role") in {"user", "assistant", "tool"}
            and isinstance(row.get("content"), str)
        ],
    }
    contract = {"protocol": GOAL_PROTOCOL, "scope": goal_scope(run), "request": request}
    try:
        return {**contract, "digest": canonical_digest(contract)}
    except (TypeError, ValueError) as exc:
        raise AgentRuntimeContractError("invalid_goal", "原始任务数据不能持久化") from exc


def validate_goal_contract(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != {"protocol", "scope", "request", "digest"}
        or value.get("protocol") != GOAL_PROTOCOL
        or not isinstance(value.get("scope"), dict)
        or not isinstance(value.get("request"), dict)
        or not isinstance(value["request"].get("text"), str)
        or not value["request"]["text"].strip()
        or value.get("digest")
        != canonical_digest({key: item for key, item in value.items() if key != "digest"})
    ):
        raise AgentRuntimeContractError("goal_changed", "原始目标合同无效或已改变")
    return copy.deepcopy(value)


def validate_runtime_goal(run: Any) -> str:
    """Recheck immutable request and scope for each grant, tool and final decision."""
    contract = validate_goal_contract(run.metadata.get("runtime_goal_contract"))
    if contract != build_goal_contract(
        run,
        attachments=contract["request"].get("attachments"),
        context_evidence=contract["request"].get("context_evidence"),
    ):
        raise AgentRuntimeContractError("goal_changed", "原任务、历史或授权范围已改变")
    return str(contract["digest"])


def goal_answers(run: Any) -> list[dict[str, Any]]:
    """Only host-persisted answers extend the original request, never model history."""
    return [
        {
            "source_id": f"answer:{event.event_id}",
            "question": event.data.get("question"),
            "answer": event.data.get("answer"),
            "input_data": copy.deepcopy(event.data.get("input_data")),
        }
        for event in run.events
        if event.event_type == "runtime.input_answered"
    ]


def plan_navigation_entries(contract: dict[str, Any]) -> list[dict[str, Any]]:
    if contract["scope"].get("requested_deliverable") != "action_plan":
        return []
    return next(
        (
            evidence["entries"]
            for evidence in contract["request"].get("context_evidence") or []
            if evidence.get("source") == "desktop_navigation"
        ),
        [],
    )


def review_schema(
    contract: dict[str, Any],
    *,
    action_catalog: dict[str, list[str]] | None = None,
    file_evidence: dict[str, dict[str, Any]] | None = None,
    receipt_ids: tuple[str, ...] = (),
    source_block_ids: tuple[str, ...] = (),
    response_block_ids: tuple[str, ...] = (),
    answers: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    schema = GoalReview.model_json_schema()
    assessment = schema["$defs"]["GoalAssessment"]
    properties = assessment["properties"]
    properties["evidence_ids"]["items"]["enum"] = ["response", *receipt_ids]
    assessment["allOf"] = [
        {
            "if": {"properties": {"kind": {"enum": ["reply", "planned_action"]}}},
            "then": {
                "properties": {"evidence_ids": {"items": {"const": "response"}, "maxItems": 1}}
            },
        }
    ]
    sources = goal_source_catalogue(contract, answers)
    properties["source_id"]["enum"] = list(sources)
    source_kinds: dict[tuple[str, ...], list[str]] = {}
    for identity, source in sources.items():
        source_kinds.setdefault(tuple(source["allowed_kinds"]), []).append(identity)
    for source_types, identities in source_kinds.items():
        bound: dict[str, Any] = {"properties": {"kind": {"enum": list(source_types)}}}
        if source_types == ("reply", "constraint"):
            bound["properties"].update(
                status={"enum": ["satisfied", "unmet"]},
                evidence_ids={"items": {"const": "response"}, "maxItems": 1},
            )
            bound["if"] = {"properties": {"kind": {"const": "constraint"}}}
            bound["then"] = {"properties": {"evidence_ids": {"minItems": 1}}}
        assessment["allOf"].append(
            {"if": {"properties": {"source_id": {"enum": identities}}}, "then": bound}
        )
    plan_content = schema["properties"]["plan_content"]
    if contract["scope"].get("plan_delivery_version") == 1:
        plan_content.pop("default")
        plan_content.pop("anyOf")
        plan_content["enum"] = ["steps", "narrative"]
        schema["required"].append("plan_content")
    else:
        schema["properties"].pop("plan_content")
    kinds = properties["kind"]["enum"]
    if contract["scope"].get("requested_deliverable") == "action_plan":
        kinds.remove("read")
        kinds.remove("write")
        # Use the same tenant-visible business identities as MCP tools/list.
        # Transport tool names and inaccessible tool/action pairs are not business operations.
        if action_catalog:
            schema["$defs"]["PlannedToolCall"]["oneOf"] = [
                {"properties": {"tool_id": {"const": tool_id}, "action": {"enum": actions}}}
                for tool_id, actions in action_catalog.items()
            ]
        elif action_catalog is not None:
            properties["planned_calls"]["maxItems"] = 0
    else:
        kinds.remove("planned_action")
    if entries := plan_navigation_entries(contract):
        ids = schema["$defs"]["PlannedNavigation"]["properties"]["navigation_id"]
        ids["enum"] = [entry["id"] for entry in entries]
    else:
        properties.pop("planned_navigation")
        schema["$defs"].pop("PlannedNavigation")
    if file_evidence is None:
        properties.pop("file_basis")
        properties.pop("file_citations")
        schema["$defs"].pop("FileCitation")
    else:
        schema["properties"]["feedback_disposition"].pop("default")
        schema["required"].append("feedback_disposition")
        properties["file_basis"].pop("anyOf")
        properties["file_basis"].pop("default")
        properties["file_basis"]["enum"] = ["independent", "passages", "complete"]
        assessment["allOf"].append(
            {
                "if": {"properties": {"kind": {"enum": ["read", "reply"]}}},
                "then": {"required": ["file_basis"]},
            }
        )
        if source_block_ids and response_block_ids:
            schema["$defs"]["FileCitation"] = {
                "type": "object",
                "additionalProperties": False,
                "required": ["source_block_id", "response_block_id"],
                "properties": {
                    "source_block_id": {"type": "string", "enum": list(source_block_ids)},
                    "response_block_id": {"type": "string", "enum": list(response_block_ids)},
                },
            }
        else:
            properties["file_citations"].update(maxItems=0, items=False)
            schema["$defs"].pop("FileCitation")
    return schema


def goal_evidence_snapshot(
    contract: dict[str, Any],
    rows: list[dict[str, Any]],
    output: str,
    answers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Deduplicate aliases while binding complete receipts, including failed attempts."""
    contract = validate_goal_contract(contract)
    evidence: dict[str, dict[str, Any]] = {}
    tasks: dict[str, str] = {}
    effects: dict[str, str] = {}
    conflicts = []
    for row in rows:
        child = str(row.get("child_run_id") or "")
        task = str(row.get("child_task_id") or "")
        operation = {key: copy.deepcopy(row.get(key)) for key in ("tool_id", "action", "params")}
        fingerprint = canonical_digest(operation)
        raw_receipt = row.get("receipt")
        receipt = copy.deepcopy(raw_receipt) if isinstance(raw_receipt, dict) else {}
        item = {
            "evidence_id": child,
            "task_id": task,
            **operation,
            "fingerprint": fingerprint,
            "read_only": row.get("read_only") is True,
            "state": row.get("state"),
            "created_at": row.get("created_at"),
            "receipt": receipt,
        }
        if (
            not child
            or not task
            or not isinstance(raw_receipt, dict)
            or row.get("fingerprint") != fingerprint
            or receipt.get("run_id") != child
            or receipt.get("task_id") != task
            or tasks.get(task, child) != child
            or (child in evidence and evidence[child] != item)
            or (not item["read_only"] and fingerprint in effects and effects[fingerprint] != child)
        ):
            conflicts.append(child or task or "missing_child_identity")
        else:
            evidence[child], tasks[task] = item, child
            if not item["read_only"]:
                effects[fingerprint] = child
    snapshot = {
        "goal_digest": contract["digest"],
        "answers": copy.deepcopy(answers or []),
        "evidence": [evidence[key] for key in sorted(evidence)],
        "conflicts": sorted(set(conflicts)),
        "response_digest": canonical_digest(output),
    }
    return {**snapshot, "digest": canonical_digest(snapshot)}


def _verified_evidence(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        row["evidence_id"]: row
        for row in snapshot["evidence"]
        if row["state"] == "completed"
        and row["receipt"].get("status") == "completed"
        and row["receipt"].get("success") is True
        and row["receipt"].get("verified") is True
        and not execution_result_outcome_unknown(row["receipt"], include_execution=True)
        and not execution_result_error(row["receipt"])
    }


def _file_source(data: dict[str, Any], *, origin: str) -> dict[str, Any] | None:
    name, text, sha256, coverage = (data.get(key) for key in ("name", "text", "sha256", "coverage"))
    if (
        isinstance(name, str)
        and isinstance(text, str)
        and text.strip()
        and isinstance(sha256, str)
        and re.fullmatch(r"[0-9a-f]{64}", sha256)
        and isinstance(coverage, dict)
        and type(coverage.get("truncated")) is bool
        and coverage.get("method") != "ocr_unverified"
    ):
        return {
            "name": name,
            "sha256": sha256,
            "origin": origin,
            "text": text,
            "coverage": coverage,
        }
    return None


def runtime_file_evidence(
    contract: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, dict[str, Any]] | None:
    """Only already admitted bytes or independently checked child readback can prove a claim."""
    request = contract["request"]
    sources: dict[str, dict[str, Any]] = {}
    upload_ids: set[str] = set()
    for item in request.get("attachments") or []:
        if item.get("source") != "owned_elt_upload":
            continue
        metadata, preview = item.get("metadata") or {}, item.get("preview") or {}
        upload_id = metadata.get("upload_id")
        if isinstance(upload_id, str) and upload_id:
            upload_ids.add(upload_id)
            if source := _file_source(
                {**preview, "name": item.get("name"), "sha256": metadata.get("sha256")},
                origin="original_request.attachments",
            ):
                sources[upload_id] = source
    for catalogue in request.get("context_evidence") or []:
        if catalogue.get("source") != "conversation_uploads":
            continue
        entries = {item["upload_id"]: item for item in catalogue.get("entries") or []}
        upload_ids.update(entries)
        reads = catalogue.get("verified_reads")
        if reads is None:
            reads = [catalogue.get("verified_read")]
        elif (
            not isinstance(reads, list)
            or not 2 <= len(reads) <= 4
            or [read.get("upload_id") for read in reads if isinstance(read, dict)] != list(entries)
            or len({entry["source_run_id"] for entry in entries.values()}) != 1
        ):
            continue
        for read in reads:
            if not isinstance(read, dict):
                continue
            origin = entries.get(read.get("upload_id")) or {}
            if origin and origin["source_run_id"] == read.get("source_run_id"):
                if source := _file_source(read, origin="conversation_uploads"):
                    sources[read["upload_id"]] = source
    if not upload_ids:
        return None
    verified = _verified_evidence(snapshot)
    verified_files = {
        artifact.get("uri")
        for row in verified.values()
        if row["read_only"] is False
        for artifact in row["receipt"].get("artifacts") or []
        if isinstance(artifact, dict) and artifact.get("artifact_type") == "file"
    }
    for identity, row in verified.items():
        calls = row["receipt"].get("tool_calls") or []
        if row["read_only"] is not True or len(calls) != 1:
            continue
        params = row.get("params") or {}
        input_data = params.get("input") if isinstance(params, dict) else None
        call = calls[0]
        output = call.get("output") if isinstance(call, dict) else None
        data = output.get("data") if isinstance(output, dict) else None
        if (
            (row.get("tool_id"), row.get("action")) == ("employee", "execute")
            and params.get("employee_id") == "excel-full-read-employee"
            and isinstance(input_data, dict)
            and input_data.get("file_path") in verified_files
            and isinstance(data, dict)
            and isinstance(readback := data.get("readback"), dict)
        ):
            artifacts = row["receipt"].get("artifacts") or []
            proof = (call.get("metadata") or {}).get("verification") or {}
            checks = proof.get("checks") or []
            if (
                len(artifacts) == 1
                and any(
                    check.get("source") == "run_artifact"
                    and check.get("status") == "passed"
                    and (check.get("evidence") or {}).get("sha256") == readback.get("sha256")
                    and (check.get("evidence") or {}).get("artifact_id")
                    == artifacts[0].get("artifact_id")
                    for check in checks
                    if isinstance(check, dict)
                )
                and artifacts[0].get("metadata", {}).get("sha256") == readback.get("sha256")
            ):
                if source := _file_source(readback, origin="verified_workbook_readback"):
                    sources[identity] = source
        upload_id = (row.get("params") or {}).get("upload_id")
        if not isinstance(upload_id, str) or upload_id not in upload_ids:
            continue
        if not isinstance(data, dict) or data.get("upload_id") != upload_id:
            continue
        proof = (call.get("metadata") or {}).get("verification") or {}
        if proof.get("status") != "verified" or not any(
            check.get("source") == "owned_attachment"
            and check.get("status") == "passed"
            and check.get("evidence")
            == {key: data.get(key) for key in ("upload_id", "sha256", "coverage")}
            for check in proof.get("checks") or []
        ):
            continue
        if source := _file_source(data, origin="evidence"):
            sources[identity] = source
    return sources


_FUTURE_SCOPE_RE = re.compile(
    r"(?:接下来|后续|以后|之后|未来)(?:的)?(?:所有|全部|每一|每次|每个)?(?:对话|回复|回答|轮次|回合)"
)
_REPLY_STYLE_RE = re.compile(r"语气|口吻|风格|说话方式|措辞|称呼")
_STYLE_NEGATION_RE = re.compile(r"不要|不得|禁止|请勿|勿再|停止|取消|别再")


def is_deferred_reply_preference(request_text: str, goal: GoalAssessment) -> bool:
    """Host-only: a future-turn tone preference cannot be proven by this turn's reply."""
    if goal.kind != "constraint" or goal.status != "not_applicable" or goal.evidence_ids:
        return False
    source = goal.source
    if source not in request_text or not source.strip():
        return False
    # 引用、转述或被括起来的要求不是在要求本轮执行。
    start = request_text.index(source)
    before = request_text[start - 1] if start else ""
    after = request_text[start + len(source)] if start + len(source) < len(request_text) else ""
    if (before and before in "“”\"'「」『』（(") or (after and after in "“”\"'「」『』）)"):
        return False
    if not (_FUTURE_SCOPE_RE.search(source) and _REPLY_STYLE_RE.search(source)):
        return False
    return not _STYLE_NEGATION_RE.search(source)


def _batch_goal_capacity(row: dict[str, Any]) -> int:
    """Bound a workbook batch by independently checked changes, not plan grouping."""
    params = row.get("params")
    if (row.get("tool_id"), row.get("action")) != ("employee", "execute") or not isinstance(
        params, dict
    ):
        return 1
    if params.get("employee_id") != "excel-template-write-employee":
        return 1
    for step in row["receipt"].get("verification", {}).get("steps") or []:
        for check in step.get("checks") or []:
            evidence = check.get("evidence") or {}
            changes = evidence.get("cell_changes") or {}
            if (
                check.get("source") == "workbook_qc"
                and check.get("status") == "passed"
                and evidence.get("sections", {}).get("conformance") == "pass"
                and changes.get("scan_complete") is True
            ):
                count = 0
                for group in changes.get("groups") or []:
                    amount = group.get("count") if isinstance(group, dict) else None
                    if type(amount) is int:
                        count += amount
                return min(64, max(1, count))
    return 1


def planned_tool_calls(review: dict[str, Any]) -> list[dict[str, Any]]:
    return [call for goal in review["goals"] for call in goal.get("planned_calls", [])]


def _plan_proofs_match(review: dict[str, Any], proofs: Any) -> bool:
    calls = planned_tool_calls(review)
    return (
        isinstance(proofs, list)
        and len(calls) == len(proofs)
        and all(
            isinstance(proof, dict)
            and proof.get("call_digest") == canonical_digest(call)
            and isinstance(proof.get("schema_digest"), str)
            and bool(re.fullmatch(r"[0-9a-f]{64}", proof["schema_digest"]))
            for call, proof in zip(calls, proofs, strict=True)
        )
    )


def _navigation_path_matches(entry: dict[str, Any], excerpt: str) -> bool:
    for label in (*entry["breadcrumb"], entry["label"]):
        _, matched, excerpt = excerpt.partition(label)
        if not matched:
            return False
    return True


def _quotes_planned_action(call: PlannedToolCall, output: str) -> bool:
    excerpt = call.response_excerpt
    if excerpt not in output:
        return False
    identity = re.escape(f"{call.tool_id}.{call.action}")
    reference = re.compile(rf"(?<![\w.]){identity}(?!\w|\.\w)", re.ASCII)
    if reference.search(excerpt):
        return bool(reference.search(output))
    # The public MCP adapter also represents a business operation as two named
    # arguments. Require a single unambiguous pair in the quoted invocation.
    if not re.search(r"(?<![\w.])(?:mcp__xcmax__)?execute_action(?![\w.])", excerpt, re.ASCII):
        return False
    fields = re.findall(
        r"""(?<![\w.])["']?(tool_id|action)["']?\s*[:=]\s*["']?([\w.-]+)""", excerpt, re.ASCII
    )
    return sorted(fields) == [("action", call.action), ("tool_id", call.tool_id)] and bool(
        re.search(rf"(?<![\w.-]){re.escape(excerpt)}(?![\w.-])", output, re.ASCII)
    )


def validate_goal_review(
    raw: Any,
    contract: dict[str, Any],
    snapshot: dict[str, Any],
    output: str,
    *,
    file_evidence: dict[str, dict[str, Any]] | None = None,
    require_completion: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    """A model can associate facts with goals; it cannot mint execution evidence."""
    review = GoalReview.model_validate(raw)
    sources = goal_source_catalogue(contract, snapshot["answers"])
    constraints = contract["scope"].get("constraints") or {}
    # History can ground a retained term in today's reply, never serve as
    # the current objective or authorize a tool action.
    current_reply = any(
        (goal.source_id == "request" or goal.source_id.startswith("answer:"))
        and goal.source_id in sources
        and goal.kind == "reply"
        and (
            (goal.status == "satisfied" and goal.evidence_ids == ["response"])
            or (goal.status == "unmet" and goal.evidence_ids in ([], ["response"]))
        )
        and goal.source in sources[goal.source_id]["text"]
        for goal in review.goals
    )
    prior_requests = [
        source["text"] for key, source in sources.items() if key.startswith("history:")
    ]
    evidence = {row["evidence_id"]: row for row in snapshot["evidence"]}
    verified = _verified_evidence(snapshot)
    if file_evidence is None:
        file_evidence = runtime_file_evidence(contract, snapshot)
    errors = list(snapshot["conflicts"])
    if file_evidence is not None:
        if review.feedback_disposition is None:
            errors.append("附件核验缺少反馈结论")
        elif require_completion and review.feedback_disposition == "blocking":
            errors.append(review.feedback or "附件事实未通过核验")
    seen: set[str] = set()
    used_writes: set[str] = set()
    assigned: dict[str, list[str]] = {}
    deferred_preferences = 0
    planned_delivery = contract["scope"].get("requested_deliverable") == "action_plan"
    navigation = {entry["id"]: entry for entry in plan_navigation_entries(contract)}
    for goal in review.goals:
        if (goal.kind == "planned_action" and not planned_delivery) or (
            goal.kind in {"read", "write"} and planned_delivery
        ):
            errors.append(f"目标 {goal.goal_id} 与原任务的交付类型不符")
        has_plan_evidence = bool(goal.planned_calls or goal.planned_navigation)
        if has_plan_evidence and goal.kind != "planned_action":
            errors.append(f"目标 {goal.goal_id} 的动作或入口需要按方案核对")
        if goal.kind == "planned_action" and goal.status == "satisfied" and not has_plan_evidence:
            errors.append(
                f"方案目标 {goal.goal_id} 缺少可核对的业务动作或人工入口。请按当前账号能力及导航目录给出方案。"
            )
        for citation in goal.planned_navigation:
            entry = navigation.get(citation.navigation_id)
            if (
                entry is None
                or citation.response_excerpt not in output
                or not _navigation_path_matches(entry, citation.response_excerpt)
            ):
                errors.append(f"方案入口 {citation.navigation_id} 与当前导航或成稿原文不一致")
        for call in goal.planned_calls:
            if not _quotes_planned_action(call, output):
                errors.append(f"方案动作 {call.tool_id}.{call.action} 未见于当前成稿")
        source = sources.get(goal.source_id)
        source_known = source is not None
        source_matches = source is not None and goal.source in source["text"]
        # Persisted v2 reports used a user-history alias. New reports receive
        # granular IDs; compatibility must not promote assistant/tool text.
        if goal.source_id == "history":
            source_known = bool(prior_requests)
            source_matches = any(goal.source in text for text in prior_requests)
        if goal.goal_id in seen:
            errors.append(f"goal_id_duplicate: 目标 {goal.goal_id} 的唯一标识重复")
        if not source_known:
            errors.append(
                f"goal_source_unknown: 目标 {goal.goal_id} 的来源 {goal.source_id} 不存在，缺少原始请求证据"
            )
        elif not source_matches:
            errors.append(
                f"goal_source_mismatch: 目标 {goal.goal_id} 的引用不匹配来源 {goal.source_id}，缺少原始请求证据"
            )
        if (goal.source_id == "history" or goal.source_id.startswith("history:")) and not (
            current_reply
            and goal.kind in {"reply", "constraint"}
            and (goal.kind == "reply" or goal.evidence_ids == ["response"])
            and (
                (goal.status == "satisfied" and goal.evidence_ids == ["response"])
                or (goal.status == "unmet" and goal.evidence_ids in ([], ["response"]))
            )
        ):
            errors.append(
                f"goal_history_scope_invalid: 目标 {goal.goal_id} 的历史来源仅能补充本轮回复条件，不能授权业务动作"
            )
        seen.add(goal.goal_id)
        if file_evidence is not None and goal.kind in {"read", "reply"} and goal.file_basis is None:
            errors.append(f"目标 {goal.goal_id} 未区分附件事实与独立回复")
        if goal.file_basis in {"passages", "complete"}:
            if goal.status != "unmet" and (
                goal.status != "satisfied"
                or not goal.file_citations
                or not file_evidence
                or any(
                    citation.evidence_id not in file_evidence
                    or citation.response_excerpt not in output
                    or citation.source_excerpt not in file_evidence[citation.evidence_id]["text"]
                    or (
                        goal.file_basis == "complete"
                        and file_evidence[citation.evidence_id]["coverage"]["truncated"]
                    )
                    for citation in goal.file_citations
                )
            ):
                errors.append(
                    f"目标 {goal.goal_id} 缺少可核对的文件内容或所需完整范围，不能确认附件事实"
                )
        elif goal.file_citations:
            errors.append(f"目标 {goal.goal_id} 的文件引文缺少来源类型")
        selected = set(goal.evidence_ids)
        if len(selected) != len(goal.evidence_ids) or selected - evidence.keys() - {"response"}:
            errors.append(f"目标 {goal.goal_id} 引用了不存在的回执")
        if is_deferred_reply_preference(contract["request"]["text"], goal):
            # 跨轮回复偏好由宿主依据原文识别，本轮只记录待观察，不算已核验。
            deferred_preferences += 1
            continue
        if goal.status == "unmet":
            if require_completion:
                errors.append(f"目标 {goal.goal_id} 尚未完成")
            continue
        # 只引用正文的约束只能约束回复本身，按正文目标核对，不要求业务回执。
        if goal.kind in {"reply", "planned_action"} or (
            goal.kind == "constraint" and selected == {"response"}
        ):
            if goal.status != "satisfied" or selected != {"response"} or not output.strip():
                errors.append(f"回复目标 {goal.goal_id} 没有完整正文")
        elif goal.kind in {"read", "write"}:
            if not selected or not selected <= verified.keys():
                errors.append(f"业务目标 {goal.goal_id} 缺少独立核验的原任务回执")
            if goal.status == "not_applicable":
                if not selected or any(
                    not verified.get(key, {}).get("read_only") for key in selected
                ):
                    errors.append(f"条件目标 {goal.goal_id} 未提供只读前提证据")
            elif goal.kind == "write":
                writes = {
                    key for key in selected if not verified.get(key, {}).get("read_only", True)
                }
                if not writes:
                    errors.append(f"写入目标 {goal.goal_id} 不能用只读结果冒充完成")
                used_writes.update(writes)
                for key in writes:
                    owners = assigned.get(key)
                    if owners is None:
                        assigned[key] = [goal.goal_id]
                    elif len(owners) < _batch_goal_capacity(verified[key]):
                        owners.append(goal.goal_id)
                    else:
                        errors.append(f"目标 {goal.goal_id} 重用了 {owners[0]} 的同一写入回执")
            elif any(not verified.get(key, {}).get("read_only", True) for key in selected):
                errors.append(f"只读目标 {goal.goal_id} 包含额外写入")
        elif goal.status != "satisfied" or selected - verified.keys():
            errors.append(f"约束 {goal.goal_id} 的核验无效")
    if deferred_preferences and not any(
        goal.kind == "reply"
        and goal.status == "satisfied"
        and set(goal.evidence_ids) == {"response"}
        for goal in review.goals
    ):
        # 跨轮偏好不能替代本轮实际交付。
        errors.append("跨轮回复偏好未附带本轮已核验的回复目标")
    successful_writes = {
        key
        for key, row in evidence.items()
        if not row["read_only"] and row["receipt"].get("success") is True
    }
    if successful_writes - used_writes:
        errors.append("存在未被原始目标覆盖的写入回执")
    bound = constraints.get("objective")
    if bound:
        bound_goals = [goal for goal in review.goals if goal.source_id == "objective"]
        if not bound_goals:
            errors.append("未核对宿主绑定的经营目标")
        elif any(
            goal.kind not in {"read", "write"}
            or (
                (require_completion or goal.status != "unmet")
                and (
                    goal.status != "satisfied"
                    or not goal.evidence_ids
                    or not set(goal.evidence_ids) <= verified.keys()
                )
            )
            for goal in bound_goals
        ):
            # 宿主已结构化的经营义务不能用回复或空证据降级为完成。
            errors.append("宿主绑定的经营目标必须由独立核验的业务回执证明")
    return review.model_dump(), errors


def valid_compensation_review(
    raw: Any,
    contract: dict[str, Any],
    snapshot: dict[str, Any],
    output: str,
    *,
    file_evidence: dict[str, dict[str, Any]] | None = None,
) -> bool:
    """A missing outcome is actionable only when its original provenance is valid.

    This does not authorize any tool or new goal. The ordinary review validator
    still checks schema, source, evidence, completed effects and scope; only
    incompleteness itself is allowed through this continuation boundary.
    """
    try:
        review, errors = validate_goal_review(
            raw,
            contract,
            snapshot,
            output,
            file_evidence=file_evidence,
            require_completion=False,
        )
        if errors:
            return False
        if file_evidence is None:
            file_evidence = runtime_file_evidence(contract, snapshot)
        # An unmet file goal may lack a citation or complete input. Any citation
        # it does supply must still refer to the real current source and output.
        for goal in review["goals"]:
            if goal["status"] != "unmet":
                continue
            for citation in goal["file_citations"]:
                source = (file_evidence or {}).get(citation["evidence_id"])
                if (
                    source is None
                    or citation["source_excerpt"] not in source["text"]
                    or citation["response_excerpt"] not in output
                ):
                    return False
    except (TypeError, ValueError, KeyError):
        return False
    return True


def goal_report_coverage(
    contract: Any,
    rows: list[dict[str, Any]],
    output: str,
    answers: list[dict[str, Any]] | None,
    report: Any,
) -> dict[str, Any]:
    """Re-evaluate a persisted report against the exact current host evidence."""
    result = {"completed": False, "required": 0, "verified": 0, "mode": "business", "errors": []}
    try:
        snapshot = goal_evidence_snapshot(contract, rows, output, answers)
        if (
            not isinstance(report, dict)
            or report.get("protocol") != GOAL_PROTOCOL
            or report.get("goal_digest") != contract["digest"]
            or report.get("evidence_digest") != snapshot["digest"]
            or report.get("response_digest") != canonical_digest(output)
            or report.get("report_digest")
            != canonical_digest(
                {key: value for key, value in report.items() if key != "report_digest"}
            )
        ):
            result["errors"] = ["目标、补答、执行回执或回复已改变，需要重新核验"]
            return result
        proof = report.get("plan_delivery")
        if contract["scope"].get("plan_delivery_version") == 1 and (
            not isinstance(proof, dict)
            or proof.get("kind") not in {"steps", "narrative"}
            or not isinstance(report.get("review"), dict)
            or report["review"].get("plan_content") != proof["kind"]
            or proof.get("goal_digest") != contract["digest"]
            or proof.get("response_digest") != snapshot["response_digest"]
        ):
            result["errors"] = ["方案缺少宿主验证的交付记录"]
            return result
        review, errors = validate_goal_review(report.get("review"), contract, snapshot, output)
        plan_verified = _plan_proofs_match(review, report.get("plan_capabilities", []))
        if not plan_verified:
            errors.append("方案缺少与成稿动作一致的宿主能力校验证据")
        goals = review["goals"]
        mode = "business" if any(g["kind"] in {"read", "write"} for g in goals) else "reply"
        complete = not (errors or review["violations"] or review["uncovered_sources"])
        return {
            "completed": complete
            and report.get("status") == "verified"
            and report.get("accepted") is True
            and all(g["status"] != "unmet" for g in goals),
            "required": len(goals),
            "verified": sum(
                g["status"] == "satisfied"
                and (g.get("file_basis") not in {"passages", "complete"} or complete)
                and (
                    g["kind"] != "planned_action"
                    or (
                        complete
                        and plan_verified
                        and bool(g["planned_calls"] or g["planned_navigation"])
                    )
                )
                for g in goals
            ),
            "mode": mode,
            "errors": errors + review["violations"] + review["uncovered_sources"],
        }
    except (TypeError, ValueError, KeyError, ValidationError):
        result["errors"] = ["原始目标核验报告无效"]
        return result
