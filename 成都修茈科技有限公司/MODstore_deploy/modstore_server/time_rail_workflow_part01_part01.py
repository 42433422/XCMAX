# mypy: disable-error-code="valid-type"
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
    except _facade().RECOVERABLE_ERRORS:
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
        except _facade().RECOVERABLE_ERRORS:
            return {}
    return {}


def _json_list(raw: _facade().Any) -> _facade().List[_facade().Any]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str) and raw.strip().startswith("["):
        try:
            value = _facade().json.loads(raw)
            return value if isinstance(value, list) else []
        except _facade().RECOVERABLE_ERRORS:
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
    except _facade().RECOVERABLE_ERRORS:
        return None
