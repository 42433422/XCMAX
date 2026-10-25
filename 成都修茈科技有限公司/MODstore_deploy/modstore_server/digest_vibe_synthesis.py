# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""LLM synthesis and top-level digest vibe-prep orchestration."""

from __future__ import annotations

import importlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger("modstore_server.digest_vibe_prep")
DigestVibeProgressCallback = Callable[[Dict[str, Any]], Awaitable[None]]


def _facade():
    return importlib.import_module("modstore_server.digest_vibe_prep")


def _build_llm_user_content(
    *,
    digest_day: str,
    digest_subject: str,
    digest_excerpt: str,
    meeting_excerpt: str,
    surface_audit_excerpt: str,
    employees: List[Dict[str, Any]],
    mode: str,
    version_ctx: Optional[Dict[str, Any]] = None,
) -> str:
    emp_json = json.dumps(employees, ensure_ascii=False, default=str)
    if len(emp_json) > 90000:
        emp_json = emp_json[:89900] + "…"
    ver = version_ctx or {}
    evolution_block = "（未采集）"
    try:
        from modstore_server.evolution_signal_collector import (
            collect_evolution_signals,
            format_evolution_signals_for_prompt,
        )

        evolution_block = format_evolution_signals_for_prompt(collect_evolution_signals())
    except RECOVERABLE_ERRORS:
        _facade().logger.debug("digest_vibe_prep: evolution signals unavailable", exc_info=True)
    return f"模式：{mode}\n摘要日期：{digest_day}\n摘要主题：{digest_subject}\n基线版本：{ver.get('base_version') or '（待写入）'}\n更新清单版本：{ver.get('updates_version') or ''}\n补丁清单版本：{ver.get('patches_version') or ''}\n\n## 进化事实信号（优先于截图）\n{evolution_block}\n\n## 每日摘要正文节选\n{digest_excerpt or '（无）'}\n\n## 员工大会摘要节选\n{meeting_excerpt or '（无）'}\n\n## 三端页面截图巡检节选（辅助 · P-W 网站 · P-S 软件 · P-App 移动）\n{surface_audit_excerpt or '（无）'}\n\n## 员工快照 JSON（{len(employees)} 人）\n```json\n{emp_json}\n```"


async def _synthesize_vibe_markdowns(*, user_content: str, user_id: int) -> Dict[str, Any]:
    bench_prov, bench_mdl = _facade().resolve_platform_bench_llm()
    if not bench_prov or not bench_mdl:
        return {
            "ok": False,
            "error": "平台 Bench LLM 未配置",
            "updates_markdown": "",
            "patches_markdown": "",
            "model": "",
        }
    messages = [
        {"role": "system", "content": _facade()._VIBE_PREP_SYSTEM},
        {"role": "user", "content": user_content},
    ]
    try:
        from modstore_server.models import get_session_factory
        from modstore_server.services.llm import chat_dispatch_via_session

        sf = get_session_factory()
        with sf() as db:
            result = await chat_dispatch_via_session(
                db, int(user_id or 0), bench_prov, bench_mdl, messages, max_tokens=4096
            )
    except RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("digest_vibe_prep synthesize failed")
        return {
            "ok": False,
            "error": str(exc),
            "updates_markdown": "",
            "patches_markdown": "",
            "model": f"{bench_prov}/{bench_mdl}",
        }
    raw = str(result or "").strip()
    parsed: Dict[str, Any] = {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        fence = re.search("```(?:json)?\\s*(\\{[\\s\\S]*?\\})\\s*```", raw, re.I)
        blob = fence.group(1) if fence else ""
        if not blob:
            m = re.search("\\{[\\s\\S]*\\}", raw)
            blob = m.group(0) if m else ""
        if blob:
            try:
                parsed = json.loads(blob)
            except json.JSONDecodeError:
                parsed = {}
    updates = str(parsed.get("updates_markdown") or "").strip()
    patches = str(parsed.get("patches_markdown") or "").strip()
    if not updates and (not patches):
        um = re.search(
            "(?:^|\\n)#\\s*Vibe\\s*预备\\s*[·•]?\\s*更新清单\\s*\\n([\\s\\S]*?)(?=\\n#\\s*Vibe\\s*预备|\\Z)",
            raw,
            re.I,
        )
        pm = re.search(
            "(?:^|\\n)#\\s*Vibe\\s*预备\\s*[·•]?\\s*补丁清单\\s*\\n([\\s\\S]*?)(?=\\n#\\s*Vibe\\s*预备|\\Z)",
            raw,
            re.I,
        )
        if um:
            updates = ("# Vibe 预备 · 更新清单\n" + um.group(1)).strip()
        if pm:
            patches = ("# Vibe 预备 · 补丁清单\n" + pm.group(1)).strip()
    if not updates and (not patches):
        return {
            "ok": False,
            "error": "LLM 未返回有效 JSON（缺少 updates_markdown / patches_markdown）",
            "updates_markdown": "",
            "patches_markdown": "",
            "model": f"{bench_prov}/{bench_mdl}",
            "raw_preview": raw[:800],
        }
    if updates and (not updates.startswith("#")):
        updates = "# Vibe 预备 · 更新清单\n\n" + updates
    if patches and (not patches.startswith("#")):
        patches = "# Vibe 预备 · 补丁清单\n\n" + patches
    return {
        "ok": True,
        "error": "",
        "updates_markdown": updates,
        "patches_markdown": patches,
        "model": f"{bench_prov}/{bench_mdl}",
    }


async def build_digest_vibe_prep(
    *,
    digest_day: str,
    digest_subject: str,
    digest_body_html: str = "",
    digest_body_text: str = "",
    meeting_minutes_html: str = "",
    surface_audit_excerpt: str = "",
    mode: str = "auto",
    employee_ids: Optional[List[str]] = None,
    max_employees: int = 52,
    concurrency: int = 2,
    user_id: int = 0,
    record_id: int = 0,
    progress_cb: Optional[DigestVibeProgressCallback] = None,
) -> Dict[str, Any]:
    """生成 Vibe 预备双 Markdown。``mode`` 为 ``auto``（轻量快照）或 ``manual``（逐员工汇报）。"""
    started_at = datetime.now(timezone.utc).isoformat()
    mode_norm = "manual" if str(mode or "").strip().lower() == "manual" else "auto"
    cap = _facade().clamp_all_hands_max_employees(
        max_employees, default=52 if mode_norm == "auto" else 16
    )
    version_ctx = _facade().resolve_vibe_prep_version_context(
        digest_day=digest_day,
        digest_subject=digest_subject,
        record_id=record_id,
        mode=mode_norm,
    )

    async def _emit(payload: _facade().Dict[str, _facade().Any]) -> None:
        if not progress_cb:
            return
        try:
            await progress_cb(payload)
        except RECOVERABLE_ERRORS as exc:
            _facade().logger.debug("digest_vibe_prep progress cb failed: %s", exc)

    pairs = _facade()._resolve_employee_pairs(employee_ids, max_employees=cap)
    await _emit({"stage": "prepare", "total": len(pairs), "completed": 0, "mode": mode_norm})
    if not pairs:
        return {
            "ok": False,
            "error": "无可汇总员工（duty_roster ∩ catalog 为空）",
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "mode": mode_norm,
            "employee_count": 0,
            "updates_markdown": "",
            "patches_markdown": "",
        }
    digest_excerpt = (digest_body_text or "").strip()
    if not digest_excerpt:
        digest_excerpt = _facade()._strip_html_to_text(digest_body_html)
    meeting_excerpt = _facade()._strip_html_to_text(meeting_minutes_html, max_chars=6000)
    surface_excerpt = (surface_audit_excerpt or "").strip()
    if mode_norm == "manual":
        employees = await _facade()._collect_manual_reports(
            pairs, user_id=user_id, concurrency=concurrency, progress_cb=progress_cb
        )
        if not employees and pairs:
            return {
                "ok": False,
                "error": "手动模式需要 Bench LLM；平台未配置或逐岗汇报失败",
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "mode": mode_norm,
                "employee_count": 0,
                "updates_markdown": "",
                "patches_markdown": "",
                **version_ctx,
            }
    else:
        employees = await _facade()._collect_lightweight(pairs, progress_cb=progress_cb)
    await _emit(
        {
            "stage": "synthesize",
            "total": len(employees),
            "completed": len(employees),
            "mode": mode_norm,
        }
    )
    synth = await _facade()._synthesize_vibe_markdowns(
        user_content=_facade()._build_llm_user_content(
            digest_day=digest_day,
            digest_subject=digest_subject,
            digest_excerpt=digest_excerpt,
            meeting_excerpt=meeting_excerpt,
            surface_audit_excerpt=surface_excerpt,
            employees=employees,
            mode=mode_norm,
            version_ctx=version_ctx,
        ),
        user_id=user_id,
    )
    completed_at = datetime.now(timezone.utc).isoformat()
    finalized = _facade()._finalize_vibe_result(
        synth=synth,
        employees=employees,
        ctx=version_ctx,
        digest_excerpt=digest_excerpt,
        meeting_excerpt=meeting_excerpt,
        surface_audit_excerpt=surface_excerpt,
    )
    if not finalized.get("ok"):
        return {
            "ok": False,
            "error": finalized.get("error") or "合成失败",
            "started_at": started_at,
            "completed_at": completed_at,
            "mode": mode_norm,
            "employee_count": len(employees),
            "updates_markdown": "",
            "patches_markdown": "",
            "model": finalized.get("model") or "",
            **version_ctx,
        }
    return {
        "ok": True,
        "error": "",
        "started_at": started_at,
        "completed_at": completed_at,
        "mode": mode_norm,
        "employee_count": len(employees),
        "digest_day": digest_day,
        "digest_subject": digest_subject,
        "updates_markdown": finalized.get("updates_markdown") or "",
        "patches_markdown": finalized.get("patches_markdown") or "",
        "model": finalized.get("model") or "",
        "synthesizer": finalized.get("synthesizer") or "",
        "fallback_reason": finalized.get("fallback_reason") or "",
        **version_ctx,
    }
