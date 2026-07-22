"""Evidence-backed founder autonomy scorecard.

The scorecard deliberately treats source capability, local runtime evidence,
and deployed/value evidence as different truth domains.  Missing evidence is
scored as missing; it is never inferred from a route or a source file alone.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class ScoreGate:
    key: str
    label: str
    weight: int
    passed: bool
    evidence: str
    gap: str
    truth_domain: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "weight": self.weight,
            "passed": self.passed,
            "evidence": self.evidence if self.passed else "",
            "gap": "" if self.passed else self.gap,
            "truth_domain": self.truth_domain,
        }


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _first_number(payload: Any, keys: Iterable[str]) -> float:
    wanted = {str(key).lower() for key in keys}

    def walk(value: Any) -> float | None:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in wanted and isinstance(child, (int, float)):
                    return float(child)
            for child in value.values():
                found = walk(child)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = walk(child)
                if found is not None:
                    return found
        return None

    return float(walk(payload) or 0.0)


def _event_text(row: Any) -> str:
    data = _as_dict(row)
    fields = (
        "phase",
        "status",
        "final_status",
        "step",
        "event",
        "event_type",
        "kind",
        "reason",
        "triggered_by",
        "action",
        "environment",
        "deployment_state",
        "qa_verdict",
        "review_verdict",
    )
    return " ".join(str(data.get(key) or "") for key in fields).lower()


def _event_ok(row: Any) -> bool:
    data = _as_dict(row)
    if data.get("ok") is False or data.get("dry_run") is True:
        return False
    text = _event_text(data)
    return not any(token in text for token in (" failed", "failure", "blocked", "held"))


def _has_event(rows: list[Any], *tokens: str, require_ok: bool = True) -> bool:
    lowered = tuple(token.lower() for token in tokens)
    for row in rows:
        text = _event_text(row)
        if all(token in text for token in lowered) and (not require_ok or _event_ok(row)):
            return True
    return False


_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40,64}$")
_PACKAGE_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _is_strong_modstore_deployment(row: Any) -> bool:
    data = _as_dict(row)
    return bool(
        data.get("event_type") == "modstore_deployment_verified"
        and data.get("ok") is True
        and data.get("dry_run") is False
        and data.get("catalog_readback_verified") is True
        and data.get("installability_verified") is True
        and data.get("runtime_contract_verified") is True
        and data.get("strategic_council_verified") is True
        and str(data.get("environment") or "").lower() in {"staging", "production"}
        and str(data.get("package_id") or "").strip()
        and str(data.get("version") or "").strip()
        and _PACKAGE_SHA_RE.fullmatch(
            str(data.get("package_sha256") or "").strip().lower()
        )
    )


def _deployment_key(row: Any) -> tuple[str, str, str, str] | None:
    data = _as_dict(row)
    key = (
        str(data.get("run_id") or "").strip(),
        str(data.get("merge_sha") or "").strip().lower(),
        str(data.get("environment") or "").strip().lower(),
        str(data.get("workflow_run_id") or "").strip(),
    )
    if not all(key) or not _COMMIT_SHA_RE.fullmatch(key[1]):
        return None
    if key[2] not in {"staging", "production"}:
        return None
    return key


def _correlated_deploy_evidence(rows: list[Any]) -> tuple[set[tuple[str, str, str, str]], list[dict[str, Any]]]:
    """Return accepted dispatches and exact matching verified deployments."""

    dispatches: set[tuple[str, str, str, str]] = set()
    for raw in rows:
        row = _as_dict(raw)
        key = _deployment_key(row)
        if (
            key is not None
            and row.get("event") == "deploy_dispatch"
            and row.get("ok") is True
            and row.get("dry_run") is not True
            and str(row.get("status") or "").lower() == "accepted"
        ):
            dispatches.add(key)

    verified: list[dict[str, Any]] = []
    for raw in rows:
        row = _as_dict(raw)
        key = _deployment_key(row)
        if (
            key in dispatches
            and row.get("event") == "post_deploy_verified"
            and row.get("ok") is True
            and row.get("identity_verified") is True
            and row.get("dry_run") is not True
            and str(row.get("status") or "").lower() == "verified"
        ):
            verified.append(row)
    return dispatches, verified


def _latest_event_age_hours(runtime: dict[str, Any], now: datetime) -> float | None:
    raw = str(runtime.get("latest_event_at") or runtime.get("refreshed_at") or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return max(0.0, (now - parsed.astimezone(UTC)).total_seconds() / 3600.0)
    except ValueError:
        return None


def _score_dimension(
    *,
    dimension_id: str,
    label: str,
    target: str,
    gates: list[ScoreGate],
    hard_cap: int | None = None,
) -> dict[str, Any]:
    raw_score = sum(gate.weight for gate in gates if gate.passed)
    score = min(raw_score, hard_cap) if hard_cap is not None else raw_score
    score = max(0, min(100, int(score)))
    if score >= 90:
        status = "ready"
        status_label = "接近目标"
    elif score >= 70:
        status = "approaching"
        status_label = "基本成形"
    elif score >= 40:
        status = "building"
        status_label = "闭环建设中"
    else:
        status = "early"
        status_label = "能力早期"
    missing = [gate.to_dict() for gate in gates if not gate.passed]
    passed = [gate.to_dict() for gate in gates if gate.passed]
    return {
        "id": dimension_id,
        "label": label,
        "target": target,
        "progress": score,
        "remaining": 100 - score,
        "status": status,
        "status_label": status_label,
        "hard_cap": hard_cap,
        "passed_gate_count": len(passed),
        "total_gate_count": len(gates),
        "evidence": passed,
        "gaps": missing,
        "next_gap": missing[0]["gap"] if missing else "保持运行证据并继续观察",
    }


def build_founder_autonomy_snapshot(
    *,
    runtime: dict[str, Any] | None = None,
    closure: dict[str, Any] | None = None,
    approvals: dict[str, Any] | None = None,
    knowledge: dict[str, Any] | None = None,
    goals: dict[str, Any] | None = None,
    finance: dict[str, Any] | None = None,
    customer_value: dict[str, Any] | None = None,
    autonomy_audit: dict[str, Any] | None = None,
    employee_autonomy: dict[str, Any] | None = None,
    employee_capability: dict[str, Any] | None = None,
    dead_letters: dict[str, Any] | None = None,
    strategic_decisions: dict[str, Any] | None = None,
    strategic_council: dict[str, Any] | None = None,
    surfaces: dict[str, Any] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build the seven-dimension founder scorecard from runtime evidence."""

    now = (generated_at or datetime.now(UTC)).astimezone(UTC)
    runtime = _as_dict(runtime)
    closure = _as_dict(closure)
    approvals = _as_dict(approvals)
    knowledge = _as_dict(knowledge)
    goals = _as_dict(goals)
    finance = _as_dict(finance)
    customer_value = _as_dict(customer_value)
    if isinstance(customer_value.get("data"), dict):
        customer_value = _as_dict(customer_value.get("data"))
    autonomy_audit = _as_dict(autonomy_audit)
    if isinstance(autonomy_audit.get("data"), dict):
        autonomy_audit = _as_dict(autonomy_audit.get("data"))
    employee_autonomy = _as_dict(employee_autonomy)
    employee_capability = _as_dict(employee_capability)
    dead_letters = _as_dict(dead_letters)
    strategic_decisions = _as_dict(strategic_decisions)
    strategic_council = _as_dict(strategic_council)
    if isinstance(strategic_council.get("data"), dict):
        strategic_council = _as_dict(strategic_council.get("data"))
    surfaces = _as_dict(surfaces)

    evidence = _as_dict(runtime.get("evidence"))
    rows = _as_list(evidence.get("recent_rows"))
    milestone_rows = _as_list(evidence.get("milestone_rows"))
    timelines = _as_list(runtime.get("run_timelines"))
    timeline_rows = [item for line in timelines for item in _as_list(_as_dict(line).get("items"))]
    all_rows = [
        *rows,
        *milestone_rows,
        *timeline_rows,
        *_as_list(_as_dict(runtime.get("governance_audit")).get("recent")),
    ]

    active_gates = _as_dict(runtime.get("active_gates"))
    governance_gate = _as_dict(runtime.get("governance_gate"))
    evolution_summary = _as_dict(runtime.get("evolution_metrics_summary"))
    current_gate = _as_dict(runtime.get("current_gate"))
    runtime_provenance = _as_dict(current_gate.get("runtime_provenance"))
    contract_status = _as_dict(runtime.get("contract_status"))
    latest_complete = _as_dict(evidence.get("latest_complete"))
    open_run_ids = [str(value) for value in _as_list(evidence.get("open_run_ids")) if str(value)]
    latest_age = _latest_event_age_hours(runtime, now)

    local_pending = _as_int(approvals.get("local_pending"))
    strategic_pending = _as_int(strategic_decisions.get("count"))
    pending_total = local_pending + strategic_pending
    knowledge_documents = _first_number(
        knowledge,
        ("documents", "document_count", "indexed_documents", "sources", "indexed_sources"),
    )
    knowledge_chunks = _first_number(knowledge, ("chunks", "chunk_count", "indexed_chunks"))

    goals_total = _first_number(goals, ("total", "count", "goal_count", "items_total"))
    goals_closed = _first_number(
        goals,
        ("closed", "merged", "completed", "done", "closed_count", "completed_count"),
    )
    goal_completion_rate = _first_number(
        goals, ("completion_rate", "completed_rate", "close_rate", "success_rate")
    )
    if goal_completion_rate > 1:
        goal_completion_rate /= 100.0
    if not goal_completion_rate and goals_total:
        goal_completion_rate = min(1.0, goals_closed / goals_total)

    # Customer-value progress is intentionally isolated from the generic
    # finance summary and internal action items.  Only the authoritative,
    # append-only evidence contract may prove real payment or delivery.
    value_ledger_ready = all(
        (
            bool(customer_value.get("value_ledger_ready")),
            bool(customer_value.get("source_available")),
            bool(customer_value.get("source_authoritative")),
            bool(customer_value.get("append_only_store_available")),
        )
    )
    paid_count = _as_int(customer_value.get("verified_paid_count"))
    paid_amount = _as_int(customer_value.get("verified_paid_amount_cents"))
    customer_goals = _as_int(customer_value.get("customer_goal_count"))
    delivered_count = _as_int(customer_value.get("delivered_count"))
    unproven_delivery_count = _as_int(customer_value.get("unproven_delivery_count"))
    paid_delivery_count = _as_int(customer_value.get("paid_delivery_count"))
    paid_acceptance_count = _as_int(customer_value.get("paid_acceptance_count"))
    production_value_verified = bool(customer_value.get("production_value_verified")) and (
        paid_count > 0 or paid_amount > 0
    )
    outcome_verified = bool(customer_value.get("outcome_verified")) and paid_delivery_count > 0
    customer_acceptance_verified = bool(
        customer_value.get("customer_acceptance_verified")
    ) and paid_acceptance_count > 0
    customer_value_excluded = _as_dict(customer_value.get("excluded"))

    audit_total = _as_int(autonomy_audit.get("total"))
    veto_rate = _as_float(autonomy_audit.get("veto_rate"))
    if 0 < veto_rate <= 1:
        veto_rate *= 100.0
    prohibited_miss_raw = autonomy_audit.get("has_prohibited_miss")
    prohibited_miss = prohibited_miss_raw is True
    prohibited_clear = prohibited_miss_raw is False
    audit_available = all(
        (
            bool(autonomy_audit.get("source_authoritative")),
            bool(autonomy_audit.get("append_only")),
            bool(autonomy_audit.get("append_only_enforced")),
        )
    )
    audit_has_rows = audit_available and audit_total > 0
    veto_channel = _as_dict(autonomy_audit.get("veto_channel"))
    veto_channel_available = bool(veto_channel.get("available"))
    veto_pending = _as_int(veto_channel.get("pending_count"))

    planned = _as_int(employee_capability.get("planned_count")) or _as_int(
        _as_dict(closure.get("staffing")).get("planned_count")
    )
    registered = _as_int(_as_dict(closure.get("staffing")).get("registered_count"))
    participants = _as_list(runtime.get("participants"))
    employee_dashboard_ok = bool(employee_autonomy) and not bool(employee_autonomy.get("error"))
    assigned_employees = _as_int(employee_capability.get("assigned_count"))
    proven_employees = _as_int(employee_capability.get("proven_count"))
    shell_employees = _as_int(employee_capability.get("shell_count"))
    workforce_ready = bool(employee_capability.get("workforce_ready"))
    workforce_assigned = bool(planned) and assigned_employees >= max(1, round(planned * 0.95))
    unresolved_dead_letters = _as_int(dead_letters.get("unresolved_count"))
    resolved_dead_letters = _as_int(dead_letters.get("resolved_count"))
    dead_letter_evidence = "unresolved_count" in dead_letters
    dead_letters_healthy = (
        dead_letter_evidence
        and bool(dead_letters.get("ok"))
        and unresolved_dead_letters == 0
    )

    cron_ok = bool(runtime.get("cron"))
    runtime_fresh = latest_age is not None and latest_age <= 6
    runtime_provenance_ok = runtime_provenance.get("ok") is True
    contract_trusted = bool(contract_status.get("global_ok"))
    gates_clear = bool(active_gates.get("ok"))
    governance_clear = bool(governance_gate.get("ok"))
    has_open_run = bool(open_run_ids)
    latest_completed = str(latest_complete.get("status") or "").startswith("completed")
    latest_merged = "merged" in str(latest_complete.get("status") or "").lower()

    wrote = _has_event(all_rows, "code", "success")
    reviewed = _has_event(all_rows, "review", "success")
    qa_passed = _has_event(all_rows, "qa", "success") or _has_event(all_rows, "qa", "pass")
    merged = latest_merged or _has_event(all_rows, "completed_merged")
    deploy_attempted = _has_event(all_rows, "deploy_dispatch", require_ok=False)
    accepted_deploys, verified_deploys = _correlated_deploy_evidence(all_rows)
    real_deploy_dispatched = bool(accepted_deploys)
    deploy_verified = any(
        str(row.get("environment") or "").lower() == "production"
        for row in verified_deploys
    )

    incident_count = _as_int(current_gate.get("incident_count"))
    incident_triggered = incident_count > 0 or _has_event(all_rows, "incident_event", require_ok=False)
    incident_run_ids = {
        str(_as_dict(row).get("run_id") or "")
        for row in all_rows
        if "incident" in _event_text(row) and str(_as_dict(row).get("run_id") or "")
    }
    repair_run_ids = {
        str(_as_dict(row).get("run_id") or "")
        for row in all_rows
        if _event_ok(row)
        and "code" in _event_text(row)
        and str(_as_dict(row).get("run_id") or "") in incident_run_ids
    }
    completed_repair_run_ids = {
        str(_as_dict(row).get("run_id") or "")
        for row in all_rows
        if str(_as_dict(row).get("status") or "") in {"completed_merged", "completed"}
        and str(_as_dict(row).get("run_id") or "") in repair_run_ids
    }
    verified_repair_run_ids = {
        str(_as_dict(row).get("run_id") or "")
        for row in all_rows
        if _event_ok(row)
        and str(_as_dict(row).get("run_id") or "") in completed_repair_run_ids
        and any(token in _event_text(row) for token in ("verified", "recovered", "healthy"))
    }
    repair_started = bool(repair_run_ids)
    repair_completed = bool(completed_repair_run_ids)
    repair_verified = bool(verified_repair_run_ids)

    proactive_signals = _as_dict(current_gate.get("proactive_signals"))
    proactive_count = _as_int(current_gate.get("proactive_task_count"))
    proactive_detected = proactive_count > 0 or bool(
        _as_list(proactive_signals.get("candidates"))
    )
    workforce_gaps = _as_list(proactive_signals.get("workforce_gaps"))
    workforce_gap_count = _as_int(proactive_signals.get("workforce_gap_count")) or len(
        workforce_gaps
    )
    planned_workforce_remediations = sum(
        1
        for raw_gap in workforce_gaps
        if str(_as_dict(raw_gap).get("employee_id") or "").strip()
        and str(_as_dict(_as_dict(raw_gap).get("remediation")).get("task_id") or "").strip()
        and bool(
            _as_list(
                _as_dict(_as_dict(raw_gap).get("remediation")).get("target_files")
            )
        )
        and _as_dict(_as_dict(raw_gap).get("remediation")).get("closure_event")
        == "later_strict_burnin_receipt_accepted"
        and _as_dict(_as_dict(raw_gap).get("remediation")).get("auto_close") is False
    )
    evolution_implementation_gap = (
        f"执行已生成的 {planned_workforce_remediations} 个员工能力修复工单，"
        "并取得后续严格试运行回执"
        if planned_workforce_remediations > 0
        else "将能力缺口变成可执行实现"
    )
    evolution_history = _as_int(evolution_summary.get("history_count"))
    kb_summary = _as_dict(runtime.get("kb_summary"))
    reusable_knowledge = _first_number(kb_summary, ("fix_count", "pattern_count", "total")) > 0
    proactive_run_ids = {
        str(_as_dict(row).get("run_id") or "")
        for row in all_rows
        if any(token in _event_text(row) for token in ("proactive", "evolution"))
        and str(_as_dict(row).get("run_id") or "")
    }
    proactive_code_runs = {
        str(_as_dict(row).get("run_id") or "")
        for row in all_rows
        if _event_ok(row)
        and "code" in _event_text(row)
        and str(_as_dict(row).get("run_id") or "") in proactive_run_ids
    }
    proactive_qa_runs = {
        str(_as_dict(row).get("run_id") or "")
        for row in all_rows
        if _event_ok(row)
        and "qa" in _event_text(row)
        and str(_as_dict(row).get("run_id") or "") in proactive_run_ids
    }
    evolution_implemented = bool(proactive_code_runs & proactive_qa_runs)
    employee_pack_built = _has_event(all_rows, "employee_pack", "built") or _has_event(
        all_rows, "pack", "registered"
    )
    modstore_deployed = any(_is_strong_modstore_deployment(row) for row in all_rows)
    council_roles = _as_dict(strategic_council.get("roles"))
    council_latest = _as_dict(strategic_council.get("latest_receipt"))
    council_ready = bool(strategic_council.get("ready")) and all(
        _as_dict(council_roles.get(role)).get("status") == expected
        for role, expected in (
            ("persy", "grounded"),
            ("para", "linked"),
            ("retort", "aligned"),
        )
    ) and _as_dict(council_roles.get("retort")).get("engine_available") is True

    founder_gates = [
        ScoreGate("cockpit", "统一驾驶舱", 15, bool(surfaces.get("founder_cockpit")), "管理端已注册创始人驾驶舱", "建立创始人统一驾驶舱", "source_capability"),
        ScoreGate("approval", "审批中心", 10, bool(surfaces.get("approval_center")), "审批中心已对管理员开放", "将审批中心加入管理端并解除路由阻断", "source_capability"),
        ScoreGate("knowledge", "知识库", 15, bool(surfaces.get("knowledge_base")), "Persy 知识库已对管理员开放", "将知识库加入管理端", "source_capability"),
        ScoreGate("employees", "AI 员工真实工作", 15, bool(surfaces.get("ai_employees")) and workforce_ready, f"已排工 {assigned_employees}/{planned}，有回执 {proven_employees}/{planned}，空壳 {shell_employees}", "让至少 80% 编制产生真实运行回执，并清零空壳/无效 handler", "local_runtime"),
        ScoreGate("goals", "Goals", 10, bool(surfaces.get("goals")) and bool(goals), f"目标条目 {int(goals_total)}", "接入可追踪 Goals 与完成率", "deployed_runtime"),
        ScoreGate("loops", "Loops", 15, bool(surfaces.get("loops")) and bool(runtime.get("ok")), f"Loop runtime 在线，最近事件 {runtime.get('latest_event_at') or '未知'}", "接入实时 Loop 账本", "local_runtime"),
        ScoreGate("council", "Persy/Para/Retort 战略三席", 10, council_ready, f"已验证协同回执 {int(_as_int(strategic_council.get('verified_receipt_count')))} 条", "让 Persy 事实、Para Goal/Loop 与 Retort 质疑形成同一可验证回执", "deployment_runtime"),
        ScoreGate("attention", "只看例外", 10, pending_total <= 5 and governance_clear, f"待人工/会议决策 {pending_total}，治理门禁健康", "将待决策压到 5 项内并清除治理 hold", "deployed_runtime"),
    ]

    system_gates = [
        ScoreGate("cron", "定时调度", 10, cron_ok, str(runtime.get("cron") or ""), "注册并启用 7x24 调度", "local_runtime"),
        ScoreGate("fresh", "持续心跳", 10, runtime_fresh, f"最近事件距今 {latest_age:.1f} 小时" if latest_age is not None else "", "最近 6 小时内必须有运行事件", "local_runtime"),
        ScoreGate("provenance", "运行来源可信", 15, runtime_provenance_ok, str(runtime_provenance.get("source") or "verified runtime provenance"), "用干净的精确提交和发布清单重建运行时；不得用心跳绕过来源门禁", "local_runtime"),
        ScoreGate("contract", "运行契约", 10, contract_trusted, str(contract_status.get("detail") or "runtime contract trusted"), "修复管理端与 Loop runtime 契约", "local_runtime"),
        ScoreGate("staffing", "员工真实排工", 15, workforce_assigned and shell_employees == 0, f"已排工 {assigned_employees}/{planned}，空壳 {shell_employees}", "为全员绑定职责、触发器、风险门禁与验收回执", "source_capability"),
        ScoreGate("execution", "无人值守执行", 15, wrote and reviewed and qa_passed, "编写/独立评审/QA 均有成功事件", "跑通编写、独立评审与 QA", "local_runtime"),
        ScoreGate("gate_clear", "自治门禁", 10, gates_clear, "当前 active_gates.ok=true", "清除 active gate 阻塞", "local_runtime"),
        ScoreGate("completed", "连续完成", 15, latest_completed and not has_open_run, str(latest_complete.get("status") or ""), "完成当前运行且不留下悬挂 run", "local_runtime"),
    ]

    customer_gates = [
        ScoreGate("value_ledger", "价值账本", 15, value_ledger_ready, "权威只追加客户价值账本可读", "接入可排除测试、内部与退款记录的权威价值账本", "local_runtime"),
        ScoreGate("paid", "真实付费", 25, production_value_verified, f"第三方校验付费 {paid_count} 笔 / {paid_amount} 分", "取得带第三方交易证明的真实客户付费；测试单不计入", "production_value"),
        ScoreGate("goals", "客户目标", 15, customer_goals > 0, f"客户目标 {customer_goals} 项", "将外部客户目标写入客户价值账本", "deployed_runtime"),
        ScoreGate("delivered", "目标交付", 20, delivered_count > 0, f"不可变产物交付 {delivered_count} 项", "形成与客户目标关联且带制品 SHA-256 的交付回执", "deployed_runtime"),
        ScoreGate("capacity", "交付编制", 10, workforce_assigned and shell_employees == 0, f"已排工 {assigned_employees}/{planned}", "补齐真实任务合同并清除空壳员工", "source_capability"),
        ScoreGate("outcome", "结果而非身份", 15, outcome_verified, f"付费交付闭环 {paid_delivery_count} 项；客户验收 {paid_acceptance_count} 项", "把真实付费关联到不可变系统产出；继续取得客户验收回执", "production_value"),
    ]

    code_gates = [
        ScoreGate("write", "自己写", 15, wrote, "code 员工步骤成功", "触发真实代码实现步骤", "local_runtime"),
        ScoreGate("review", "自己审", 15, reviewed, "独立 review 员工步骤成功", "保留独立评审证据", "local_runtime"),
        ScoreGate("qa", "自己验", 15, qa_passed, "独立 QA 步骤成功", "保留独立 QA 证据", "local_runtime"),
        ScoreGate("merge", "自己合", 20, merged, "账本存在 completed_merged", "让最新合格变更自动合并", "local_runtime"),
        ScoreGate("dispatch", "自己发版", 15, real_deploy_dispatched, f"同链路部署派发 {len(accepted_deploys)} 次", "捕获带 run_id、合并 SHA 与 workflow ID 的 staging 派发回执", "deployment_runtime"),
        ScoreGate("verify", "部署验证", 20, deploy_verified, "production 的 workflow、SHA 与制品摘要均已回读验证", "在同一 run/SHA 上通过 production workflow 与部署身份校验", "deployment_runtime"),
    ]

    fault_gates = [
        ScoreGate("sense", "故障感知", 20, incident_triggered, f"近窗 incident 信号 {incident_count}", "接入真实故障信号", "local_runtime"),
        ScoreGate("triage", "自动分诊", 15, incident_triggered and len(participants) > 0, f"参与员工 {len(participants)}", "将 incident 绑定责任员工", "local_runtime"),
        ScoreGate("repair", "自动修复", 25, repair_started, "incident 已进入代码修复步骤", "从 incident 自动生成并执行修复", "local_runtime"),
        ScoreGate("complete", "修复落地", 20, repair_completed, "incident run 已完成合并", "让 incident run 跨过门禁并落地", "local_runtime"),
        ScoreGate("verify", "恢复验证", 15, repair_verified, "恢复/健康验证已写回 incident run", "自动验证恢复并关联原 incident", "deployment_runtime"),
        ScoreGate("dlq", "死信自愈", 5, dead_letters_healthy, f"未解决 {unresolved_dead_letters} / 已审计处理 {resolved_dead_letters}", "自动重试幂等事件，隔离支付/退款等高影响事件并保留审计", "local_runtime"),
    ]

    evolution_gates = [
        ScoreGate("detect", "发现缺口", 15, proactive_detected, f"主动候选 {proactive_count}", "持续采集质量、性能和业务缺口", "local_runtime"),
        ScoreGate("knowledge", "复用知识", 15, reusable_knowledge, "自进化知识库存在 fix/pattern", "沉淀并复用 fix/pattern", "local_runtime"),
        ScoreGate("implement", "实现能力", 20, evolution_implemented, "代码与 QA 证据齐全", evolution_implementation_gap, "local_runtime"),
        ScoreGate("metrics", "进化度量", 10, evolution_history > 0, f"进化窗口历史 {evolution_history}", "积累至少一个真实进化指标窗口", "local_runtime"),
        ScoreGate("council", "战略三席质疑", 10, council_ready, f"Persy/Para/Retort 回执 {int(_as_int(strategic_council.get('verified_receipt_count')))} 条", "在部署前绑定知识、Goal/Loop、Retort 意图质疑与 veto", "deployment_runtime"),
        ScoreGate("package", "能力打包", 10, employee_pack_built, "能力已构建 employee_pack", "将新能力打包为 employee_pack/Mod", "deployment_runtime"),
        ScoreGate("publish", "部署更新 MODstore", 20, modstore_deployed, "新能力已部署并完成 catalog 安装验证", "把能力包部署到 MODstore，并回读安装与版本身份", "deployment_runtime"),
    ]

    alignment_gates = [
        ScoreGate("audit", "可审计", 15, audit_has_rows, f"权威只追加自治审计记录 {audit_total}", "让真实自治决策持续写入不可变审计账本", "local_runtime"),
        ScoreGate("prohibited", "禁止项零漏放", 25, audit_available and prohibited_clear, "所有 allow 动作均有独立后验异常证据，未发现 prohibited miss", "补齐所有允许动作的独立后验异常覆盖；未知不能当作零漏放", "local_runtime"),
        ScoreGate("veto", "veto 通道", 15, veto_channel_available, f"红线 veto 通道可用，待处理 {veto_pending}", "部署并验证管理员红线 approve/reject/veto 通道", "deployed_runtime"),
        ScoreGate("rare", "低频人工", 20, audit_has_rows and 0 <= veto_rate <= 5, f"veto rate {veto_rate:.2f}%", "积累真实决策样本，并把 veto rate 压到 5% 以内", "deployed_runtime"),
        ScoreGate("governance", "治理健康", 10, governance_clear, str(governance_gate.get("reason") or "governance healthy"), "处理连续治理动作失败", "local_runtime"),
        ScoreGate("council", "独立质疑门", 10, council_ready, "Persy/Para/Retort 三席已在真实部署前共同放行", "把 Retort 质疑与 Persy/Para 执行证据接到 veto 门", "deployment_runtime"),
        ScoreGate("self_policy", "不能自改边界", 5, contract_trusted and audit_available and prohibited_clear, "运行契约可信、审计不可变且禁止项后验覆盖完整", "锁定自治边界并补齐禁止项后验覆盖", "source_capability"),
    ]

    dimensions = [
        _score_dimension(
            dimension_id="founder",
            label="创始人状态",
            target="退出日常运营，只处理战略与少量例外",
            gates=founder_gates,
            hard_cap=(
                65
                if not workforce_ready
                else (
                    80
                    if pending_total > 5 or not governance_clear
                    else (85 if not runtime_provenance_ok else None)
                )
            ),
        ),
        _score_dimension(
            dimension_id="system",
            label="系统状态",
            target="7x24 自运转，无日常人工介入",
            gates=system_gates,
            hard_cap=(
                45
                if not workforce_ready
                else (
                    60
                    if not gates_clear
                    else (85 if not runtime_provenance_ok else None)
                )
            ),
        ),
        _score_dimension(
            dimension_id="customer",
            label="客户状态",
            target="客户为可验证产出付费",
            gates=customer_gates,
            hard_cap=65 if paid_count <= 0 and paid_amount <= 0 else None,
        ),
        _score_dimension(
            dimension_id="code",
            label="代码状态",
            target="自己写、审、验、合、部署并回读验证",
            gates=code_gates,
            hard_cap=65 if not deploy_verified else None,
        ),
        _score_dimension(
            dimension_id="fault",
            label="故障状态",
            target="自己感知、修复、验证",
            gates=fault_gates,
            hard_cap=65 if not repair_verified else None,
        ),
        _score_dimension(
            dimension_id="evolution",
            label="进化状态",
            target="发现缺口、实现能力、部署更新到 MODstore",
            gates=evolution_gates,
            hard_cap=60 if not modstore_deployed else None,
        ),
        _score_dimension(
            dimension_id="alignment",
            label="对齐状态",
            target="知道什么不能做，veto 低频但始终可用",
            gates=alignment_gates,
            hard_cap=65 if not governance_clear else None,
        ),
    ]

    overall = round(sum(item["progress"] for item in dimensions) / len(dimensions))
    attention_items: list[dict[str, Any]] = []
    if local_pending:
        attention_items.append({"kind": "approval", "count": local_pending, "label": "本地审批待处理", "route": "approval-hub"})
    if strategic_pending:
        attention_items.append({"kind": "strategy", "count": strategic_pending, "label": "战略/会议待决策", "route": "founder-autonomy"})
    if not governance_clear:
        attention_items.append({"kind": "governance", "count": 1, "label": str(governance_gate.get("reason") or "自治治理门禁阻塞"), "route": "duty-roster-graph", "query": {"view": "loop"}})
    if not runtime_provenance_ok:
        attention_items.append({"kind": "runtime_provenance", "count": 1, "label": "运行时来源证明未通过", "route": "duty-roster-graph", "query": {"view": "loop"}})
    if has_open_run:
        attention_items.append({"kind": "loop", "count": len(open_run_ids), "label": "当前仍有开放 Loop", "route": "duty-roster-graph", "query": {"view": "loop"}})
    if veto_pending:
        attention_items.append({"kind": "veto", "count": veto_pending, "label": "红线 veto 待处理", "route": "approval-hub"})
    if prohibited_miss:
        attention_items.append({"kind": "alignment", "count": 1, "label": "发现禁止项漏放证据", "route": "approval-hub"})
    unproven_employees = max(0, planned - proven_employees)
    if shell_employees:
        attention_items.append({"kind": "employee_shell", "count": shell_employees, "label": "AI 员工仍是空壳或 handler 无效", "route": "workflow-employee-space"})
    if unproven_employees:
        attention_items.append({"kind": "employee_receipt", "count": unproven_employees, "label": "AI 员工尚无真实运行回执", "route": "workflow-employee-space"})

    return {
        "schema_version": "founder_autonomy_status.v1",
        "generated_at": now.isoformat(),
        "overall_progress": overall,
        "overall_remaining": 100 - overall,
        "target_state": "founder_strategic_only",
        "dimensions": dimensions,
        "attention": {
            "total": sum(_as_int(item.get("count")) for item in attention_items),
            "items": attention_items,
            "human_intervention_rare": pending_total <= 5 and governance_clear and workforce_ready and runtime_provenance_ok,
        },
        "live_summary": {
            "runtime_ok": bool(runtime.get("ok")),
            "runtime_fresh": runtime_fresh,
            "runtime_provenance_ok": runtime_provenance_ok,
            "runtime_provenance_source": runtime_provenance.get("source"),
            "runtime_provenance_reasons": _as_list(runtime_provenance.get("reasons")),
            "latest_event_at": runtime.get("latest_event_at"),
            "latest_complete_status": latest_complete.get("status"),
            "open_run_ids": open_run_ids,
            "milestone_evidence_rows": len(milestone_rows),
            "milestone_evidence_window": _as_dict(evidence.get("milestone_window")),
            "active_gates_ok": gates_clear,
            "blocking_gate_keys": _as_list(active_gates.get("blocking_keys")),
            "governance_ok": governance_clear,
            "governance_summary": _as_dict(governance_gate.get("summary")),
            "planned_employees": planned,
            "registered_employees": registered,
            "assigned_employees": assigned_employees,
            "proven_employees": proven_employees,
            "shell_employees": shell_employees,
            "employee_workforce_ready": workforce_ready,
            "employee_assignment_ratio": _as_float(employee_capability.get("assignment_ratio")),
            "employee_proof_ratio": _as_float(employee_capability.get("proof_ratio")),
            "loop_participants": len(participants),
            "goals_total": int(goals_total),
            "goals_closed": int(goals_closed),
            "customer_goals": customer_goals,
            "customer_deliveries": delivered_count,
            "unproven_customer_deliveries": unproven_delivery_count,
            "paid_delivery_count": paid_delivery_count,
            "paid_acceptance_count": paid_acceptance_count,
            "customer_acceptance_verified": customer_acceptance_verified,
            "customer_value_ledger_ready": value_ledger_ready,
            "customer_value_excluded": customer_value_excluded,
            "knowledge_documents": int(knowledge_documents),
            "knowledge_chunks": int(knowledge_chunks),
            "workforce_capability_gap_count": workforce_gap_count,
            "planned_workforce_remediations": planned_workforce_remediations,
            "paid_count": int(paid_count),
            "paid_amount_cents": int(paid_amount),
            "production_value_verified": production_value_verified,
            "outcome_verified": outcome_verified,
            "veto_rate": veto_rate,
            "autonomy_audit_authoritative": audit_available,
            "autonomy_audit_count": audit_total,
            "prohibited_miss_status": autonomy_audit.get(
                "prohibited_miss_evidence_status"
            ) or ("detected" if prohibited_miss else "unknown"),
            "prohibited_posthoc_coverage_rate": _as_float(
                autonomy_audit.get("posthoc_coverage_rate")
            ),
            "veto_channel_available": veto_channel_available,
            "veto_pending": veto_pending,
            "deploy_attempted": deploy_attempted,
            "real_deploy_dispatched": real_deploy_dispatched,
            "deploy_verified": deploy_verified,
            "accepted_deploy_receipts": len(accepted_deploys),
            "verified_deploy_receipts": len(verified_deploys),
            "employee_autonomy_available": employee_dashboard_ok,
            "dead_letters_healthy": dead_letters_healthy,
            "unresolved_dead_letters": unresolved_dead_letters,
            "resolved_dead_letters": resolved_dead_letters,
            "strategic_council_ready": council_ready,
            "strategic_council_receipts": _as_int(
                strategic_council.get("verified_receipt_count")
            ),
            "strategic_council_roles": council_roles,
            "strategic_council_latest": council_latest,
        },
        "truth_domains": {
            "source_capability": {"available": True, "label": "当前源码能力"},
            "local_runtime": {"available": bool(runtime.get("ok")), "label": "本机实际运行"},
            "deployment_runtime": {"available": real_deploy_dispatched or deploy_attempted, "label": "部署派发/验证"},
            "production_value": {"available": outcome_verified, "label": "真实客户付费与价值"},
        },
    }


def build_public_founder_autonomy_projection(
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Return the public-safe subset used by the official World Will page.

    Internal run ids, approval subjects, source paths, error messages and
    finance amounts intentionally never cross this boundary.  The public page
    receives the same calculated progress values as the founder cockpit, plus
    only coarse, non-sensitive proof flags.
    """

    dimensions: list[dict[str, Any]] = []
    for raw in _as_list(snapshot.get("dimensions")):
        item = _as_dict(raw)
        gaps = _as_list(item.get("gaps"))
        next_gap = _as_dict(gaps[0]).get("label") if gaps else "继续积累运行证据"
        dimensions.append(
            {
                "id": str(item.get("id") or ""),
                "label": str(item.get("label") or ""),
                "target": str(item.get("target") or ""),
                "progress": _as_int(item.get("progress")),
                "remaining": _as_int(item.get("remaining")),
                "status": str(item.get("status") or "early"),
                "status_label": str(item.get("status_label") or "能力早期"),
                "passed_gate_count": _as_int(item.get("passed_gate_count")),
                "total_gate_count": _as_int(item.get("total_gate_count")),
                "next_gap": str(next_gap or "继续积累运行证据"),
            }
        )

    live = _as_dict(snapshot.get("live_summary"))
    truth = _as_dict(snapshot.get("truth_domains"))
    public_truth = {
        str(key): {
            "label": str(_as_dict(value).get("label") or key),
            "available": bool(_as_dict(value).get("available")),
        }
        for key, value in truth.items()
    }
    return {
        "schema": "xcagi.public_founder_autonomy/v1",
        "generated_at": str(snapshot.get("generated_at") or datetime.now(UTC).isoformat()),
        "readonly": True,
        "overall_progress": _as_int(snapshot.get("overall_progress")),
        "overall_remaining": _as_int(snapshot.get("overall_remaining")),
        "target_state": "founder_strategic_only",
        "dimensions": dimensions,
        "human_intervention_rare": bool(
            _as_dict(snapshot.get("attention")).get("human_intervention_rare")
        ),
        "proof": {
            "runtime_fresh": bool(live.get("runtime_fresh")),
            "runtime_provenance_ok": bool(live.get("runtime_provenance_ok")),
            "active_gates_ok": bool(live.get("active_gates_ok")),
            "governance_ok": bool(live.get("governance_ok")),
            "deploy_verified": bool(live.get("deploy_verified")),
            "paid_value_verified": bool(live.get("production_value_verified")),
            "paid_delivery_verified": bool(live.get("outcome_verified")),
            "customer_acceptance_verified": bool(
                live.get("customer_acceptance_verified")
            ),
            "employee_workforce_ready": bool(live.get("employee_workforce_ready")),
        },
        "truth_domains": public_truth,
        "note": "官网仅展示脱敏后的证据评分；完整门禁、审批与 veto 细节只在管理端可见。",
    }


def _public_projection_targets(repo_root: Path | None = None) -> list[Path]:
    root = repo_root
    if root is None:
        configured = str(os.environ.get("XCMAX_MONOREPO_ROOT") or "").strip()
        root = Path(configured).expanduser().resolve() if configured else Path(__file__).resolve().parents[3]
    company_root = root / "成都修茈科技有限公司"
    targets = [
        company_root / "download-founder-autonomy.json",
        company_root / "MODstore_deploy" / "market" / "public" / "download-founder-autonomy.json",
    ]
    configured_live_roots = [
        item.strip()
        for item in str(os.environ.get("XCMAX_PUBLIC_SITE_LIVE_ROOTS") or "").split(",")
        if item.strip()
    ]
    if not configured_live_roots:
        configured_live_roots = ["/root/成都修茈科技有限公司"]
    for raw in configured_live_roots:
        try:
            live_root = Path(raw).expanduser().resolve()
        except OSError:
            continue
        if live_root.is_dir():
            targets.append(live_root / "download-founder-autonomy.json")
    return list(dict.fromkeys(targets))


def write_public_founder_autonomy_projection(
    snapshot: dict[str, Any],
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Atomically publish the sanitized scorecard to official-site targets."""

    payload = build_public_founder_autonomy_projection(snapshot)
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    written: list[str] = []
    errors: list[str] = []
    for target in _public_projection_targets(repo_root):
        if not target.parent.is_dir():
            continue
        tmp = target.with_suffix(f"{target.suffix}.tmp")
        try:
            tmp.write_text(body, encoding="utf-8")
            tmp.replace(target)
            written.append(str(target))
        except OSError as exc:
            errors.append(f"{target.name}:{exc.__class__.__name__}")
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
    return {
        "ok": bool(written) and not errors,
        "written": written,
        "errors": errors,
        "payload": payload,
    }


__all__ = [
    "ScoreGate",
    "build_founder_autonomy_snapshot",
    "build_public_founder_autonomy_projection",
    "write_public_founder_autonomy_projection",
]
