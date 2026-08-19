"""Execution workflow for parsed daily-digest production-line work units."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Sequence

from modstore_server import digest_line_executor as facade
from modstore_server.digest_vibe_line_dispatch import DISPATCH_PS


def execute_digest_line_work_units(
    record_id: int,
    *,
    dispatch_line: str = DISPATCH_PS,
    list_kinds: Optional[Sequence[str]] = None,
    priorities: Optional[Sequence[str]] = None,
    phase: str = "A",
    mode: str = "auto",
    force: bool = False,
    dry_run: bool = False,
    max_units: Optional[int] = None,
    max_concurrency: Optional[int] = None,
    allow_high_risk_real_run: Optional[bool] = None,
) -> Dict[str, Any]:
    """解析产线 MD → ``dispatch_subtasks``（Phase A=P-S 补丁，Phase B=P-W/S-R）。"""
    _env_bool = facade._env_bool
    DISPATCH_PS = facade.DISPATCH_PS
    DISPATCH_PW = facade.DISPATCH_PW
    DISPATCH_APP = facade.DISPATCH_APP
    DISPATCH_SR = facade.DISPATCH_SR
    _resolve_line_mode = facade._resolve_line_mode
    _parse_priorities_env = facade._parse_priorities_env
    _max_units = facade._max_units
    _load_digest_execute_context = facade._load_digest_execute_context
    _read_execute_meta = facade._read_execute_meta
    _merge_run_meta = facade._merge_run_meta
    persist_line_execute_on_digest_record = facade.persist_line_execute_on_digest_record
    parse_digest_record_work_units = facade.parse_digest_record_work_units
    _filter_units_for_line = facade._filter_units_for_line
    _split_local_verified_units = facade._split_local_verified_units
    _work_units_to_subtasks = facade._work_units_to_subtasks
    _resolve_user_id = facade._resolve_user_id
    _platform_bench_override = facade._platform_bench_override
    _mark_local_verified_action_items_merged = facade._mark_local_verified_action_items_merged
    logger = facade.logger

    if not _env_bool("MODSTORE_DAILY_VIBE_EXECUTE_ENABLED", "1"):
        return {"ok": False, "skipped": True, "reason": "MODSTORE_DAILY_VIBE_EXECUTE_ENABLED=0"}

    line = (dispatch_line or DISPATCH_PS).strip()
    run_phase = (phase or "A").strip().upper() or "A"
    line_mode, policy_dry_run, rollout_policy = _resolve_line_mode(
        line, phase=run_phase, requested_mode=mode
    )
    if dry_run or policy_dry_run:
        dry_run = True
        line_mode = "shadow"
    kinds = list(list_kinds) if list_kinds is not None else ["patches"]
    prios = list(priorities) if priorities is not None else _parse_priorities_env()
    cap = max_units if max_units is not None else _max_units()

    try:
        from modstore_server.integrations.ops_action_handlers import repo_root

        ctx = _load_digest_execute_context(int(record_id))
        if ctx is None:
            return {"ok": False, "error": "digest record not found", "record_id": record_id}

        base_version = ctx["base_version"]
        meta_prev = _read_execute_meta(int(record_id))
        prev_line = (meta_prev.get("runs") or {}).get(line) or {}
        if not dry_run:
            try:
                from modstore_server.line_rollout_policy import check_daily_cr_budget

                budget = check_daily_cr_budget(digest_record_id=int(record_id))
                if not budget.get("ok"):
                    run_payload = {
                        "ok": True,
                        "skipped": True,
                        "reason": "daily_cr_budget_exceeded",
                        "budget": budget,
                        "dispatch_line": line,
                        "phase": run_phase,
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                    }
                    merged = _merge_run_meta(meta_prev, line, run_payload)
                    persist_line_execute_on_digest_record(record_id, merged)
                    return {"ok": True, "record_id": record_id, **run_payload}
            except Exception:
                logger.debug("cr budget check skipped", exc_info=True)

        if (
            not force
            and not dry_run
            and prev_line.get("ok")
            and prev_line.get("base_version") == base_version
            and prev_line.get("phase") == run_phase
        ):
            return {
                "ok": True,
                "skipped": True,
                "reason": "already executed for base_version",
                "record_id": record_id,
                "dispatch_line": line,
                "base_version": base_version,
                "previous": prev_line,
            }

        md_map = ctx["md_map"]
        line_md = md_map.get(line, "")
        if not line_md.strip():
            run_payload = {
                "ok": True,
                "skipped": True,
                "reason": f"empty line markdown for {line}",
                "dispatch_line": line,
                "base_version": base_version,
                "phase": run_phase,
                "mode": line_mode,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
            merged = _merge_run_meta(meta_prev, line, run_payload)
            persist_line_execute_on_digest_record(record_id, merged)
            return {"ok": True, "record_id": record_id, **run_payload}

        units = parse_digest_record_work_units(
            ps_markdown=md_map.get(DISPATCH_PS, ""),
            pw_markdown=md_map.get(DISPATCH_PW, ""),
            app_markdown=md_map.get(DISPATCH_APP, ""),
            sr_markdown=md_map.get(DISPATCH_SR, ""),
            digest_record_id=int(record_id),
            base_version=base_version,
            dispatch_line=line,
            list_kinds=kinds,
            priorities=prios,
        )
        units = _filter_units_for_line(units, line=line, phase=run_phase)
        if cap and len(units) > cap:
            units = units[:cap]

        started_at = datetime.now(timezone.utc).isoformat()
        root = str(repo_root())

        if not units:
            run_payload = {
                "ok": True,
                "skipped": True,
                "reason": "no matching work units",
                "dispatch_line": line,
                "list_kinds": kinds,
                "priorities": prios,
                "base_version": base_version,
                "phase": run_phase,
                "mode": line_mode,
                "dry_run": dry_run,
                "rollout_policy": rollout_policy,
                "unit_count": 0,
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
            merged = _merge_run_meta(meta_prev, line, run_payload)
            persist_line_execute_on_digest_record(record_id, merged)
            return {"ok": True, "record_id": record_id, **run_payload}

        if dry_run:
            completed_at = datetime.now(timezone.utc).isoformat()
            run_payload = {
                "ok": True,
                "dry_run": True,
                "dispatch_line": line,
                "list_kinds": kinds,
                "priorities": prios,
                "base_version": base_version,
                "phase": run_phase,
                "mode": line_mode,
                "rollout_policy": rollout_policy,
                "unit_count": len(units),
                "units": [u.to_dict() for u in units],
                "planned_employees": sorted({u.employee_id for u in units}),
                "started_at": started_at,
                "completed_at": completed_at,
            }
            merged = _merge_run_meta(meta_prev, line, run_payload)
            persist_line_execute_on_digest_record(record_id, merged)
            return {"ok": True, "record_id": record_id, **run_payload}

        local_units, local_results, remote_units = _split_local_verified_units(
            units, record_id=int(record_id), line=line, phase=run_phase
        )

        try:
            conc = max(
                1,
                min(
                    int(
                        max_concurrency
                        or os.environ.get("MODSTORE_DAILY_VIBE_EXECUTE_CONCURRENCY", "2")
                    ),
                    8,
                ),
            )
        except ValueError:
            conc = 2
        if allow_high_risk_real_run is None:
            allow_high_risk = _env_bool("MODSTORE_DAILY_VIBE_EXECUTE_ALLOW_HIGH_RISK", "0")
        else:
            allow_high_risk = bool(allow_high_risk_real_run)

        remote_out: Dict[str, Any] = {"ok": True, "results": []}
        if remote_units:
            subtasks = _work_units_to_subtasks(
                remote_units,
                digest_record_id=int(record_id),
                base_version=base_version,
                dispatch_line=line,
                project_root=root,
                digest_subject=str(ctx.get("subject") or ""),
            )
            from modstore_server.employee_orchestrator import dispatch_subtasks

            remote_out = dispatch_subtasks(
                subtasks,
                created_by_user_id=_resolve_user_id(),
                max_concurrency=conc,
                allow_high_risk_real_run=allow_high_risk,
                bench_llm_override=_platform_bench_override(),
            )

        remote_results = list(remote_out.get("results") or [])
        all_results = [*local_results, *remote_results]
        dispatch_out = {
            "ok": bool(remote_out.get("ok")) and all(bool(r.get("ok")) for r in local_results),
            "results": all_results,
            "handoff_chain": remote_out.get("handoff_chain") or [],
            "local_verified_count": len(local_units),
            "remote_dispatched_count": len(remote_units),
        }

        completed_at = datetime.now(timezone.utc).isoformat()
        run_payload = {
            "ok": bool(dispatch_out.get("ok")),
            "dispatch_line": line,
            "list_kinds": kinds,
            "priorities": prios,
            "base_version": base_version,
            "phase": run_phase,
            "mode": line_mode,
            "rollout_policy": rollout_policy,
            "unit_count": len(units),
            "units": [u.to_dict() for u in units],
            "dispatch": {
                "ok": dispatch_out.get("ok"),
                "results_count": len(dispatch_out.get("results") or []),
                "handoff_chain": dispatch_out.get("handoff_chain") or [],
                "local_verified_count": dispatch_out.get("local_verified_count", 0),
                "remote_dispatched_count": dispatch_out.get("remote_dispatched_count", 0),
                "local_results": local_results,
            },
            "started_at": started_at,
            "completed_at": completed_at,
        }
        if not dispatch_out.get("ok"):
            run_payload["error"] = "one or more subtasks failed"

        if run_payload.get("ok") and not dry_run:
            try:
                from modstore_server.digest_action_items import sync_dispatched_for_work_units

                run_payload["action_items_writeback"] = sync_dispatched_for_work_units(
                    int(record_id), units
                )
                if local_results:
                    run_payload["action_items_writeback"]["local_verified_merge"] = (
                        _mark_local_verified_action_items_merged(local_results)
                    )
                try:
                    from modstore_server.public_action_board import write_public_action_board

                    write_public_action_board()
                except Exception:
                    logger.exception(
                        "public action board after dispatch writeback failed record_id=%s",
                        record_id,
                    )
            except Exception:
                logger.exception("action_items dispatch writeback failed record_id=%s", record_id)
            try:
                from modstore_server.strategic_layer.digest_strategic_bridge import (
                    sync_record_after_status_writeback,
                )

                run_payload["strategic_action_bridge"] = sync_record_after_status_writeback(
                    record_id=int(record_id)
                )
            except Exception:
                logger.exception(
                    "strategic action bridge after line-execute failed record_id=%s", record_id
                )

        merged = _merge_run_meta(meta_prev, line, run_payload)
        persist_line_execute_on_digest_record(record_id, merged)
        return {"ok": run_payload["ok"], "record_id": record_id, **run_payload}

    except Exception as exc:
        logger.exception(
            "execute_digest_line_work_units failed record_id=%s line=%s", record_id, line
        )
        err_payload = {
            "ok": False,
            "error": str(exc),
            "dispatch_line": line,
            "phase": run_phase,
            "mode": mode,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            persist_line_execute_on_digest_record(
                record_id,
                _merge_run_meta(_read_execute_meta(int(record_id)), line, err_payload),
            )
        except Exception:
            pass
        return {"ok": False, "record_id": record_id, **err_payload}
