"""消费三产线清单，按 Phase A/B 派发 WorkUnit（不直接跑完整 P3–P9 流水线）。"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from modstore_server.digest_vibe_line_dispatch import DISPATCH_PS
from modstore_server.digest_vibe_work_units import (
    DISPATCH_APP,
    DISPATCH_PW,
    DISPATCH_SR,
    VibeWorkUnit,
    parse_digest_record_work_units,
)

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: str = "1") -> bool:
    raw = (os.environ.get(name, default) or "").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _parse_priorities_env() -> Optional[List[str]]:
    raw = (os.environ.get("MODSTORE_DAILY_VIBE_EXECUTE_PRIORITIES") or "P0,P1,P2").strip()
    if not raw or raw.lower() in ("*", "all"):
        return None
    parts = [p.strip().upper() for p in raw.replace(";", ",").split(",") if p.strip()]
    return parts or None


def _max_units() -> int:
    try:
        return max(1, min(int(os.environ.get("MODSTORE_DAILY_VIBE_EXECUTE_MAX_UNITS", "32")), 128))
    except ValueError:
        return 32


def _resolve_user_id() -> int:
    raw = (
        os.environ.get("MODSTORE_DAILY_VIBE_EXECUTE_USER_ID")
        or os.environ.get("MODSTORE_DAILY_VIBE_PREP_USER_ID")
        or os.environ.get("MODSTORE_DAILY_BRIEF_USER_ID")
        or "0"
    ).strip()
    return int(raw) if raw.isdigit() else 0


def _read_execute_meta(record_id: int) -> Dict[str, Any]:
    try:
        from modstore_server.models import DailyDigestRecord, get_session_factory

        sf = get_session_factory()
        with sf() as session:
            raw = (
                session.query(DailyDigestRecord.vibe_line_execute_json)
                .filter(DailyDigestRecord.id == int(record_id))
                .scalar()
            )
            if raw and str(raw).strip().startswith("{"):
                return json.loads(str(raw))
    except Exception:
        pass
    return {}


def persist_line_execute_on_digest_record(record_id: int, payload: Dict[str, Any]) -> None:
    if record_id <= 0 or not isinstance(payload, dict):
        return
    try:
        from modstore_server.models import DailyDigestRecord, get_session_factory

        sf = get_session_factory()
        with sf() as session:
            row = session.get(DailyDigestRecord, int(record_id))
            if row is None:
                return
            row.vibe_line_execute_json = json.dumps(payload, ensure_ascii=False)
            session.commit()
    except Exception:
        logger.exception("persist_line_execute_on_digest_record failed id=%s", record_id)


def _load_digest_execute_context(record_id: int) -> Optional[Dict[str, Any]]:
    from modstore_server.models import DailyDigestRecord, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        row = session.get(DailyDigestRecord, int(record_id))
        if row is None:
            return None
        vibe_meta: Dict[str, Any] = {}
        try:
            raw_vm = getattr(row, "vibe_prep_meta_json", "") or ""
            if raw_vm.strip().startswith("{"):
                vibe_meta = json.loads(raw_vm)
        except Exception:
            vibe_meta = {}
        return {
            "record_id": int(record_id),
            "subject": str(row.subject or ""),
            "base_version": str(
                vibe_meta.get("base_version") or vibe_meta.get("version") or ""
            ).strip(),
            "md_map": {
                DISPATCH_PW: getattr(row, "vibe_prep_pw_md", "") or "",
                DISPATCH_PS: getattr(row, "vibe_prep_ps_md", "") or "",
                DISPATCH_APP: getattr(row, "vibe_prep_app_md", "") or "",
                DISPATCH_SR: getattr(row, "vibe_prep_sr_md", "") or "",
            },
        }


def _risk_flags_for_dispatch() -> Dict[str, bool]:
    return {
        "allow_high_risk_real_run": _env_bool("MODSTORE_DAILY_VIBE_EXECUTE_ALLOW_HIGH_RISK", "0"),
        "allow_medium_risk": _env_bool("MODSTORE_DAILY_VIBE_EXECUTE_ALLOW_MEDIUM_RISK", "0"),
    }


def _work_units_to_subtasks(
    units: Sequence[VibeWorkUnit],
    *,
    digest_record_id: int,
    base_version: str,
    dispatch_line: str,
    project_root: str,
    digest_subject: str = "",
) -> List[Any]:
    from modstore_server.task_router import SubTask

    risk_flags = _risk_flags_for_dispatch()
    subtasks: List[SubTask] = []
    for u in units:
        brief = (
            f"[Vibe {dispatch_line} · {u.list_kind} · {u.priority}] "
            f"digest#{digest_record_id} · {base_version}\n"
            f"摘要主题：{digest_subject or '—'}\n"
            f"任务：{u.task_brief}"
        )
        if u.path_hints:
            brief += "\n路径提示：" + ", ".join(u.path_hints)
        pri_num = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}.get(u.priority, 5)
        routing: Dict[str, Any] = {}
        if u.priority == "P0":
            routing["delegate"] = "cursor"
        if u.employee_id == "vibe-coding-maintainer":
            routing["project_root"] = project_root
        subtasks.append(
            SubTask(
                employee_id=u.employee_id,
                task_brief=brief,
                input_data={
                    "project_root": project_root,
                    "digest_record_id": digest_record_id,
                    "base_version": base_version,
                    "dispatch_line": dispatch_line,
                    "list_kind": u.list_kind,
                    "priority": u.priority,
                    "pipeline_step": u.pipeline_step,
                    "unit_id": u.unit_id,
                    "path_hints": list(u.path_hints),
                    "vibe_work_unit": u.to_dict(),
                    **risk_flags,
                    **routing,
                },
                priority=pri_num,
            )
        )
    return subtasks


def _filter_units_for_line(
    units: Sequence[VibeWorkUnit],
    *,
    line: str,
    phase: str,
) -> List[VibeWorkUnit]:
    filtered: List[VibeWorkUnit] = list(units)
    if line == DISPATCH_PW:
        filtered = [u for u in filtered if u.pipeline_step in ("P1", "P2")]
        if phase == "B":
            filtered = [
                u
                for u in filtered
                if u.list_kind == "updates"
                or (u.list_kind == "patches" and u.pipeline_step == "P2")
            ]
    elif line == DISPATCH_SR:
        filtered = [
            u for u in filtered if u.pipeline_step in ("P1", "P8") or u.list_kind == "updates"
        ]
    elif line == DISPATCH_APP:
        # 移动 / App 发布线：消费 P1/P2 的更新与补丁（打包 / 渠道发布 / WebView 适配）。
        filtered = [u for u in filtered if u.pipeline_step in ("P1", "P2")]
    elif line == DISPATCH_PS:
        filtered = [u for u in filtered if u.list_kind == "patches" and u.pipeline_step == "P2"]
    else:
        filtered = [u for u in filtered if u.pipeline_step == "P2"]
    return filtered


def _resolve_line_mode(
    dispatch_line: str,
    *,
    phase: str,
    requested_mode: str,
) -> tuple[str, bool, Dict[str, Any]]:
    """按产线灰度策略解析执行 mode 与 dry_run。"""
    global_mode = (
        os.environ.get("MODSTORE_DAILY_ORCHESTRATOR_DIGEST_MODE", "shadow") or "shadow"
    ).strip().lower()
    try:
        from modstore_server.line_rollout_policy import resolve_line_execution_mode, should_allow_line_primary

        policy = should_allow_line_primary(dispatch_line)
        line_mode = resolve_line_execution_mode(
            dispatch_line,
            phase=phase,
            global_digest_mode=global_mode,
        )
        if not policy.get("allowed"):
            line_mode = "shadow"
        if requested_mode == "shadow":
            line_mode = "shadow"
        dry_run = line_mode == "shadow"
        return line_mode, dry_run, policy
    except Exception:
        dry_run = requested_mode == "shadow" or global_mode == "shadow"
        return requested_mode or ("shadow" if dry_run else "auto"), dry_run, {}


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

        subtasks = _work_units_to_subtasks(
            units,
            digest_record_id=int(record_id),
            base_version=base_version,
            dispatch_line=line,
            project_root=root,
            digest_subject=str(ctx.get("subject") or ""),
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

        from modstore_server.employee_orchestrator import dispatch_subtasks

        dispatch_out = dispatch_subtasks(
            subtasks,
            created_by_user_id=_resolve_user_id(),
            max_concurrency=conc,
            allow_high_risk_real_run=allow_high_risk,
        )

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
            except Exception:
                logger.exception("action_items dispatch writeback failed record_id=%s", record_id)

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


def _merge_run_meta(meta: Dict[str, Any], line: str, run: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(meta or {})
    runs = dict(out.get("runs") or {})
    runs[line] = run
    out["runs"] = runs
    out["last_line"] = line
    out["last_completed_at"] = run.get("completed_at")
    out["last_ok"] = bool(run.get("ok"))
    return out
