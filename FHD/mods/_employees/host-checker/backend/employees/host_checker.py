"""Deterministic host-contract receipt auditor; never probes a live host."""

from __future__ import annotations

from typing import Any


def run(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    snapshot = payload.get("host_snapshot")
    issues: list[dict[str, str]] = []
    if not isinstance(snapshot, dict):
        issues.append({"code": "missing_host_snapshot", "detail": "host_snapshot is required"})
        snapshot = {}
    if snapshot.get("loaded") is not True:
        issues.append(
            {"code": "pack_not_loaded", "detail": "supplied snapshot does not prove loading"}
        )
    routes = snapshot.get("routes") if isinstance(snapshot.get("routes"), list) else []
    if not routes or any(
        str(item.get("status") or "") != "ready" for item in routes if isinstance(item, dict)
    ):
        issues.append(
            {"code": "route_contract_incomplete", "detail": "all supplied routes must be ready"}
        )
    dependencies = (
        snapshot.get("dependencies") if isinstance(snapshot.get("dependencies"), list) else []
    )
    if not dependencies or any(
        str(item.get("status") or "") != "available"
        for item in dependencies
        if isinstance(item, dict)
    ):
        issues.append(
            {
                "code": "dependency_contract_incomplete",
                "detail": "all supplied dependencies must be available",
            }
        )
    approved = not issues
    return {
        "ok": True,
        "status": "approved" if approved else "needs_review",
        "summary": "supplied host contract is complete"
        if approved
        else "supplied host contract has gaps",
        "issues": issues,
        "loaded": snapshot.get("loaded") is True,
        "routes_checked": len(routes),
        "dependencies_checked": len(dependencies),
        "evidence": ["fixture_only", "no_host_probe", "no_network_access"],
        "read_only": True,
        "side_effects": [],
    }


__all__ = ["run"]
