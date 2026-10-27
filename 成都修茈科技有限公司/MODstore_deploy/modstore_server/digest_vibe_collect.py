# mypy: disable-error-code="assignment, attr-defined, no-any-return, valid-type"
"""Employee snapshot collection and digest-record persistence."""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import re
from html import unescape
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger("modstore_server.digest_vibe_prep")
DigestVibeProgressCallback = Callable[[Dict[str, Any]], Awaitable[None]]


def _facade():
    return importlib.import_module("modstore_server.digest_vibe_prep")


def _finalize_vibe_result(
    *,
    synth: Dict[str, Any],
    employees: List[Dict[str, Any]],
    ctx: Dict[str, Any],
    digest_excerpt: str = "",
    meeting_excerpt: str = "",
    surface_audit_excerpt: str = "",
) -> Dict[str, Any]:
    """合成成功后打版本戳；自动模式在 LLM 不可用时走模板兜底。"""
    if synth.get("ok"):
        updates = _facade()._apply_version_stamp(
            "updates", str(synth.get("updates_markdown") or ""), ctx
        )
        patches = _facade()._apply_version_stamp(
            "patches", str(synth.get("patches_markdown") or ""), ctx
        )
        patches, backlog_meta = _facade()._merge_event_backlog_into_patches(patches)
        return {
            "ok": True,
            "error": "",
            "updates_markdown": updates,
            "patches_markdown": patches,
            "model": str(synth.get("model") or ""),
            "synthesizer": "llm",
            "event_backlog_merge": backlog_meta,
        }
    if str(ctx.get("mode") or "") != "auto":
        return {
            "ok": False,
            "error": str(synth.get("error") or "合成失败"),
            "updates_markdown": "",
            "patches_markdown": "",
            "model": str(synth.get("model") or ""),
            "synthesizer": "llm",
        }
    updates, patches = _facade()._build_template_vibe_markdowns(
        employees=employees,
        ctx=ctx,
        digest_excerpt=digest_excerpt,
        meeting_excerpt=meeting_excerpt,
        surface_audit_excerpt=surface_audit_excerpt,
        fallback_reason=str(synth.get("error") or "LLM 不可用"),
    )
    patches, backlog_meta = _facade()._merge_event_backlog_into_patches(patches)
    return {
        "ok": True,
        "error": "",
        "updates_markdown": updates,
        "patches_markdown": patches,
        "model": "template",
        "synthesizer": "template",
        "fallback_reason": str(synth.get("error") or "LLM 不可用"),
        "event_backlog_merge": backlog_meta,
    }


def _merge_event_backlog_into_patches(
    patches_markdown: str,
) -> tuple[str, Dict[str, Any]]:
    """事件轨 M2：合并 ``six_line_digest_backlog.jsonl`` 进补丁清单。"""
    if (os.environ.get("MODSTORE_EVENT_BACKLOG_MERGE_ENABLED", "1") or "").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return (patches_markdown, {"merged_count": 0, "skipped": True})
    try:
        from modstore_server.six_line_event_router import (
            merge_event_backlog_into_vibe_patches,
        )

        return merge_event_backlog_into_vibe_patches(patches_markdown, consume=True)
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("digest_vibe_prep: event backlog merge failed")
        return (patches_markdown, {"merged_count": 0, "error": "merge_failed"})


def _strip_html_to_text(raw: str, *, max_chars: int = 12000) -> str:
    text = re.sub("(?is)<(script|style)\\b.*?</\\1>", " ", raw or "")
    text = re.sub("(?s)<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub("\\s+", " ", text).strip()
    if len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "…"
    return text


def _lightweight_employee_snapshot(pkg_id: str, display_name: str) -> Dict[str, Any]:
    signals = _facade()._manifest_signals(pkg_id)
    failures = _facade()._recent_failures(pkg_id, limit=4)
    meta = _facade()._load_yuangon_employee_meta(pkg_id)
    scope = []
    outline = signals.get("employee_config_v2_outline") if isinstance(signals, dict) else {}
    if isinstance(outline, dict):
        scope = list(outline.get("workspace_scope_globs") or [])[:8]
    return {
        "employee_id": pkg_id,
        "name": display_name,
        "pack_version": _facade()._employee_pack_version(pkg_id),
        "area": _facade().yuangon_area_for_pkg(pkg_id) or signals.get("area") or "",
        "domain": str(meta.get("domain") or signals.get("domain") or "")[:400],
        "depends_on": list(signals.get("depends_on") or meta.get("depends_on_yaml") or [])[:6],
        "scope_globs": scope,
        "recent_failures": failures,
        "handlers": list(signals.get("handlers") or [])[:6],
    }


async def _collect_lightweight(
    pairs: List[Tuple[str, str]],
    *,
    progress_cb: Optional[DigestVibeProgressCallback] = None,
) -> List[Dict[str, Any]]:
    total = len(pairs)
    out: List[Dict[str, Any]] = []
    for idx, (pid, name) in enumerate(pairs, start=1):
        out.append(_facade()._lightweight_employee_snapshot(pid, name))
        if progress_cb:
            await progress_cb(
                {
                    "stage": "collect",
                    "mode": "auto",
                    "total": total,
                    "completed": idx,
                    "employee_id": pid,
                    "employee_name": name,
                }
            )
    return out


async def _collect_manual_reports(
    pairs: List[Tuple[str, str]],
    *,
    user_id: int,
    concurrency: int,
    progress_cb: Optional[DigestVibeProgressCallback] = None,
) -> List[Dict[str, Any]]:
    bench_prov, bench_mdl = _facade().resolve_platform_bench_llm()
    if not bench_prov or not bench_mdl:
        return []
    other_ids = [p for (p, _) in pairs]
    sem = asyncio.Semaphore(max(1, min(concurrency, 4)))
    done = 0
    total = len(pairs)
    lock = asyncio.Lock()
    rows: List[Dict[str, Any]] = []

    async def _one(pid: str, name: str) -> _facade().Dict[str, _facade().Any]:
        nonlocal done
        async with sem:
            row = await _facade()._report_one_employee(
                pkg_id=pid,
                display_name=name,
                other_employees=[x for x in other_ids if x != pid],
                user_id=user_id,
                bench_provider=bench_prov,
                bench_model=bench_mdl,
                with_research=False,
                user_question=None,
            )
        async with lock:
            done += 1
            snap_done = done
        if progress_cb:
            await progress_cb(
                {
                    "stage": "collect",
                    "mode": "manual",
                    "total": total,
                    "completed": snap_done,
                    "employee_id": pid,
                    "employee_name": name,
                    "employee_status": str(row.get("status") or ""),
                }
            )
        base = _facade()._lightweight_employee_snapshot(pid, name)
        base["report_markdown"] = str(row.get("report_markdown") or "")[:2500]
        base["report_status"] = str(row.get("status") or "")
        return base

    rows = await asyncio.gather(*[_one(p, n) for (p, n) in pairs])
    return list(rows)


def persist_vibe_prep_on_digest_record(record_id: int, result: Dict[str, Any]) -> None:
    """将 Vibe 预备 Markdown 写回 ``daily_digest_records`` 行。"""
    if record_id <= 0 or not isinstance(result, dict):
        return
    try:
        from modstore_server.models import DailyDigestRecord, get_session_factory

        meta = {
            "ok": bool(result.get("ok")),
            "error": str(result.get("error") or ""),
            "mode": str(result.get("mode") or ""),
            "employee_count": int(result.get("employee_count") or 0),
            "model": str(result.get("model") or ""),
            "synthesizer": str(result.get("synthesizer") or ""),
            "completed_at": str(result.get("completed_at") or ""),
            "version": str(result.get("base_version") or ""),
            "base_version": str(result.get("base_version") or ""),
            "updates_version": str(result.get("updates_version") or ""),
            "patches_version": str(result.get("patches_version") or ""),
            "digest_record_id": int(result.get("digest_record_id") or 0),
            "git_branch": str(result.get("git_branch") or ""),
            "git_commit": str(result.get("git_commit") or ""),
            "fallback_reason": str(result.get("fallback_reason") or ""),
        }
        sf = get_session_factory()
        with sf() as session:
            row = session.get(DailyDigestRecord, int(record_id))
            if row is None:
                return
            row.vibe_prep_updates_md = str(result.get("updates_markdown") or "")
            row.vibe_prep_patches_md = str(result.get("patches_markdown") or "")
            row.vibe_prep_meta_json = json.dumps(meta, ensure_ascii=False)
            session.commit()
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("persist_vibe_prep_on_digest_record failed id=%s", record_id)


def run_digest_vibe_prep_sync(
    *,
    digest_day: str,
    digest_subject: str,
    digest_body_html: str = "",
    digest_body_text: str = "",
    meeting_minutes_html: str = "",
    surface_audit_excerpt: str = "",
    mode: str = "auto",
    max_employees: int = 52,
    user_id: int = 0,
    record_id: int = 0,
) -> Dict[str, Any]:
    """同步入口：供 ``run_daily_digest_email`` 在 08:00 cron 内调用。"""
    from modstore_server.runtime_async import run_coro_sync

    try:
        return run_coro_sync(
            _facade().build_digest_vibe_prep(
                digest_day=digest_day,
                digest_subject=digest_subject,
                digest_body_html=digest_body_html,
                digest_body_text=digest_body_text,
                meeting_minutes_html=meeting_minutes_html,
                surface_audit_excerpt=surface_audit_excerpt,
                mode=mode,
                max_employees=max_employees,
                concurrency=2,
                user_id=user_id,
                record_id=record_id,
            )
        )
    except RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("run_digest_vibe_prep_sync failed")
        return {
            "ok": False,
            "error": str(exc),
            "updates_markdown": "",
            "patches_markdown": "",
            "mode": mode,
        }
