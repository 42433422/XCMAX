# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.time_rail_workflow")


def _derive_from_sources() -> _facade().Dict[str, _facade().Dict[str, _facade().Any]]:
    """从 release_train / digest / backup 等现有 SSOT 推导节点状态。"""
    derived: _facade().Dict[str, _facade().Dict[str, _facade().Any]] = {}
    guard = None
    rt_state: _facade().Dict[str, _facade().Any] = {}
    try:
        from modstore_server.release_train import active_backup_guard, load_state

        guard = active_backup_guard()
        rt_state = load_state() or {}
    except Exception:
        _facade().logger.debug("time_rail: release_train unavailable", exc_info=True)
    if guard:
        derived["DRFAIL"] = _facade()._node_status_shell(
            "DRFAIL",
            last_run=_facade()._iso_or_none(
                guard.get("last_probe_at") or guard.get("at") or guard.get("set_at")
            ),
            ok=False,
            guard_active=True,
            source="release_train.backup_guard",
            detail={"reason": guard.get("reason"), "day": guard.get("day")},
        )
        derived["DRPROBE"] = _facade()._node_status_shell(
            "DRPROBE",
            last_run=_facade()._iso_or_none(guard.get("last_probe_at") or guard.get("set_at")),
            ok=guard.get("probe_escalated") is not True,
            guard_active=True,
            source="release_train.backup_guard",
            detail={
                "probe_retry_count": guard.get("probe_retry_count"),
                "probe_escalated": guard.get("probe_escalated"),
            },
        )
    else:
        derived["DRFAIL"] = _facade()._node_status_shell(
            "DRFAIL",
            ok=True,
            source="release_train.backup_guard",
            detail={"active": False},
            observed=True,
            proof_status="proved_ok",
        )
    try:
        from modstore_server.daily_backup_job import list_backups

        backups = list_backups(limit=5)
        if backups:
            latest = backups[0]
            derived["BK"] = _facade()._node_status_shell(
                "BK",
                last_run=latest.get("mtime"),
                ok=True,
                source="backups.dir",
                detail={"name": latest.get("name"), "bytes": latest.get("bytes")},
            )
    except Exception:
        _facade().logger.debug("time_rail: backup list unavailable", exc_info=True)
    try:
        from modstore_server.release_train import history_dir

        hdir = history_dir()
        ondemand = sorted(hdir.glob("*ondemand*.json"), key=lambda p: p.name, reverse=True)
        if ondemand:
            latest_ondemand = ondemand[0]
            derived["BKOND"] = _facade()._node_status_shell(
                "BKOND",
                last_run=_facade()
                .datetime.fromtimestamp(latest_ondemand.stat().st_mtime, _facade().timezone.utc)
                .isoformat(),
                ok=True,
                source="release_train_history.ondemand",
                detail={"name": latest_ondemand.name, "path": str(latest_ondemand)},
            )
    except Exception:
        _facade().logger.debug("time_rail: ondemand backup history unavailable", exc_info=True)
    if rt_state:
        current = str(rt_state.get("current") or "1.0.0.0")
        day_index = int(rt_state.get("day_index") or 0)
        bump_ok = guard is None
        rt_detail = {
            "current": current,
            "last_bump_day": rt_state.get("last_bump_day"),
            "day_index": day_index,
        }
        derived["RT"] = _facade()._node_status_shell(
            "RT",
            last_run=_facade()._iso_or_none(rt_state.get("last_bump_at")),
            ok=bump_ok,
            guard_active=guard is not None,
            source="release_train.json",
            detail=rt_detail,
            observed=True,
        )
        major_today = day_index > 0 and day_index % 100 == 0
        installer_today = current.split(".")[-1:] == ["0"] and day_index > 0
        every_30 = day_index > 0 and day_index % 30 == 0
        derived["CENT"] = _facade()._node_status_shell(
            "CENT",
            last_run=_facade()._iso_or_none(rt_state.get("last_bump_at")),
            ok=None,
            source="release_train.json",
            detail={**rt_detail, "decision": major_today},
            observed=True,
            proof_status="decision_true" if major_today else "decision_false",
        )
        derived["MAJ"] = _facade()._node_status_shell(
            "MAJ",
            last_run=_facade()._iso_or_none(
                rt_state.get("last_major_push_at") or rt_state.get("last_bump_at")
            ),
            ok=True if major_today else None,
            source="release_train.json",
            detail={**rt_detail, "is_major_day": major_today},
            observed=True,
            proof_status="planned" if major_today else "decision_not_taken",
        )
        derived["GATE"] = _facade()._node_status_shell(
            "GATE",
            last_run=_facade()._iso_or_none(rt_state.get("last_bump_at")),
            ok=None,
            source="release_train.json",
            detail={**rt_detail, "decision": installer_today},
            observed=True,
            proof_status="decision_true" if installer_today else "decision_false",
        )
        derived["P6G"] = _facade()._node_status_shell(
            "P6G",
            last_run=_facade()._iso_or_none(rt_state.get("last_bump_at")),
            ok=None,
            source="release_train.json",
            detail={**rt_detail, "decision": every_30},
            observed=True,
            proof_status="decision_true" if every_30 else "decision_false",
        )
    metric = _facade()._retention_metric()
    if metric is not None:
        err = str(getattr(metric, "error", "") or "").strip()
        derived["R"] = _facade()._node_status_shell(
            "R",
            last_run=_facade()._iso_or_none(getattr(metric, "created_at", None)),
            ok=not err,
            source="employee_execution_metric",
            detail={"task_brief": getattr(metric, "task_brief", ""), "error": err},
        )
    latest_digest_created: _facade().Optional[str] = None
    latest_digest_record_id = 0
    latest_release_kind = ""
    latest_line_dispatch: _facade().Dict[str, _facade().Any] = {}
    latest_phase_c_pipeline: _facade().Dict[str, _facade().Any] = {}
    latest_phase_c: _facade().Dict[str, _facade().Any] = {}
    digest = _facade()._latest_digest_row()
    if digest is not None:
        created = _facade()._iso_or_none(getattr(digest, "created_at", None))
        latest_digest_created = created
        day = str(getattr(digest, "day", "") or "")
        record_id = int(getattr(digest, "id", 0) or 0)
        latest_digest_record_id = record_id
        release_kind = str(getattr(digest, "release_kind", "") or "daily")
        latest_release_kind = release_kind
        derived["daily-hub"] = _facade()._node_status_shell(
            "daily-hub",
            last_run=created,
            ok=True,
            source="daily_digest_records",
            detail={"digest_id": record_id, "day": day, "release_kind": release_kind},
            observed=True,
        )
        derived["K"] = _facade()._node_status_shell(
            "K",
            last_run=created,
            ok=bool(getattr(digest, "body_html", "") or getattr(digest, "body_text", "")),
            source="daily_digest_records",
            detail={"digest_id": record_id, "day": day, "scope": "KPI/TLS/IMAP section"},
        )
        derived["P"] = _facade()._node_status_shell(
            "P",
            last_run=created,
            ok=bool(getattr(digest, "delivered", False)),
            source="daily_digest_records",
            detail={"digest_id": record_id, "day": day},
        )
        derived["ASM"] = _facade()._node_status_shell(
            "ASM",
            last_run=created,
            ok=bool(getattr(digest, "body_html", "") or getattr(digest, "body_text", "")),
            source="daily_digest_records",
            detail={"digest_id": record_id, "day": day},
        )
        derived["M"] = _facade()._node_status_shell(
            "M",
            last_run=created,
            ok=bool(getattr(digest, "meeting_minutes_html", "")),
            source="daily_digest_records",
            detail={"digest_id": record_id, "day": day},
        )
        derived["V"] = _facade()._node_status_shell(
            "V",
            last_run=created,
            ok=bool(
                getattr(digest, "vibe_prep_updates_md", "")
                or getattr(digest, "vibe_prep_patches_md", "")
            ),
            source="daily_digest_records",
            detail={"release_kind": release_kind, "digest_id": record_id},
        )
        derived["KIND"] = _facade()._node_status_shell(
            "KIND",
            last_run=created,
            ok=None,
            source="daily_digest_records",
            detail={"release_kind": release_kind, "digest_id": record_id},
            observed=True,
            proof_status=(
                "decision_true" if release_kind in ("installer", "major") else "decision_false"
            ),
        )
        action_stats = _facade()._action_item_stats(day=day, record_id=record_id)
        if action_stats.get("ok"):
            derived["ACT"] = _facade()._node_status_shell(
                "ACT",
                last_run=created,
                ok=True,
                source="daily_action_items",
                detail=action_stats,
                observed=True,
            )
            patch_count = int((action_stats.get("by_kind") or {}).get("patch", 0))
            update_count = int((action_stats.get("by_kind") or {}).get("update", 0))
            derived["GAPS"] = _facade()._node_status_shell(
                "GAPS",
                last_run=created,
                ok=True,
                source="daily_action_items",
                detail={"patch_items": patch_count, "digest_id": record_id},
                observed=True,
            )
            derived["ROAD"] = _facade()._node_status_shell(
                "ROAD",
                last_run=created,
                ok=True,
                source="daily_action_items",
                detail={"update_items": update_count, "digest_id": record_id},
                observed=True,
            )
            merged = int((action_stats.get("by_status") or {}).get("merged", 0))
            if merged:
                derived["WB_M"] = _facade()._node_status_shell(
                    "WB_M",
                    last_run=created,
                    ok=True,
                    source="daily_action_items",
                    detail={"merged_items": merged, "digest_id": record_id},
                    observed=True,
                )
        line_dispatch = _facade()._json_obj(
            getattr(digest, "vibe_prep_line_dispatch_json", "") or ""
        )
        if line_dispatch:
            latest_line_dispatch = line_dispatch
            derived["L"] = _facade()._node_status_shell(
                "L",
                last_run=created,
                ok=line_dispatch.get("ok") is not False,
                source="daily_digest.vibe_prep_line_dispatch",
                detail={
                    "digest_id": record_id,
                    "line_meta": line_dispatch.get("line_meta"),
                    "total_sections": line_dispatch.get("total_sections"),
                },
                observed=True,
            )
        derived["ART"] = _facade()._node_status_shell(
            "ART",
            last_run=created,
            ok=True,
            source="daily_digest_records",
            detail={
                "digest_id": record_id,
                "has_meta": bool(getattr(digest, "vibe_prep_meta_json", "")),
            },
            observed=True,
        )
        meta_raw = getattr(digest, "vibe_prep_meta_json", "") or ""
        if meta_raw:
            try:
                meta = _facade().json.loads(meta_raw) if isinstance(meta_raw, str) else meta_raw
                audit = (meta or {}).get("surface_audit") if isinstance(meta, dict) else None
                if isinstance(audit, dict):
                    for lane, nid in (("P-W", "SW"), ("P-S", "SS"), ("P-App", "SA")):
                        lane_row = audit.get(lane) or audit.get(lane.replace("-", ""))
                        if isinstance(lane_row, dict):
                            derived[nid] = _facade()._node_status_shell(
                                nid,
                                last_run=created,
                                ok=lane_row.get("ok") is not False,
                                source="daily_digest.surface_audit",
                                detail=lane_row,
                            )
                    ppt = audit.get("ppt") if isinstance(audit.get("ppt"), dict) else None
                    if ppt:
                        derived["PPTX"] = _facade()._node_status_shell(
                            "PPTX",
                            last_run=created,
                            ok=ppt.get("ok") is not False,
                            source="daily_digest.surface_audit",
                            detail=ppt,
                        )
                orch = (meta or {}).get("orchestrator_audit") if isinstance(meta, dict) else None
                if isinstance(orch, dict):
                    derived["ORCH"] = _facade()._status_from_block(
                        "ORCH", orch, source="daily_digest.orchestrator_audit"
                    )
                    derived["BR"] = _facade()._node_status_shell(
                        "BR",
                        last_run=_facade()._iso_or_none(orch.get("ran_at")),
                        ok=orch.get("orchestrator_mode") in ("primary", "digest"),
                        source="daily_digest.orchestrator_audit",
                        detail=orch,
                        observed=True,
                    )
            except Exception:
                _facade().logger.debug("time_rail: surface_audit meta parse failed", exc_info=True)
        exec_raw = getattr(digest, "vibe_line_execute_json", "") or ""
        if exec_raw:
            try:
                ex = _facade().json.loads(exec_raw) if isinstance(exec_raw, str) else exec_raw
                if isinstance(ex, dict):
                    derived["PARSE"] = _facade()._node_status_shell(
                        "PARSE",
                        last_run=created,
                        ok=ex.get("ok") is not False,
                        source="daily_digest.vibe_line_execute",
                        detail={"mode": ex.get("mode"), "digest_id": record_id},
                    )
                    runs = ex.get("runs") if isinstance(ex.get("runs"), dict) else {}
                    phase_a = ex.get("phase_a") if isinstance(ex.get("phase_a"), dict) else {}
                    phase_b = ex.get("phase_b") if isinstance(ex.get("phase_b"), dict) else {}
                    phase_c = ex.get("phase_c") if isinstance(ex.get("phase_c"), dict) else {}
                    phase_c_pipeline = (
                        ex.get("phase_c_pipeline")
                        if isinstance(ex.get("phase_c_pipeline"), dict)
                        else {}
                    )
                    latest_phase_c = phase_c
                    latest_phase_c_pipeline = phase_c_pipeline
                    ps_run = (phase_a.get("line_results") or {}).get("P-S") or runs.get("P-S") or {}
                    app_run = (
                        (phase_a.get("line_results") or {}).get("P-App") or runs.get("P-App") or {}
                    )
                    if ps_run:
                        derived["PSA"] = _facade()._status_from_block(
                            "PSA", ps_run, source="daily_digest.phase_a.P-S"
                        )
                    if app_run:
                        derived["APPA"] = _facade()._status_from_block(
                            "APPA", app_run, source="daily_digest.phase_a.P-App"
                        )
                    if phase_a:
                        derived["WB_D"] = _facade()._status_from_block(
                            "WB_D", phase_a, source="daily_digest.phase_a"
                        )
                    for source_nid, mapped_nid in (("PSA", "P2S"),):
                        if source_nid in derived and mapped_nid not in derived:
                            derived[mapped_nid] = _facade()._derive_mapped_node(
                                mapped_nid,
                                derived[source_nid],
                                source=f"time_rail.derive.{source_nid}",
                                detail={"record_id": record_id, "release_kind": release_kind},
                            )
                    for line_key, nid in (("P-W", "PW"), ("P-App", "APPB"), ("S-R", "SR")):
                        line_block = (phase_b.get("line_results") or {}).get(line_key) or {}
                        if line_block:
                            derived[nid] = _facade()._status_from_block(
                                nid, line_block, source=f"daily_digest.phase_b.{line_key}"
                            )
                    _facade()._ensure_p2_line_mappings(
                        derived, record_id=record_id, release_kind=release_kind
                    )
                    if "APPB" not in derived and "APPA" in derived:
                        derived["APPB"] = _facade()._decision_not_taken_status(
                            "APPB",
                            last_run=_facade()._iso_or_none(derived["APPA"].get("last_run")),
                            source="daily_digest.phase_a.P-App",
                            reason="phase_b_app_updates_not_scheduled",
                            detail={"record_id": record_id, "release_kind": release_kind},
                        )
                    if phase_b:
                        derived["ORCH"] = derived.get("ORCH") or _facade()._status_from_block(
                            "ORCH", phase_b, source="daily_digest.phase_b"
                        )
                    if phase_c_pipeline:
                        step_ids = list(
                            phase_c_pipeline.get("executed_steps")
                            or phase_c_pipeline.get("step_ids")
                            or phase_c_pipeline.get("planned_steps")
                            or []
                        )
                        for step in ("P3", "P4", "P5", "P6", "P7", "P8", "P9"):
                            if step in step_ids:
                                derived[step] = _facade()._status_from_block(
                                    step,
                                    phase_c_pipeline,
                                    source="daily_digest.phase_c_pipeline",
                                    detail={"step": step, "step_ids": step_ids},
                                )
                        if any((step in step_ids for step in ("P5", "P6"))):
                            derived["CANARY"] = _facade()._status_from_block(
                                "CANARY",
                                phase_c_pipeline,
                                source="daily_digest.phase_c_pipeline",
                                detail={
                                    "step_ids": step_ids,
                                    "strategy": "staging-canary-production",
                                },
                            )
                        if phase_c_pipeline.get("rollback"):
                            derived["ROLLBACK"] = _facade()._status_from_block(
                                "ROLLBACK",
                                phase_c_pipeline.get("rollback") or {},
                                source="daily_digest.phase_c_pipeline.rollback",
                            )
                    if phase_c:
                        step_results = (
                            phase_c.get("steps") if isinstance(phase_c.get("steps"), list) else []
                        )
                        step_map = {
                            str(s.get("step") or ""): s for s in step_results if isinstance(s, dict)
                        }
                        for source_step, nid in (("P9", "P9I"), ("P5", "P5I"), ("P6", "P6I")):
                            if source_step in step_map:
                                derived[nid] = _facade()._status_from_block(
                                    nid,
                                    step_map[source_step],
                                    source="daily_digest.phase_c.installer_chain",
                                )
                        if phase_c.get("fastgate"):
                            derived["FASTGATE"] = _facade()._status_from_block(
                                "FASTGATE",
                                phase_c.get("fastgate") or {},
                                source="daily_digest.phase_c.fastgate",
                            )
                        if phase_c.get("download_release"):
                            derived["DLSSOT"] = _facade()._status_from_block(
                                "DLSSOT",
                                phase_c.get("download_release") or {},
                                source="daily_digest.phase_c.download_release",
                            )
                        if phase_c.get("rollback"):
                            derived["ROLLBACK"] = _facade()._status_from_block(
                                "ROLLBACK",
                                phase_c.get("rollback") or {},
                                source="daily_digest.phase_c.rollback",
                            )
            except Exception:
                pass
    staged = _facade()._latest_ops_staged_change()
    if staged is not None:
        staged_detail = {
            "id": getattr(staged, "id", None),
            "branch": getattr(staged, "branch", ""),
            "status": getattr(staged, "status", ""),
            "files_changed_count": getattr(staged, "files_changed_count", None),
        }
        created = _facade()._iso_or_none(getattr(staged, "created_at", None))
        approved = _facade()._iso_or_none(getattr(staged, "approved_at", None))
        deployed = _facade()._iso_or_none(getattr(staged, "deployed_at", None))
        derived["STG"] = _facade()._node_status_shell(
            "STG", last_run=created, ok=True, source="ops_staged_changes", detail=staged_detail
        )
        if approved:
            derived["APPR"] = _facade()._node_status_shell(
                "APPR",
                last_run=approved,
                ok=True,
                source="ops_staged_changes",
                detail=staged_detail,
            )
        if deployed:
            derived["V10SYNC"] = _facade()._node_status_shell(
                "V10SYNC",
                last_run=deployed,
                ok=True,
                source="ops_staged_changes",
                detail=staged_detail,
            )
            derived["MERGE"] = _facade()._node_status_shell(
                "MERGE",
                last_run=deployed,
                ok=True,
                source="ops_staged_changes",
                detail=staged_detail,
            )
        else:
            for nid, reason in (
                ("APPR", "ops_staged_change_waiting_approval"),
                ("V10SYNC", "ops_staged_change_not_deployed"),
                ("MERGE", "ops_staged_change_not_deployed"),
                ("WB_M", "ops_staged_change_not_deployed"),
            ):
                if nid not in derived:
                    derived[nid] = _facade()._decision_not_taken_status(
                        nid,
                        last_run=approved or created,
                        source="ops_staged_changes",
                        reason=reason,
                        detail=staged_detail,
                    )
    cr = _facade()._latest_change_request()
    if cr is not None:
        branch = str(getattr(cr, "git_branch", "") or "")
        base_sha = str(getattr(cr, "base_commit_sha", "") or "")
        staged_sha = str(getattr(cr, "staged_commit_sha", "") or "")
        approved = _facade()._iso_or_none(getattr(cr, "approved_at", None))
        applied = _facade()._iso_or_none(getattr(cr, "applied_at", None))
        cr_detail = {
            "id": getattr(cr, "id", None),
            "source_employee_id": getattr(cr, "source_employee_id", ""),
            "status": getattr(cr, "status", ""),
            "change_kind": getattr(cr, "change_kind", ""),
            "git_branch": branch,
            "base_commit_sha": base_sha,
            "staged_commit_sha": staged_sha,
        }
        created = _facade()._iso_or_none(
            getattr(cr, "created_at", None) or getattr(cr, "submitted_at", None)
        )
        derived["CS_CHG"] = _facade()._node_status_shell(
            "CS_CHG", last_run=created, ok=True, source="employee_change_requests", detail=cr_detail
        )
        if branch or staged_sha:
            derived["GITCR"] = _facade()._node_status_shell(
                "GITCR",
                last_run=created,
                ok=bool(branch and staged_sha),
                source="employee_change_requests.git",
                detail=cr_detail,
                observed=True,
            )
            if "STG" not in derived and branch and staged_sha:
                derived["STG"] = _facade()._node_status_shell(
                    "STG",
                    last_run=created,
                    ok=True,
                    source="employee_change_requests.git",
                    detail=cr_detail,
                    observed=True,
                )
        if approved and "APPR" not in derived:
            derived["APPR"] = _facade()._node_status_shell(
                "APPR",
                last_run=approved,
                ok=True,
                source="employee_change_requests",
                detail=cr_detail,
            )
        elif "APPR" not in derived:
            derived["APPR"] = _facade()._decision_not_taken_status(
                "APPR",
                last_run=created,
                source="employee_change_requests",
                reason="change_request_waiting_approval",
                detail=cr_detail,
            )
        for nid in ("V10SYNC", "MERGE", "WB_M"):
            if nid in derived:
                continue
            derived[nid] = _facade()._decision_not_taken_status(
                nid,
                last_run=applied or approved or created,
                source="employee_change_requests",
                reason="change_request_not_deployed",
                detail=cr_detail,
            )
        derived["O7"] = _facade()._node_status_shell(
            "O7",
            last_run=created,
            ok=True,
            source="employee_change_requests",
            detail={"bridge": "feedback-to-change-request", **cr_detail},
        )
        derived["Vibe08"] = _facade()._node_status_shell(
            "Vibe08",
            last_run=created,
            ok=True,
            source="employee_change_requests",
            detail={"bridge": "change-request-to-next-digest", **cr_detail},
        )
    for nid in ("O5", "O6"):
        if nid not in derived:
            derived[nid] = _facade()._decision_not_taken_status(
                nid,
                last_run=latest_digest_created,
                source="production_line_orchestrator.static_skip",
                reason="static_skip_step_not_triggered",
                detail={"release_kind": latest_release_kind or "unknown"},
            )
    _facade()._ensure_non_triggered_time_rail_decisions(
        derived,
        last_run=latest_digest_created,
        record_id=int(latest_digest_record_id or 0),
        release_kind=latest_release_kind or "unknown",
        line_dispatch=latest_line_dispatch,
        phase_c_pipeline=latest_phase_c_pipeline,
        phase_c=latest_phase_c,
        guard_active=bool(guard),
    )
    _facade()._ensure_p2_line_mappings(
        derived,
        record_id=int(latest_digest_record_id or 0),
        release_kind=latest_release_kind or "unknown",
    )
    return derived


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
    except Exception as exc:
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
