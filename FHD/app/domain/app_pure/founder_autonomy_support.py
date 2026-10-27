"""Shared scoring primitives for the founder-autonomy application service."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
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
        and data.get("market_listing_verified") is True
        and _as_int(data.get("market_catalog_item_id")) > 0
        and data.get("installability_verified") is True
        and data.get("runtime_contract_verified") is True
        and data.get("strategic_council_verified") is True
        and str(data.get("environment") or "").lower() in {"staging", "production"}
        and str(data.get("package_id") or "").strip()
        and str(data.get("version") or "").strip()
        and _PACKAGE_SHA_RE.fullmatch(str(data.get("package_sha256") or "").strip().lower())
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


def _correlated_deploy_evidence(
    rows: list[Any],
) -> tuple[set[tuple[str, str, str, str]], list[dict[str, Any]]]:
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


def _build_dimensions(
    *,
    founder_gates: list[ScoreGate],
    system_gates: list[ScoreGate],
    customer_gates: list[ScoreGate],
    code_gates: list[ScoreGate],
    fault_gates: list[ScoreGate],
    evolution_gates: list[ScoreGate],
    alignment_gates: list[ScoreGate],
    workforce_ready: bool,
    founder_workforce_ready: bool,
    pending_total: int,
    governance_clear: bool,
    runtime_provenance_ok: bool,
    gates_clear: bool,
    paid_count: int,
    paid_amount: int,
    deploy_verified: bool,
    repair_verified: bool,
    modstore_deployed: bool,
) -> list[dict[str, Any]]:
    return [
        _score_dimension(
            dimension_id="founder",
            label="创始人状态",
            target="退出日常运营，只处理战略与少量例外",
            gates=founder_gates,
            hard_cap=(
                65
                if not founder_workforce_ready
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
                else (60 if not gates_clear else (85 if not runtime_provenance_ok else None))
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


def _build_attention_items(
    *,
    local_pending: int,
    strategic_pending: int,
    governance_clear: bool,
    governance_reason: str,
    runtime_provenance_ok: bool,
    open_run_ids: list[str],
    veto_pending: int,
    prohibited_miss: bool,
    planned: int,
    proven_employees: int,
    shell_employees: int,
    retort_open: int = 0,
    retort_critical: int = 0,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if local_pending:
        items.append(
            {
                "kind": "approval",
                "count": local_pending,
                "label": "本地审批待处理",
                "route": "approval-hub",
            }
        )
    if retort_open:
        label = "Retort 待澄清（Boss 问答）"
        if retort_critical:
            label = f"Retort 待澄清（{retort_critical} 条即将超时）"
        items.append(
            {
                "kind": "retort_clarification",
                "count": retort_open,
                "label": label,
                "route": "employee-autonomy",
                "query": {"tab": "questions"},
            }
        )
    if strategic_pending:
        items.append(
            {
                "kind": "strategy",
                "count": strategic_pending,
                "label": "战略/会议待决策",
                "route": "founder-autonomy",
            }
        )
    if not governance_clear:
        items.append(
            {
                "kind": "governance",
                "count": 1,
                "label": governance_reason or "自治治理门禁阻塞",
                "route": "duty-roster-graph",
                "query": {"view": "loop"},
            }
        )
    if not runtime_provenance_ok:
        items.append(
            {
                "kind": "runtime_provenance",
                "count": 1,
                "label": "运行时来源证明未通过",
                "route": "duty-roster-graph",
                "query": {"view": "loop"},
            }
        )
    if open_run_ids:
        items.append(
            {
                "kind": "loop",
                "count": len(open_run_ids),
                "label": "当前仍有开放 Loop",
                "route": "duty-roster-graph",
                "query": {"view": "loop"},
            }
        )
    if veto_pending:
        items.append(
            {
                "kind": "veto",
                "count": veto_pending,
                "label": "红线 veto 待处理",
                "route": "approval-hub",
            }
        )
    if prohibited_miss:
        items.append(
            {
                "kind": "alignment",
                "count": 1,
                "label": "发现禁止项漏放证据",
                "route": "approval-hub",
            }
        )
    unproven_employees = max(0, planned - proven_employees)
    if shell_employees:
        items.append(
            {
                "kind": "employee_shell",
                "count": shell_employees,
                "label": "AI 员工仍是空壳或 handler 无效",
                "route": "workflow-employee-space",
            }
        )
    if unproven_employees:
        items.append(
            {
                "kind": "employee_receipt",
                "count": unproven_employees,
                "label": "AI 员工尚无真实运行回执",
                "route": "workflow-employee-space",
            }
        )
    return items
