# ruff: noqa
"""Candidate selection and planning for duty-workforce burn-in."""
from __future__ import annotations
import importlib
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional
from modstore_server.duty_workforce_burnin_policy import _payload_sha256, assess_burn_in_eligibility
from modstore_server.duty_workforce_contracts import (
    load_reviewed_duty_manifest,
    workforce_contract_map,
)
from modstore_server.duty_workforce_receipts import (
    fresh_accepted_receipt_identities,
    recent_attempt_manifest_shas,
)
from modstore_server.models import EmployeeExecutionMetric, get_session_factory


def _facade():
    return importlib.import_module("modstore_server.duty_workforce_burnin")


def _recent_attempt_ids(cooldown_hours: int, now: datetime) -> set[str]:
    cutoff = now.replace(tzinfo=None) - timedelta(hours=max(1, cooldown_hours))
    sf = get_session_factory()
    with sf() as session:
        rows = (
            session.query(EmployeeExecutionMetric.employee_id)
            .filter(
                EmployeeExecutionMetric.task.like("[duty-burn-in:%"),
                EmployeeExecutionMetric.created_at >= cutoff,
            )
            .distinct()
            .all()
        )
    return {str(row[0]) for row in rows if str(row[0] or "").strip()}


def _load_manifest(employee_id: str) -> Dict[str, Any]:
    return load_reviewed_duty_manifest(employee_id)


def _candidate_task(employee_id: str, contract: Dict[str, Any], marker: str) -> str:
    acceptance = [
        str(item).strip() for item in contract.get("acceptance") or [] if str(item).strip()
    ]
    return f"{marker} 执行一次岗位只读巡检回执。岗位：{employee_id}。任务：{str(contract.get('mission') or '').strip()}。必须至少调用一次工作区只读工具获取真实证据；禁止写文件、运行命令、访问外网、发消息、转交任务、创建变更或执行任何业务副作用。验收要求：{'；'.join(acceptance) or '输出可追溯证据'}。认知结果与最终答案都必须使用 JSON 对象，包含 status=success、不少于 10 个字的 summary 和 evidence 字段，并且只能根据工具真实结果下结论；缺证据就明确失败，不得伪造回执。"


def _candidate_direct_task(employee_id: str, marker: str) -> str:
    """Describe only the reviewed deterministic sub-capability being proven."""
    return f"{marker} 执行一次岗位确定性只读子能力回执。岗位：{employee_id}。仅使用 manifest 中已审查的 burn_in_fixture 验证声明的输入输出契约；不得声称完整岗位的写入、构建、派发、发布或外联职责已经执行。输出必须由 direct_python 入口产生，并包含 status=success/approved、不少于 10 个字的 summary、evidence、read_only=true 和 side_effects=[]。"


def build_burn_in_plan(
    *,
    window_hours: int = 24,
    limit: Optional[int] = None,
    now: Optional[datetime] = None,
    _contracts: Optional[Dict[str, Dict[str, Any]]] = None,
    _manifests: Optional[Dict[str, Dict[str, Any]]] = None,
    _proven_ids: Optional[Iterable[str]] = None,
    _recent_ids: Optional[Iterable[str]] = None,
    _recent_manifest_shas: Optional[Dict[str, Iterable[str]]] = None,
) -> Dict[str, Any]:
    """Build a dry plan without invoking an employee or producing a receipt."""
    observed_at = now or _facade().datetime.now(_facade().timezone.utc)
    limits = _facade().burn_in_limits()
    max_candidates = max(
        1, min(int(limit or limits["max_candidates"]), limits["max_candidates"], 8)
    )
    contracts = _contracts if _contracts is not None else workforce_contract_map()
    proven_override = {str(item) for item in _proven_ids} if _proven_ids is not None else None
    accepted_receipts = (
        {}
        if proven_override is not None
        else fresh_accepted_receipt_identities(
            _facade().burn_in_audit_path(), window_hours, observed_at
        )
    )
    recent = (
        {str(item) for item in _recent_ids}
        if _recent_ids is not None
        else _facade()._recent_attempt_ids(limits["cooldown_hours"], observed_at)
    )
    recent_manifest_shas = (
        {
            str(employee_id): {str(value).strip().lower() for value in values if str(value).strip()}
            for (employee_id, values) in _recent_manifest_shas.items()
        }
        if _recent_manifest_shas is not None
        else recent_attempt_manifest_shas(
            _facade().burn_in_audit_path(), limits["cooldown_hours"], observed_at
        )
    )
    manifests = _manifests or {}
    candidates: list[Dict[str, Any]] = []
    skipped: list[Dict[str, str]] = []
    fresh_proven_count = 0
    for employee_id in sorted(contracts):
        contract = dict(contracts[employee_id] or {})
        contract.setdefault("employee_id", employee_id)
        try:
            manifest = manifests.get(employee_id) or _facade()._load_manifest(employee_id)
        except Exception as exc:
            skipped.append(
                {"employee_id": employee_id, "reason": f"manifest_unavailable:{type(exc).__name__}"}
            )
            continue
        manifest_sha256 = _facade()._payload_sha256(manifest)
        contract_sha256 = _facade()._payload_sha256(contract)
        has_fresh_proof = (
            employee_id in proven_override
            if proven_override is not None
            else (manifest_sha256, contract_sha256) in accepted_receipts.get(employee_id, set())
        )
        if has_fresh_proof:
            fresh_proven_count += 1
            skipped.append({"employee_id": employee_id, "reason": "fresh_receipt_exists"})
            continue
        if employee_id in recent:
            attempted_shas = recent_manifest_shas.get(employee_id) or set()
            if not attempted_shas or manifest_sha256 in attempted_shas:
                skipped.append({"employee_id": employee_id, "reason": "attempt_cooldown"})
                continue
        eligibility = _facade().assess_burn_in_eligibility(employee_id, contract, manifest)
        if eligibility.get("eligible") is not True:
            skipped.append(
                {"employee_id": employee_id, "reason": str(eligibility.get("reason") or "blocked")}
            )
            continue
        candidates.append(
            {
                "employee_id": employee_id,
                "risk_level": str(eligibility.get("risk_level") or ""),
                "mode": str(contract.get("mode") or ""),
                "mission": str(contract.get("mission") or ""),
                "acceptance": list(contract.get("acceptance") or []),
                "handlers": list(eligibility.get("handlers") or []),
                "capability_handlers": list(eligibility.get("capability_handlers") or []),
                "manifest_source": "reviewed_duty_ssot",
                "manifest_sha256": manifest_sha256,
                "contract_sha256": contract_sha256,
                "forced_read_only": True,
                "burn_in_fixture": dict(eligibility.get("burn_in_fixture") or {}),
                "prohibited_semantics_fixture_override": bool(
                    eligibility.get("prohibited_semantics_fixture_override")
                ),
                "high_risk_fixture_only": bool(eligibility.get("high_risk_fixture_only")),
            }
        )
    selected = candidates[:max_candidates]
    deferred = candidates[max_candidates:]
    if deferred:
        skipped.extend(
            ({"employee_id": item["employee_id"], "reason": "per_run_limit"} for item in deferred)
        )
    reason_counts = Counter((item["reason"].split(":", 1)[0] for item in skipped))
    return {
        "ok": True,
        "dry_run": True,
        "execution_enabled": _facade().burn_in_execution_enabled(),
        "observed_at": observed_at.isoformat(),
        "window_hours": max(1, int(window_hours)),
        "planned_count": len(contracts),
        "fresh_proven_count": fresh_proven_count,
        "candidate_count_before_limit": len(candidates),
        "max_eventual_new_receipts": len(candidates),
        "selected_count": len(selected),
        "estimated_new_receipts": len(selected),
        "candidates": selected,
        "skipped": skipped,
        "skip_reason_counts": dict(sorted(reason_counts.items())),
        "limits": limits,
        "safety": {
            "forced_read_only": True,
            "external_network": False,
            "external_messages": False,
            "handoff": False,
            "change_requests": False,
            "high_risk_read_only_direct": any(
                (item.get("high_risk_fixture_only") for item in selected)
            ),
            "medium_risk_read_only_direct": any(
                (
                    item.get("risk_level") == "medium"
                    and item.get("capability_handlers") == ["direct_python"]
                    for item in selected
                )
            ),
            "medium_or_high_risk_side_effects": False,
            "prohibited_semantics_fixture_override": any(
                (item.get("prohibited_semantics_fixture_override") for item in selected)
            ),
            "payment_release_delete_roles": False,
            "generic_shells_count_as_receipts": False,
        },
    }
