from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_production_recovery_drill(project: str | Path, *, output: str | Path = "") -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    scenarios = [
        _scenario("readonly_degradation", root / "docs" / "retort_pr_readonly_degradation_probe.json", _readonly_recovered),
        _scenario("low_permission_write_denied", root / "docs" / "retort_pr_low_permission_probe.json", _low_permission_recovered),
        _scenario("sandbox_write_rollback", root / "docs" / "retort_pr_publish_sandbox.json", _sandbox_recovered),
        _scenario("employee_gate_failure_rollback", root / "docs" / "retort_employee_patch_closure.json", _patch_recovered),
        _scenario("quality_gate_recovery", root / "docs" / "retort_quality_gate_bundle.json", _quality_recovered),
    ]
    recovered = [item for item in scenarios if item["recovered"]]
    summary = {
        "scenario_count": len(scenarios),
        "recovered_count": len(recovered),
        "all_recovered": len(recovered) == len(scenarios),
        "real_network_denial_verified": any(item["name"] == "low_permission_write_denied" and item["real_network"] and item["recovered"] for item in scenarios),
        "rollback_scenario_count": sum(1 for item in scenarios if item["rollback_verified"]),
        "degradation_scenario_count": sum(1 for item in scenarios if item["degraded_without_write"]),
    }
    result = {
        "status": "ready" if summary["all_recovered"] and summary["real_network_denial_verified"] else "needs_more_evidence",
        "project": str(root),
        "summary": summary,
        "scenarios": scenarios,
        "evidence": {
            "style": "production_fault_injection_recovery_matrix",
            "source_reports": [item["report"] for item in scenarios],
            "no_secret_material": True,
        },
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _scenario(name: str, path: Path, checker: Any) -> dict[str, Any]:
    payload = _read_json(path)
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
    recovered = checker(payload)
    return {
        "name": name,
        "report": str(path),
        "status": str(payload.get("status") or ""),
        "recovered": recovered,
        "real_network": bool(evidence.get("real_network")),
        "rollback_verified": bool(summary.get("rollback_verified") or summary.get("failure_case_rolled_back") or summary.get("all_expected_outcomes_verified")),
        "degraded_without_write": bool(summary.get("degraded_without_write")),
        "live_github_write": bool(summary.get("live_github_write")),
    }


def _readonly_recovered(payload: dict[str, Any]) -> bool:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return str(payload.get("status") or "") == "read_only_degraded" and bool(summary.get("degraded_without_write"))


def _low_permission_recovered(payload: dict[str, Any]) -> bool:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
    return str(payload.get("status") or "") == "permission_denied_degraded" and bool(summary.get("permission_denied")) and bool(evidence.get("real_network"))


def _sandbox_recovered(payload: dict[str, Any]) -> bool:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return bool(summary.get("created_comment_count")) and bool(summary.get("rollback_verified"))


def _patch_recovered(payload: dict[str, Any]) -> bool:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return bool(summary.get("all_expected_outcomes_verified")) and int(summary.get("unexpected_gate_failure_count") or 0) == 0


def _quality_recovered(payload: dict[str, Any]) -> bool:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return bool(summary.get("all_gates_passed"))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
