"""Bind sourced XiaoC reflections to the existing Retort and portfolio ledgers.

This adapter creates proposals only. Original Retort approvals, engineering
budgets, isolated workers and verified delivery receipts remain authoritative.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from modstore_server import xiaoc_life_store as life
from modstore_server.customer_service_tools import json_loads
from modstore_server.db.xiaoc_life import XiaoCLifeEvent, XiaoCLifeState
from modstore_server.models import RetortEvolutionRun
from modstore_server.strategic_portfolio import PortfolioError, digest
from modstore_server.xiaoc_life_policy import IDENTITY_ID, LifePolicyError, parse_time


def reflection_template(template_id: str, owner: int) -> dict[str, Any]:
    from modstore_server.retort_evolution_api import _templates

    template = _templates().get(template_id)
    policy = template.get("life_reflection") if isinstance(template, dict) else None
    if (
        not isinstance(policy, dict)
        or type(policy.get("owner_id")) is not int
        or policy["owner_id"] != owner
        or not isinstance(policy.get("goal"), str)
        or not 1 <= len(policy["goal"].strip()) <= 12000
        or not all(
            isinstance(policy.get(key), str) and policy[key].strip()
            for key in ("provider", "model")
        )
        or not all(
            key in template for key in ("name", "criterion_ids", "checks", "container_image")
        )
    ):
        raise LifePolicyError("请配置属于当前授权人的原改进验收方案、公开目标与模型路由")
    return cast(dict[str, Any], deepcopy(template))


def private_source(request_id: str, *, session: Any = None) -> dict[str, Any] | None:
    if session is None:
        with life.get_session_factory()() as db:
            return private_source(request_id, session=db)
    row = session.get(RetortEvolutionRun, request_id)
    source = json_loads(row.effects_json, {}).get("life_reflection") if row else None
    if source is None:
        return None
    saved = session.get(XiaoCLifeState, IDENTITY_ID)
    data = json_loads(saved.state_json, {}) if saved else {}
    goal = next(
        (g for g in data.get("goals", []) if g.get("retort_request_id") == request_id), None
    )
    owner = data.get("owner_user_id")
    if goal is None or type(owner) is not int:
        raise LifePolicyError("原改进任务没有小 C 来源绑定")
    return _original(session, goal, owner)[1]


def _check_approved_source(source: dict[str, Any] | None, state: dict[str, Any]) -> None:
    if source is None:
        return
    from modstore_server.integrations.repository_packages import load_repository_module

    contract = load_repository_module("retort_engine.evolution_contract")
    approval = state.get("approval") or {}
    if (
        (state.get("plan") or {}).get("private_life_reflection") != source
        or approval.get("approved") is not True
        or approval.get("digest")
        != contract.digest({key: state.get(key) for key in ("protocol", "plan", "optimization")})
    ):
        raise LifePolicyError("原反思来源与改进批准不一致")


def check_dispatch(request_id: str, state: dict[str, Any]) -> None:
    _check_approved_source(private_source(request_id), state)


def private_execution_context(session: Any, event_id: int, payload: dict[str, Any]):
    """Feed the original private prompt port, without public issue/PR text."""
    from modstore_server.retort_github_workspace import authorized_incident

    request_id = payload.get("retort_run_id")
    source = private_source(request_id, session=session) if request_id else None
    if source is None:
        return None
    if not authorized_incident(session, payload, event_id, read_only=True):
        raise LifePolicyError("原反思员工任务身份未核验")
    row = session.get(RetortEvolutionRun, request_id)
    effects = json_loads(row.effects_json, {})
    _check_approved_source(
        source,
        {
            "protocol": json_loads(row.protocol_json, {}),
            "plan": effects.get("plan"),
            "optimization": effects.get("optimization"),
            "approval": effects.get("authorization"),
        },
    )
    return {
        "intent": "evidence_linked_life_reflection",
        "reproduction": [
            *source["private_goal"].values(),
            "evidence_refs: " + ", ".join(source["evidence_refs"]),
        ],
        "context_sha256": digest(source),
    }


def _original(
    session: Any, goal: dict[str, Any], owner: int
) -> tuple[RetortEvolutionRun, dict[str, Any]]:
    row = session.get(RetortEvolutionRun, goal["retort_request_id"])
    source = json_loads(row.effects_json, {}).get("life_reflection") if row else None
    if (
        row is None
        or row.user_id != owner
        or not isinstance(source, dict)
        or source.get("identity_id") != IDENTITY_ID
        or source.get("goal_id") != goal["id"]
        or source.get("owner_user_id") != owner
        or digest(source) != goal.get("evolution_source_sha256")
    ):
        raise LifePolicyError("原改进任务身份、来源或责任人已变化")
    return row, source


def propose(claim: dict[str, Any], goal: dict[str, Any]) -> dict[str, Any]:
    """Commit the original Retort request and life goal in one SQL transaction."""
    from modstore_server import retort_evolution as retort
    from modstore_server.customer_ticket_github import configuration, github

    owner = claim["owner_user_id"]
    if claim["domain"] != "reflection" or not goal.get("evidence_refs"):
        raise LifePolicyError("只有带原来源的 L6 反思可以形成改进提案")
    if goal.get("retort_request_id"):
        with life.get_session_factory()() as session:
            _original(session, goal, owner)
        return goal
    template_id = claim["state"]["policy"].get("retort_template_id", "")
    template = reflection_template(template_id, owner)
    public = template["life_reflection"]
    repository = configuration()["repository"]
    source_sha = github("GET", f"/repos/{repository}/commits/main")["sha"]
    request_id = str(uuid5(NAMESPACE_URL, f"{IDENTITY_ID}:{owner}:reflection:{goal['id']}"))
    request = {key: template[key] for key in ("criterion_ids", "checks", "container_image")}
    request.update(
        request_id=request_id,
        title=template["name"],
        goal=public["goal"],
        repository=repository,
        source_sha=source_sha,
    )
    source = {
        "identity_id": IDENTITY_ID,
        "owner_user_id": owner,
        "goal_id": goal["id"],
        "template_id": template_id,
        "template_sha256": digest(template),
        "evidence_refs": list(goal["evidence_refs"]),
        "private_goal": {key: goal[key] for key in ("title", "description") if key in goal},
        "provider": public["provider"],
        "model": public["model"],
    }

    def bind(data: dict[str, Any], session: Any) -> dict[str, Any]:
        if not life._claim_active(data, session, claim) or data["owner_user_id"] != owner:
            raise LifePolicyError("反思授权已变化，未创建改进任务")
        current = next((item for item in data["goals"] if item["id"] == goal["id"]), None)
        if current and current.get("retort_request_id"):
            _original(session, current, owner)
            return dict(current)
        if current and current.get("decision_id"):
            raise LifePolicyError("已有企业任务不能换绑为改进任务")
        if not current and len(data["goals"]) >= 100:
            raise LifePolicyError("life_goal_capacity_reached")
        if (
            data["policy"].get("retort_template_id") != template_id
            or digest(reflection_template(template_id, owner)) != source["template_sha256"]
        ):
            raise LifePolicyError("原改进验收方案已变化，请重新核对")
        retort.create_run(request, owner, life_reflection=source, _session=session)
        linked = {
            **goal,
            "retort_request_id": request_id,
            "evolution_source_sha256": digest(source),
            "status": "awaiting_approval",
        }
        data["goals"] = life._merge(data["goals"], [linked], "id", 100)
        life._event(
            session,
            "evolution-proposal:" + request_id,
            kind="reflection",
            status="awaiting_approval",
            summary="已将有来源的反思绑定原改进流程，等待原审批与公司执行预算。",
            evidence_refs=[*source["evidence_refs"], "retort:" + request_id],
        )
        return linked

    return life._mutate(bind)


def pending_budget(state: dict[str, Any], domain: str) -> dict[str, Any] | None:
    if domain != "reflection":
        return None
    with life.get_session_factory()() as session:
        for goal in state.get("goals", []):
            if not goal.get("retort_request_id") or goal.get("decision_id"):
                continue
            row, _ = _original(session, goal, state["owner_user_id"])
            if (
                row.status in {"waiting_execution", "waiting_credential_isolation"}
                and json_loads(str(row.effects_json), {}).get("authorization", {}).get("approved")
                is True
            ):
                return dict(goal)
    return None


def propose_budget(claim: dict[str, Any], goal: dict[str, Any]) -> dict[str, Any]:
    """Freeze a proposal intent before creating the existing strategic decision."""
    from modstore_server.strategic_portfolio import create_portfolio_proposal
    from modstore_server.strategic_workspace_bridge import KIND, original

    def freeze(data: dict[str, Any], session: Any) -> dict[str, Any]:
        if claim["domain"] != "reflection" or not life._claim_active(data, session, claim):
            raise LifePolicyError("反思授权已变化，未创建工程预算提案")
        target = next(item for item in data["goals"] if item["id"] == goal["id"])
        if target.get("decision_id"):
            return {"decision_id": target["decision_id"]}
        row, source = _original(session, target, claim["owner_user_id"])
        protocol, effects = json_loads(str(row.protocol_json), {}), json_loads(
            str(row.effects_json), {}
        )
        remote = {
            "kind": KIND,
            "original_request_id": row.id,
            "repository": protocol["repository"],
            "source_sha": protocol["source_sha"],
            "protocol_digest": protocol["protocol_digest"],
            "approval_digest": effects.get("authorization", {}).get("digest", ""),
            "provider": source["provider"],
            "model": source["model"],
        }
        original(
            session, {**remote, "binding": {"owner_user_id": claim["owner_user_id"]}}, active=True
        )
        if target.get("engineering_intent"):
            return dict(target["engineering_intent"])
        policy = data["policy"]
        limits = policy.get("portfolio_limits") or {}
        if not policy.get("employee_id") or not limits.get("company_budget_id"):
            raise LifePolicyError("原改进任务等待已授权公司预算的企业任务模板")
        if not any(
            t["provider"] == source["provider"] and t["model"] == source["model"]
            for t in limits["tariffs"]
        ):
            raise LifePolicyError("原改进模型路由没有对应的已配置预算费率")
        # The existing phase bridge permits only the exact original work order
        # to retain its lease. Its explicit expiry is part of the later approval.
        remote["life_lease"] = {
            "mode": "persistent_phases",
            "expires_at": min(
                parse_time(limits["expires_at"]), parse_time(policy["authorization_expires_at"])
            ).isoformat(),
        }
        intent = {
            "owner_user_id": claim["owner_user_id"],
            "goal": protocol["title"],
            "period": "xiaoc-life:" + target["id"][:45],
            "limits": deepcopy(limits),
            "opportunities": [
                {
                    "opportunity_id": "life-" + digest(target["id"])[:24],
                    "title": protocol["title"],
                    "task": protocol["goal"][:4000],
                    "employee_id": policy["employee_id"],
                    "input_data": {**policy.get("task_input", {}), "remote_execution": remote},
                    "source_refs": [*target["evidence_refs"][:30], "retort:" + row.id],
                    "value_score": 100,
                    "confidence_bps": 5000,
                    "risk": "medium",
                    **{key: limits[key] for key in ("cost_cents", "tokens", "compute_seconds")},
                }
            ],
            "idempotency_key": "xiaoc-retort:" + row.id,
        }
        target["engineering_intent"] = intent
        return deepcopy(intent)

    intent = life._mutate(freeze)
    if intent.get("decision_id"):
        return {**goal, **intent}
    proposal = create_portfolio_proposal(**intent)
    decision_id = proposal["decision"]["decision_id"]

    def bind(data: dict[str, Any], session: Any) -> dict[str, Any]:
        target = next(item for item in data["goals"] if item["id"] == goal["id"])
        _original(session, target, intent["owner_user_id"])
        if target.get("engineering_intent") != intent or target.get("decision_id") not in (
            None,
            "",
            decision_id,
        ):
            raise LifePolicyError("原工程预算提案身份已变化")
        # A policy change can stop execution, but must not orphan a proposal that
        # already exists. Binding its original ID grants no execution authority.
        target.update(decision_id=decision_id, status="awaiting_approval")
        life._event(
            session,
            "evolution-budget:" + goal["retort_request_id"],
            kind="reflection",
            status="awaiting_approval",
            summary="原改进批准已读回，工程任务进入原公司预算审批，尚未执行。",
            evidence_refs=["retort:" + goal["retort_request_id"], "portfolio:" + decision_id],
        )
        return dict(target)

    return life._mutate(bind)


def _historical_rejection(session: Any, request_id: str) -> str | None:
    """An original request cannot erase a recorded rejection with a later snapshot.

    Use the existing append-only events, not the bounded goal projection. The
    exact request ID is immutable and already bound to its owner and protocol.
    """
    events = session.scalars(
        select(XiaoCLifeEvent)
        .where(
            XiaoCLifeEvent.identity_id == IDENTITY_ID,
            XiaoCLifeEvent.kind == "reflection",
            XiaoCLifeEvent.status.in_(("evolution_failed", "waiting_recovery")),
            XiaoCLifeEvent.evidence_json.contains(f'"retort:{request_id}"', autoescape=True),
        )
        .order_by(XiaoCLifeEvent.created_at, XiaoCLifeEvent.id)
    )
    for event in events:
        if f"retort:{request_id}" not in json_loads(event.evidence_json, []):
            continue
        outcome = json_loads(event.details_json, {}).get("evolution_outcome") or {}
        metrics = outcome.get("metrics") or {}
        if event.status == "evolution_failed" or (
            metrics.get("impact_status") == "customer_impact_rejected"
        ):
            return str(outcome.get("evidence_ref") or event.id)
    return None


def feedback(session: Any, goal: dict[str, Any], owner: int) -> dict[str, Any]:
    from modstore_server.strategic_workspace_receipts import _evidence, _terminal

    row, _ = _original(session, goal, owner)
    protocol = json_loads(str(row.protocol_json), {})
    evidence = _evidence(row)
    state = evidence["snapshot"]
    request = {"original_request_id": row.id, "protocol_digest": protocol["protocol_digest"]}
    status, summary = str(row.status), "原改进流程仍在推进，尚未确认发布与效果。"
    terminal = None
    try:
        terminal = _terminal(request, evidence)
    except PortfolioError:
        status, summary = "evolution_evidence_incomplete", "原改进终态证据不完整，未登记成功。"
    if terminal:
        status = "evolution_delivery_verified" if terminal["ok"] else "evolution_failed"
        summary = (
            "原独立测试、验收与发布身份已核验；业务改善仍以实际效果回执为准。"
            if terminal["ok"]
            else "原改进未成功，已保留失败与恢复回执。"
        )
    elif row.status == "completed" and status != "evolution_evidence_incomplete":
        status, summary = "evolution_evidence_incomplete", "原改进终态投影尚未一致，未登记成功。"
    elif row.status in {"waiting_execution", "waiting_credential_isolation"} and not goal.get(
        "decision_id"
    ):
        status, summary = (
            "awaiting_engineering_budget",
            "原改进批准已记录，等待公司工程预算提案与审批。",
        )
    elif row.status == "customer_impact_rejected":
        status, summary = "waiting_recovery", "真实效果未通过，等待原回滚核验，未登记改进成功。"
    delivery = state.get("delivery") or {}
    impact = state.get("impact") or {}
    verification = state.get("verification") or {}
    current_rejection = (
        status == "evolution_failed" or impact.get("status") == "customer_impact_rejected"
    )
    # Do not re-hash a negative event merely because it has just been persisted.
    historical_rejection = (
        None if current_rejection else _historical_rejection(session, row.id)
    )
    if historical_rejection:
        status = "evolution_evidence_incomplete"
        summary = "原改进曾被拒绝，当前回执与历史失败冲突；须人工复核，不登记成功。"
        terminal = None
    # Delivery and independent checks are not evidence of improved outcomes.
    # The original Retort impact and recovery ports remain authoritative.
    effect_verdict = "not_verified"
    if historical_rejection or current_rejection:
        effect_verdict = "rejected"
    elif (
        terminal
        and terminal["ok"]
        and state.get("has_customer_feedback") is True
        and impact.get("status") == "customer_impact_verified"
        and impact.get("release_sha")
        and impact["release_sha"] == delivery.get("release_sha")
        and impact.get("verified_at")
    ):
        effect_verdict = "impact_receipt_verified"
    audit = {
        "baseline_sha": protocol.get("source_sha", ""),
        "candidate_sha": verification.get("target_sha", ""),
        "protocol_digest": protocol["protocol_digest"],
        "verification_archive_sha256": (verification.get("evidence_archive") or {}).get(
            "sha256", ""
        ),
        "dispatch_approval_digest": (evidence["effects"].get("authorization") or {}).get(
            "digest", ""
        ),
        "acceptance_approval_digest": (state.get("approval") or {}).get("digest", ""),
        "impact_receipt_sha256": digest(impact) if impact else "",
        "recovery_receipt_sha256": digest(state["recovery"]) if state.get("recovery") else "",
        # Code-level CI checks are not a paired baseline/candidate measurement.
        "comparison_status": "paired_measurement_not_established",
        "historical_rejection_ref": historical_rejection,
    }
    metrics = {
        "request_id": row.id,
        "status": status,
        "observed_at": row.updated_at.isoformat() if row.updated_at else "",
        "protocol_digest": protocol["protocol_digest"],
        "checks_status": (state.get("verification") or {}).get("status", "unknown"),
        "delivery_status": delivery.get("status", "unknown"),
        "release_sha": delivery.get("release_sha", ""),
        "impact_status": (state.get("impact") or {}).get("status", "not_measured"),
        "recovery_status": (state.get("recovery") or {}).get("status", "not_requested"),
        "terminal_verified": terminal is not None,
        "effect_verdict": effect_verdict,
        "scope": "original_retort_receipt_not_model_self_assessment",
    }
    return {
        "status": status,
        "summary": summary,
        "metrics": metrics,
        "candidate_audit": audit,
        "evidence_ref": "evolution-outcome:" + row.id + ":"
        + digest({"metrics": metrics, "audit": audit})[:24],
    }


def reconcile() -> int:
    """Read original results even while paused; never advance work or approve it."""

    def update(data: dict[str, Any], session: Any) -> int:
        changed = 0
        for goal in data["goals"]:
            if not goal.get("retort_request_id"):
                continue
            try:
                observed = feedback(session, goal, data["owner_user_id"])
            except (LifePolicyError, ValueError, KeyError):
                observed = {
                    "status": "evolution_evidence_incomplete",
                    "summary": "原改进任务身份或来源暂不能核验，未登记成功。",
                    "metrics": {
                        "request_id": goal["retort_request_id"],
                        "status": "evolution_evidence_incomplete",
                        "observed_at": "",
                        "terminal_verified": False,
                        "effect_verdict": "not_verified",
                    },
                    "evidence_ref": "evolution-outcome:"
                    + goal["retort_request_id"]
                    + ":source-unverified",
                }
            if not goal.get("decision_id") or observed["status"] in {
                "evolution_delivery_verified",
                "evolution_failed",
                "evolution_evidence_incomplete",
                "waiting_recovery",
            }:
                goal["status"] = observed["status"]
            if goal.get("evolution_outcome", {}).get("evidence_ref") == observed["evidence_ref"]:
                continue
            goal["evolution_outcome"] = observed
            event_id = "evolution:" + digest(observed)
            if session.get(XiaoCLifeEvent, event_id) is None:
                life._event(
                    session,
                    event_id,
                    kind="reflection",
                    status=observed["status"],
                    summary=observed["summary"],
                    evidence_refs=["retort:" + goal["retort_request_id"], observed["evidence_ref"]],
                    details={"evolution_outcome": observed},
                )
            changed += 1
        return changed

    return life._mutate(update)


def feedback_facts(state: dict[str, Any]) -> list[dict[str, Any]]:
    observed = [
        goal["evolution_outcome"]
        for goal in state.get("goals", [])
        if goal.get("evolution_outcome")
    ]
    observed.sort(key=lambda row: row["metrics"]["observed_at"], reverse=True)
    return [
        {"ref": row["evidence_ref"], "text": row["summary"], "evolution_feedback": row["metrics"]}
        for row in observed[:2]
    ]
