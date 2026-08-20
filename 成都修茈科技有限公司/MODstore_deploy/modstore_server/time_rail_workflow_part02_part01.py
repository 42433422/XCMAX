# mypy: disable-error-code="union-attr, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.time_rail_workflow")


def collect_node_runtime_status(
    *, node_ids: _facade().Optional[_facade().List[str]] = None
) -> _facade().Dict[str, _facade().Any]:
    """聚合全部（或指定）节点的 runtime 状态。"""
    from modstore_server.time_rail_runtime import all_node_records

    graph = _facade().load_workflow_graph()
    graph_nodes = {
        str(n.get("id")): {
            "label": str(n.get("label") or ""),
            "kind": str(n.get("kind") or ""),
            "phase": str(n.get("phase") or ""),
        }
        for n in graph.get("nodes") or []
        if n.get("id")
    }
    all_ids = list(graph_nodes.keys())
    if node_ids:
        wanted = {str(x).strip() for x in node_ids if str(x).strip()}
        ids = list(wanted)
    else:
        ids = all_ids
    persisted = all_node_records()
    derived = _facade()._derive_from_sources()
    maintenance_by_node = _facade()._maintenance_backlog_by_node()
    guard_global = bool(derived.get("DRFAIL", {}).get("guard_active"))
    nodes: _facade().Dict[str, _facade().Dict[str, _facade().Any]] = {}
    for nid in ids:
        row = persisted.get(nid) or derived.get(nid)
        graph_meta = graph_nodes.get(nid) or {}
        if row:
            detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
            if not detail and isinstance(row.get("meta"), dict):
                detail = row.get("meta") or {}
            evidence = row.get("evidence") if isinstance(row.get("evidence"), list) else []
            proof_status = row.get("proof_status")
            if not proof_status and (detail.get("shadow") or detail.get("dry_run")):
                proof_status = "shadow_observed"
            nodes[nid] = {
                "node_id": nid,
                "label": graph_meta.get("label", ""),
                "kind": graph_meta.get("kind", ""),
                "phase": graph_meta.get("phase", ""),
                "last_run": row.get("last_run"),
                "ok": row.get("ok"),
                "guard_active": bool(row.get("guard_active"))
                or (guard_global and nid in ("RT", "DRFAIL", "DRPROBE")),
                "source": row.get("source") or "",
                "detail": detail,
                "observed": bool(row.get("observed"))
                or bool(row.get("last_run") or row.get("source") or row.get("ok") is not None),
                "proof_status": proof_status
                or (
                    "proved_ok"
                    if row.get("ok") is True
                    else "proved_failed" if row.get("ok") is False else "observed"
                ),
                "evidence": evidence
                or [
                    {
                        "source": row.get("source") or "time_rail_runtime",
                        "last_run": row.get("last_run"),
                        "ok": row.get("ok"),
                        "detail": detail,
                    }
                ],
                "evidence_count": int(
                    row.get("evidence_count") or (len(evidence) if evidence else 1)
                ),
                "missing_evidence": (
                    row.get("missing_evidence")
                    if isinstance(row.get("missing_evidence"), list)
                    else []
                ),
                "observable": True,
            }
        else:
            queued = maintenance_by_node.get(nid)
            if queued:
                nodes[nid] = {
                    **_facade()._node_status_shell(
                        nid,
                        last_run=_facade()._iso_or_none(queued.get("at")),
                        ok=None,
                        source="six_line_digest_backlog",
                        detail={
                            "route_id": queued.get("route_id"),
                            "priority": queued.get("priority"),
                            "dispatch_line": queued.get("dispatch_line"),
                            "employee_id": queued.get("employee_id"),
                            "task_brief": queued.get("task_brief"),
                        },
                        observed=True,
                        proof_status="maintenance_queued",
                    ),
                    "label": graph_meta.get("label", ""),
                    "kind": graph_meta.get("kind", ""),
                    "phase": graph_meta.get("phase", ""),
                    "observable": True,
                }
            else:
                nodes[nid] = {
                    **_facade()._node_status_shell(nid),
                    "label": graph_meta.get("label", ""),
                    "kind": graph_meta.get("kind", ""),
                    "phase": graph_meta.get("phase", ""),
                    "observable": True,
                }
    observed_ids = [nid for (nid, row) in nodes.items() if row.get("observed")]
    runtime_evidence_ids = [
        nid for (nid, row) in nodes.items() if int(row.get("evidence_count") or 0) > 0
    ]
    maintenance_queued_ids = [
        nid
        for (nid, row) in nodes.items()
        if str(row.get("proof_status") or "") == "maintenance_queued"
    ]
    proved_ids = [
        nid
        for (nid, row) in nodes.items()
        if str(row.get("proof_status") or "")
        in (
            "proved_ok",
            "proved_failed",
            "guard_active",
            "decision_true",
            "decision_false",
            "shadow_observed",
            "planned",
            "decision_not_taken",
            "maintenance_queued",
        )
    ]
    missing_nodes = [
        {
            "node_id": nid,
            "label": row.get("label") or "",
            "phase": row.get("phase") or "",
            "kind": row.get("kind") or "",
            "reason": "; ".join(row.get("missing_evidence") or []) or "missing runtime evidence",
        }
        for (nid, row) in nodes.items()
        if not row.get("observed")
    ]
    maintenance_items = [
        {
            "kind": "time_rail_missing_evidence",
            "priority": "P1" if row.get("phase") in ("t1", "t2", "t2b", "t3") else "P2",
            "node_id": row["node_id"],
            "title": f"补齐时间轨节点证据: {row.get('label') or row['node_id']}",
            "suggested_owner": "daily-orchestrator",
            "status": "open",
            "reason": row.get("reason"),
        }
        for row in missing_nodes
    ]
    coverage = {
        "total_nodes": len(ids),
        "status_nodes": len(nodes),
        "observable_nodes": len(nodes),
        "observed_nodes": len(observed_ids),
        "proved_nodes": len(proved_ids),
        "runtime_evidence_nodes": len(runtime_evidence_ids),
        "maintenance_queued_nodes": len(maintenance_queued_ids),
        "state_classified_nodes": len(nodes),
        "missing_evidence_nodes": len(missing_nodes),
        "status_coverage_pct": round(len(nodes) / len(ids) * 100.0, 1) if ids else 100.0,
        "observable_coverage_pct": round(len(nodes) / len(ids) * 100.0, 1) if ids else 100.0,
        "observed_coverage_pct": round(len(observed_ids) / len(ids) * 100.0, 1) if ids else 100.0,
        "proved_coverage_pct": round(len(proved_ids) / len(ids) * 100.0, 1) if ids else 100.0,
        "runtime_evidence_coverage_pct": (
            round(len(runtime_evidence_ids) / len(ids) * 100.0, 1) if ids else 100.0
        ),
        "maintenance_queued_coverage_pct": (
            round(len(maintenance_queued_ids) / len(ids) * 100.0, 1) if ids else 0.0
        ),
        "state_classified_coverage_pct": round(len(nodes) / len(ids) * 100.0, 1) if ids else 100.0,
    }
    return {
        "contract_version": _facade().STATUS_CONTRACT_VERSION,
        "version": graph.get("version"),
        "graph_schema": graph.get("schema"),
        "graph_path": str(_facade().graph_json_path()),
        "checked_at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        "backup_guard_active": guard_global,
        "refresh_after_seconds": 15,
        "coverage": coverage,
        "missing_evidence": missing_nodes,
        "maintenance_backlog": maintenance_items,
        "nodes": nodes,
    }


def sync_missing_evidence_backlog(*, limit: int = 32) -> _facade().Dict[str, _facade().Any]:
    """把缺证节点写入事件轨 digest backlog，让次日 Vibe 自动生成维护任务。"""
    status = _facade().collect_node_runtime_status()
    missing = list(status.get("missing_evidence") or [])[: max(1, int(limit))]
    if not missing:
        return {"ok": True, "added": 0, "skipped": 0, "reason": "no_missing_evidence"}
    try:
        from modstore_server.six_line_event_router import (
            append_digest_backlog,
            read_digest_backlog_entries,
        )
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("time_rail: event backlog unavailable")
        return {"ok": False, "error": str(exc)}
    existing = {
        str(row.get("node_id") or "")
        for row in read_digest_backlog_entries()
        if str(row.get("source") or "") == "time-rail-observability"
    }
    added: _facade().List[_facade().Dict[str, _facade().Any]] = []
    skipped = 0
    for row in missing:
        nid = str(row.get("node_id") or "").strip()
        if not nid or nid in existing:
            skipped += 1
            continue
        phase = str(row.get("phase") or "")
        priority = "P1" if phase in ("t1", "t2", "t2b", "t3") else "P2"
        entry = {
            "source": "time-rail-observability",
            "route_id": "time_rail_missing_evidence",
            "trigger": "time_rail_maintenance",
            "six_line": "prod_software",
            "line_step": "P8",
            "dispatch_line": "P-S",
            "list_kind": "patches",
            "priority": priority,
            "employee_id": "daily-orchestrator",
            "node_id": nid,
            "summary": f"补齐时间轨节点证据: {row.get('label') or nid}",
            "task_brief": f"时间轨节点 `{nid}` 当前缺少 runtime 证据。 节点: {row.get('label') or nid}；phase={phase or 'unknown'}；原因: {row.get('reason') or 'missing runtime evidence'}。 请补充 record_node_run 或可验证的派生证据，使该节点进入 observed/proved 状态。",
        }
        path = append_digest_backlog(entry)
        added.append({"node_id": nid, "path": path})
        existing.add(nid)
    return {
        "ok": True,
        "added": len(added),
        "skipped": skipped,
        "total_missing": len(status.get("missing_evidence") or []),
        "added_items": added,
    }


def graph_api_payload() -> _facade().Dict[str, _facade().Any]:
    graph = _facade().load_workflow_graph()
    return {
        "ok": True,
        "version": graph.get("version"),
        "schema": graph.get("schema"),
        "center_id": graph.get("center_id"),
        "phase_colors": graph.get("phase_colors") or {},
        "compact_ids": graph.get("compact_ids") or [],
        "xrail_edge_keys": graph.get("xrail_edge_keys") or [],
        "nodes": graph.get("nodes") or [],
        "edges": graph.get("edges") or [],
        "source": graph.get("source"),
        "path": str(_facade().graph_json_path()),
    }
