# mypy: disable-error-code="assignment, attr-defined, no-any-return, union-attr, valid-type"
"""消费三产线清单，按 Phase A/B 派发 WorkUnit（不直接跑完整 P3–P9 流水线）。"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Sequence

from modstore_server.digest_line_execution import (
    execute_digest_line_work_units as execute_digest_line_work_units,
)
from modstore_server.digest_vibe_line_dispatch import DISPATCH_PS
from modstore_server.digest_vibe_work_units import (
    DISPATCH_APP,
    DISPATCH_PW,
    DISPATCH_SR,
    VibeWorkUnit,
)
from modstore_server.digest_vibe_work_units import (
    parse_digest_record_work_units as parse_digest_record_work_units,
)
from modstore_server.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

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
        return max(
            1,
            min(int(os.environ.get("MODSTORE_DAILY_VIBE_EXECUTE_MAX_UNITS", "32")), 128),
        )
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


def _platform_bench_override() -> Optional[tuple]:
    """后台 loop 默认走平台派发：LLM 成本记到平台密钥、不查/扣用户 ``llm_calls`` 配额。

    这条 loop 是后台自治行为（和 bench/裁判同性质），不该被按「用户调用」计量——
    否则把它挂到某个真实用户的月度配额上，24/7 跑几小时就 ``403 配额不足: llm_calls``
    （生产实测 99.6% 失败的根因）。返回平台 bench (provider, model) 作为
    ``bench_llm_override`` → cognition ``use_platform_dispatch=True`` →
    ``chat_dispatch_via_platform_only``（不经 require_llm_credit）。``user_id`` 仍透传
    给 RAG 集合可见性与执行指标，作用域不变。

    关闭（回退按用户配额计费）：``MODSTORE_DAILY_VIBE_EXECUTE_PLATFORM_LLM=0``。
    未配置任何平台密钥时返回 ``None``（无法路由平台，退回原行为）。
    """
    if not _env_bool("MODSTORE_DAILY_VIBE_EXECUTE_PLATFORM_LLM", "1"):
        return None
    try:
        from modstore_server.services.llm import resolve_platform_bench_llm

        rp, rm = resolve_platform_bench_llm()
        if rp and rm:
            return (rp, rm)
    except BOUNDARY_ERRORS:  # noqa: BLE001
        return None
    return None


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
    except RECOVERABLE_ERRORS:
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
    except RECOVERABLE_ERRORS:
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
        except RECOVERABLE_ERRORS:
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


_VIBE_PREP_BREAKPOINT_PHRASES = (
    "Vibe 预备任务生成断点",
    "Vibe fallback 任务责任路由",
    "template fallback 发生时必须进入",
)


def _is_vibe_prep_generation_breakpoint_unit(unit: VibeWorkUnit, *, line: str) -> bool:
    """Vibe 预备 fallback 自举任务用本地证据验收，避免再进同一条慢 LLM 链路。"""
    if (line or "").strip() != DISPATCH_PS:
        return False
    if str(getattr(unit, "list_kind", "") or "") != "patches":
        return False
    brief = str(getattr(unit, "task_brief", "") or "")
    return any(p in brief for p in _VIBE_PREP_BREAKPOINT_PHRASES)


def _verify_vibe_prep_generation_breakpoint_unit(
    record_id: int, unit: VibeWorkUnit
) -> Dict[str, Any]:
    """快速闭环 Vibe 预备 fallback 任务：预备 MD、action-items、AI 交流圈都有证据即通过。"""
    evidence: Dict[str, Any] = {
        "kind": "vibe_prep_generation_breakpoint",
        "record_id": int(record_id),
        "unit_id": str(unit.unit_id or ""),
    }
    try:
        from sqlalchemy import text as _sql

        from modstore_server.digest_action_items import (
            ensure_table,
            find_matching_item_ids,
        )
        from modstore_server.models import (
            DailyDigestRecord,
            get_engine,
            get_session_factory,
        )

        sf = get_session_factory()
        with sf() as session:
            row = session.get(DailyDigestRecord, int(record_id))
            if row is None:
                return {
                    "ok": False,
                    "employee_id": unit.employee_id,
                    "error": "digest record not found",
                    "evidence": evidence,
                }
            day = str(getattr(row, "day", "") or "")
            ps_md = str(getattr(row, "vibe_prep_ps_md", "") or "")
            raw_meta = str(getattr(row, "vibe_prep_meta_json", "") or "")
        meta: Dict[str, Any] = {}
        if raw_meta.strip().startswith("{"):
            try:
                meta = json.loads(raw_meta)
            except RECOVERABLE_ERRORS:
                meta = {}

        fallback_reason = str(meta.get("fallback_reason") or "").strip()
        evidence.update(
            {
                "day": day,
                "fallback_reason": fallback_reason,
                "ps_contains_breakpoint": "Vibe 预备任务生成断点" in ps_md,
            }
        )

        ensure_table()
        item_ids = find_matching_item_ids(
            record_id=int(record_id),
            employee_id=unit.employee_id,
            kind="patch",
            task_text=unit.task_brief,
            day=day or None,
        )
        evidence["action_item_ids"] = item_ids

        collab_ids: List[int] = []
        if day:
            eng = get_engine()
            with eng.begin() as conn:
                report_key = f"actions|{day}|{unit.employee_id}"
                rows = conn.execute(
                    _sql(
                        "SELECT id FROM employee_collab_messages "
                        "WHERE payload_json LIKE :pattern "
                        "ORDER BY id DESC LIMIT 5"
                    ),
                    {"pattern": f"%{report_key}%"},
                ).fetchall()
            collab_ids = [int(r[0]) for r in rows]
        evidence["collab_message_ids"] = collab_ids

        missing: List[str] = []
        if not fallback_reason:
            missing.append("vibe_prep_meta_json.fallback_reason")
        if not evidence["ps_contains_breakpoint"]:
            missing.append("vibe_prep_ps_md breakpoint task")
        if not item_ids:
            missing.append("daily_action_items matched row")
        if not collab_ids:
            missing.append("employee_collab_messages actions report")
        if missing:
            return {
                "ok": False,
                "employee_id": unit.employee_id,
                "error": "missing evidence: " + ", ".join(missing),
                "evidence": evidence,
            }
        return {
            "ok": True,
            "employee_id": unit.employee_id,
            "mode": "system_verified",
            "result": "Vibe 预备 fallback 任务已由落库证据闭环",
            "evidence": evidence,
        }
    except BOUNDARY_ERRORS as exc:  # noqa: BLE001
        logger.exception(
            "verify vibe prep generation breakpoint failed record_id=%s unit=%s",
            record_id,
            getattr(unit, "unit_id", ""),
        )
        return {
            "ok": False,
            "employee_id": unit.employee_id,
            "error": str(exc),
            "evidence": evidence,
        }


def _split_local_verified_units(
    units: Sequence[VibeWorkUnit],
    *,
    record_id: int,
    line: str,
    phase: str,
) -> tuple[List[VibeWorkUnit], List[Dict[str, Any]], List[VibeWorkUnit]]:
    if (phase or "").strip().upper() != "A":
        return [], [], list(units)
    local_units: List[VibeWorkUnit] = []
    remote_units: List[VibeWorkUnit] = []
    local_results: List[Dict[str, Any]] = []
    for unit in units:
        if _is_vibe_prep_generation_breakpoint_unit(unit, line=line):
            local_units.append(unit)
            local_results.append(_verify_vibe_prep_generation_breakpoint_unit(record_id, unit))
        else:
            remote_units.append(unit)
    return local_units, local_results, remote_units


def _mark_local_verified_action_items_merged(
    results: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """本地 evidence 已验收的自举任务没有后续员工执行，直接推进到 merged。"""
    ids: List[int] = []
    for result in results:
        if not bool(result.get("ok")):
            continue
        evidence = result.get("evidence") if isinstance(result.get("evidence"), dict) else {}
        for raw_id in evidence.get("action_item_ids") or []:
            try:
                iid = int(raw_id)
            except (TypeError, ValueError):
                continue
            if iid not in ids:
                ids.append(iid)
    if not ids:
        return {"ok": True, "updated": 0, "matched_ids": []}

    updated = 0
    advanced: List[int] = []
    try:
        from modstore_server.digest_action_items import set_status_if_advanced

        for iid in ids:
            if set_status_if_advanced(iid, "merged"):
                updated += 1
                advanced.append(iid)
        return {
            "ok": True,
            "updated": updated,
            "matched_ids": advanced,
            "seen_ids": ids,
        }
    except BOUNDARY_ERRORS as exc:  # noqa: BLE001
        logger.exception("local verified action_items merge writeback failed")
        return {
            "ok": False,
            "error": str(exc),
            "updated": updated,
            "matched_ids": advanced,
        }


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
        (os.environ.get("MODSTORE_DAILY_ORCHESTRATOR_DIGEST_MODE", "shadow") or "shadow")
        .strip()
        .lower()
    )
    try:
        from modstore_server.line_rollout_policy import (
            resolve_line_execution_mode,
            should_allow_line_primary,
        )

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
    except RECOVERABLE_ERRORS:
        dry_run = requested_mode == "shadow" or global_mode == "shadow"
        return requested_mode or ("shadow" if dry_run else "auto"), dry_run, {}


def _merge_run_meta(meta: Dict[str, Any], line: str, run: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(meta or {})
    runs = dict(out.get("runs") or {})
    runs[line] = run
    out["runs"] = runs
    out["last_line"] = line
    out["last_completed_at"] = run.get("completed_at")
    out["last_ok"] = bool(run.get("ok"))
    return out
