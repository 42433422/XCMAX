# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.time_rail_workflow")


def _repo_root() -> _facade().Path:
    mono = (_facade().os.environ.get("XCMAX_MONOREPO_ROOT") or "").strip()
    if mono:
        return _facade().Path(mono).expanduser().resolve()
    try:
        from modstore_server.integrations.ops_action_handlers import repo_root

        return repo_root()
    except Exception:
        return _facade().Path(__file__).resolve().parents[3]


def graph_json_path() -> _facade().Path:
    env = (_facade().os.environ.get("MODSTORE_TIME_RAIL_GRAPH_JSON") or "").strip()
    if env:
        return _facade().Path(env).expanduser().resolve()
    candidates = [
        _facade()._repo_root() / "FHD" / "config" / "time_rail_workflow_graph.json",
        _facade()._repo_root() / "docs" / "xcagi-dashboard" / "time_rail_workflow_graph.json",
        _facade().Path(__file__).resolve().parents[3]
        / "FHD"
        / "config"
        / "time_rail_workflow_graph.json",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return candidates[0]


def load_workflow_graph(
    *, path: _facade().Optional[_facade().Path] = None
) -> _facade().Dict[str, _facade().Any]:
    p = path or _facade().graph_json_path()
    if not p.is_file():
        raise FileNotFoundError(f"time_rail workflow graph missing: {p}")
    doc = _facade().json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("time_rail workflow graph must be a JSON object")
    return doc


def _iso_or_none(value: _facade().Any) -> _facade().Optional[str]:
    if value is None:
        return None
    if isinstance(value, _facade().datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=_facade().timezone.utc)
        return value.isoformat()
    s = str(value).strip()
    return s or None


def _node_status_shell(
    node_id: str,
    *,
    last_run: _facade().Optional[str] = None,
    ok: _facade().Optional[bool] = None,
    guard_active: bool = False,
    source: str = "",
    detail: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    observed: _facade().Optional[bool] = None,
    proof_status: _facade().Optional[str] = None,
    evidence: _facade().Optional[_facade().List[_facade().Dict[str, _facade().Any]]] = None,
    missing_evidence: _facade().Optional[_facade().List[str]] = None,
) -> _facade().Dict[str, _facade().Any]:
    ev = list(evidence or [])
    if source:
        ev.append({"source": source, "last_run": last_run, "ok": ok, "detail": dict(detail or {})})
    is_observed = (
        bool(observed)
        if observed is not None
        else bool(ev or last_run or source or (ok is not None))
    )
    if proof_status is None:
        if guard_active:
            proof_status = "guard_active"
        elif ok is True:
            proof_status = "proved_ok"
        elif ok is False:
            proof_status = "proved_failed"
        elif is_observed:
            proof_status = "observed"
        else:
            proof_status = "missing_evidence"
    missing = list(missing_evidence or [])
    if not is_observed and (not missing):
        missing.append("no runtime evidence recorded for this workflow node")
    return {
        "node_id": node_id,
        "last_run": last_run,
        "ok": ok,
        "guard_active": bool(guard_active),
        "source": source or "",
        "detail": dict(detail or {}),
        "observed": is_observed,
        "proof_status": proof_status,
        "evidence": ev,
        "evidence_count": len(ev),
        "missing_evidence": missing,
    }


def _json_obj(raw: _facade().Any) -> _facade().Dict[str, _facade().Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            value = _facade().json.loads(raw)
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}
    return {}


def _json_list(raw: _facade().Any) -> _facade().List[_facade().Any]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str) and raw.strip().startswith("["):
        try:
            value = _facade().json.loads(raw)
            return value if isinstance(value, list) else []
        except Exception:
            return []
    return []


def _status_from_block(
    node_id: str,
    block: _facade().Dict[str, _facade().Any],
    *,
    source: str,
    detail: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    ok: _facade().Optional[bool] = None,
) -> _facade().Dict[str, _facade().Any]:
    detail_out: _facade().Dict[str, _facade().Any] = dict(detail or {})
    for key in (
        "record_id",
        "phase",
        "release_train",
        "release_kind",
        "shadow",
        "dry_run",
        "skipped",
        "unit_count",
        "lines",
        "employee_chain",
        "planned_steps",
        "step_ids",
        "executed_steps",
        "error",
        "reason",
    ):
        if key in block and key not in detail_out:
            detail_out[key] = block.get(key)
    block_ok = ok if ok is not None else block.get("ok")
    if block.get("skipped") and block_ok is None:
        block_ok = True
    return _facade()._node_status_shell(
        node_id,
        last_run=_facade()._iso_or_none(
            block.get("completed_at") or block.get("ran_at") or block.get("started_at")
        ),
        ok=bool(block_ok) if block_ok is not None else None,
        source=source,
        detail=detail_out,
        observed=True,
        proof_status="shadow_observed" if block.get("shadow") or block.get("dry_run") else None,
    )


def _decision_not_taken_status(
    node_id: str,
    *,
    last_run: _facade().Optional[str] = None,
    source: str,
    reason: str,
    detail: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> _facade().Dict[str, _facade().Any]:
    detail_out = dict(detail or {})
    if reason and "reason" not in detail_out:
        detail_out["reason"] = reason
    return _facade()._node_status_shell(
        node_id,
        last_run=last_run,
        ok=None,
        source=source,
        detail=detail_out,
        observed=True,
        proof_status="decision_not_taken",
    )


def _derive_mapped_node(
    node_id: str,
    from_node: _facade().Dict[str, _facade().Any],
    *,
    source: str,
    detail: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> _facade().Dict[str, _facade().Any]:
    detail_out = {"from_node": from_node.get("node_id")}
    detail_out.update(from_node.get("detail") if isinstance(from_node.get("detail"), dict) else {})
    detail_out.update(detail or {})
    proof_status = from_node.get("proof_status")
    if proof_status not in (
        "shadow_observed",
        "planned",
        "decision_true",
        "decision_false",
        "decision_not_taken",
    ):
        proof_status = None
    return _facade()._node_status_shell(
        node_id,
        last_run=_facade()._iso_or_none(from_node.get("last_run")),
        ok=from_node.get("ok"),
        source=source,
        detail=detail_out,
        observed=True,
        proof_status=proof_status,
    )


def _ensure_p2_line_mappings(
    derived: _facade().Dict[str, _facade().Dict[str, _facade().Any]],
    *,
    record_id: int = 0,
    release_kind: str = "",
) -> None:
    """派生 P2 编码节点，避免调度证据和 P2 图节点因解析顺序脱节。"""
    for source_nid, mapped_nid in (("PW", "P2W"), ("APPB", "P2APP"), ("SR", "P2R")):
        if source_nid in derived and mapped_nid not in derived:
            derived[mapped_nid] = _facade()._derive_mapped_node(
                mapped_nid,
                derived[source_nid],
                source=f"time_rail.derive.{source_nid}",
                detail={"record_id": record_id, "release_kind": release_kind},
            )


def _line_total_sections(
    line_dispatch: _facade().Dict[str, _facade().Any], line: str
) -> _facade().Optional[int]:
    meta = (
        line_dispatch.get("line_meta") if isinstance(line_dispatch.get("line_meta"), dict) else {}
    )
    row = meta.get(line) if isinstance(meta.get(line), dict) else None
    if not row:
        return None
    try:
        return int(row.get("total_sections") or 0)
    except Exception:
        return None


def _ensure_non_triggered_time_rail_decisions(
    derived: _facade().Dict[str, _facade().Dict[str, _facade().Any]],
    *,
    last_run: _facade().Optional[str],
    record_id: int,
    release_kind: str,
    line_dispatch: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    phase_c_pipeline: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    phase_c: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    guard_active: bool = False,
) -> None:
    """Mark branch steps that were decided but intentionally not run in this cadence."""
    base_detail = {"record_id": record_id, "release_kind": release_kind or "unknown"}

    def mark(
        node_id: str,
        *,
        source: str,
        reason: str,
        detail: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    ):
        if node_id in derived:
            return
        out_detail = dict(base_detail)
        out_detail.update(detail or {})
        derived[node_id] = _facade()._decision_not_taken_status(
            node_id, last_run=last_run, source=source, reason=reason, detail=out_detail
        )

    if not guard_active:
        mark(
            "DRPROBE",
            source="release_train.backup_guard",
            reason="no_active_backup_guard",
            detail={"active": False},
        )
    dispatch = line_dispatch or {}
    for line, line_node, p2_node in (("P-W", "PW", "P2W"), ("S-R", "SR", "P2R")):
        total = _facade()._line_total_sections(dispatch, line)
        if total == 0:
            detail = {"line": line, "total_sections": 0}
            mark(
                line_node,
                source="daily_digest.vibe_prep_line_dispatch",
                reason="line_has_no_work_items",
                detail=detail,
            )
            mark(
                p2_node,
                source=f"time_rail.derive.{line_node}",
                reason="line_has_no_work_items",
                detail={**detail, "from_node": line_node},
            )
    if release_kind not in ("installer", "major"):
        for nid in ("P9I", "P5I", "P6I", "FASTGATE", "DLSSOT"):
            mark(nid, source="daily_digest.release_kind", reason="release_kind_not_installer")
    pipeline = phase_c_pipeline or {}
    step_ids = list(
        pipeline.get("executed_steps")
        or pipeline.get("step_ids")
        or pipeline.get("planned_steps")
        or []
    )
    if pipeline or release_kind == "daily":
        for step in ("P4", "P5", "P6", "P9"):
            if step not in step_ids:
                mark(
                    step,
                    source="daily_digest.phase_c_pipeline",
                    reason="phase_c_step_not_planned",
                    detail={"step_ids": step_ids},
                )
        if "P5" not in step_ids and "P6" not in step_ids:
            mark(
                "CANARY",
                source="daily_digest.phase_c_pipeline",
                reason="canary_not_scheduled_without_release",
                detail={"step_ids": step_ids},
            )
        if "P6" not in step_ids:
            for nid in ("P6POP", "P6PW"):
                mark(
                    nid,
                    source="daily_digest.phase_c_pipeline",
                    reason="update_push_not_scheduled",
                    detail={"step_ids": step_ids},
                )
        mark(
            "P9G",
            source="release_train.json",
            reason="generation_cadence_not_due",
            detail={"step_ids": step_ids},
        )
    rollback = (
        pipeline.get("rollback")
        if isinstance(pipeline.get("rollback"), dict)
        else (
            (phase_c or {}).get("rollback")
            if isinstance((phase_c or {}).get("rollback"), dict)
            else None
        )
    )
    if not rollback:
        mark(
            "ROLLBACK",
            source="daily_digest.phase_c_pipeline",
            reason="rollback_not_required",
            detail={"step_ids": step_ids},
        )
    mark(
        "HEAL",
        source="daily_digest.phase_c_pipeline",
        reason="self_heal_not_required",
        detail={"step_ids": step_ids},
    )


def _latest_ops_staged_change() -> _facade().Optional[_facade().Any]:
    try:
        from modstore_server.models import OpsStagedChange, get_session_factory

        session_factory = get_session_factory()
        with session_factory() as session:
            return (
                session.query(OpsStagedChange).order_by(OpsStagedChange.id.desc()).limit(1).first()
            )
    except Exception:
        _facade().logger.debug("time_rail: ops staged change unavailable", exc_info=True)
        return None


def _latest_change_request() -> _facade().Optional[_facade().Any]:
    try:
        from modstore_server.models import EmployeeChangeRequest, get_session_factory

        session_factory = get_session_factory()
        with session_factory() as session:
            return (
                session.query(EmployeeChangeRequest)
                .order_by(EmployeeChangeRequest.id.desc())
                .limit(1)
                .first()
            )
    except Exception:
        _facade().logger.debug("time_rail: change request unavailable", exc_info=True)
        return None


def _action_item_stats(
    *, day: str = "", record_id: _facade().Optional[int] = None
) -> _facade().Dict[str, _facade().Any]:
    try:
        from modstore_server.digest_action_items import list_action_items

        items = list_action_items(day=day or None, limit=2000)
        if record_id:
            items = [it for it in items if int(it.get("record_id") or 0) == int(record_id)]
        by_kind: _facade().Dict[str, int] = {}
        by_status: _facade().Dict[str, int] = {}
        for it in items:
            by_kind[str(it.get("kind") or "")] = by_kind.get(str(it.get("kind") or ""), 0) + 1
            by_status[str(it.get("status") or "")] = (
                by_status.get(str(it.get("status") or ""), 0) + 1
            )
        return {"ok": True, "total": len(items), "by_kind": by_kind, "by_status": by_status}
    except Exception:
        _facade().logger.debug("time_rail: action item stats unavailable", exc_info=True)
        return {"ok": False, "total": 0, "by_kind": {}, "by_status": {}}


def _maintenance_backlog_by_node() -> _facade().Dict[str, _facade().Dict[str, _facade().Any]]:
    """读取已排队的时间轨自维护任务，作为缺证节点的可证明状态。"""
    try:
        from modstore_server.six_line_event_router import read_digest_backlog_entries

        rows = read_digest_backlog_entries()
    except Exception:
        _facade().logger.debug("time_rail: maintenance backlog unavailable", exc_info=True)
        return {}
    out: _facade().Dict[str, _facade().Dict[str, _facade().Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("source") or "") != "time-rail-observability":
            continue
        nid = str(row.get("node_id") or "").strip()
        if not nid:
            continue
        prev = out.get(nid)
        if prev and str(prev.get("at") or "") >= str(row.get("at") or ""):
            continue
        out[nid] = dict(row)
    return out


def _latest_digest_row() -> _facade().Optional[_facade().Any]:
    try:
        from modstore_server.models import DailyDigestRecord, get_session_factory

        session_factory = get_session_factory()
        with session_factory() as session:
            return (
                session.query(DailyDigestRecord)
                .order_by(DailyDigestRecord.id.desc())
                .limit(1)
                .first()
            )
    except Exception:
        _facade().logger.debug("time_rail: latest digest unavailable", exc_info=True)
        return None


def _retention_metric() -> _facade().Optional[_facade().Any]:
    try:
        from modstore_server.models import EmployeeExecutionMetric, get_session_factory

        session_factory = get_session_factory()
        with session_factory() as session:
            return (
                session.query(EmployeeExecutionMetric)
                .filter(EmployeeExecutionMetric.employee_id == "retention-officer")
                .order_by(EmployeeExecutionMetric.id.desc())
                .limit(1)
                .first()
            )
    except Exception:
        _facade().logger.debug("time_rail: retention metric unavailable", exc_info=True)
        return None
