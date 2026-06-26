"""从每日摘要 + 编制员工生成 Vibe-Coding 预备 Markdown（更新清单 + 补丁清单）。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from html import unescape
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from modstore_server.all_hands_report import (
    _load_yuangon_employee_meta,
    _manifest_signals,
    _recent_failures,
    _report_one_employee,
    _resolve_employee_pairs,
    clamp_all_hands_max_employees,
)
from modstore_server.duty_roster import yuangon_area_for_pkg
from modstore_server.services.llm import resolve_platform_bench_llm

logger = logging.getLogger(__name__)

DigestVibeProgressCallback = Callable[[Dict[str, Any]], Awaitable[None]]

_VIBE_PREP_SYSTEM = """你是 MODstore 的 Vibe-Coding 编排秘书。
根据输入的「每日摘要节选」与「各 AI 员工岗位快照」，生成两份 Markdown，供后续 vibe-coding 自动改码使用。

硬性要求：
1. 仅基于输入事实归纳；不得编造不存在的文件、错误、或已完成的改动。
2. 输出必须是合法 JSON 对象，且只含两个键：
   - ``updates_markdown``：更新清单（文档同步、配置、监控、流程、依赖升级、测试补齐等非紧急维护）
   - ``patches_markdown``：补丁清单（需改代码/修 bug/补迁移/修测试失败的具体任务）
3. 两份 Markdown 各自以一级标题开头：
   - updates 首行必须是 ``# Vibe 预备 · 更新清单``
   - patches 首行必须是 ``# Vibe 预备 · 补丁清单``
4. 按员工 ``employee_id`` 分节（``## [employee_id] 显示名 · v{pack_version}``），每节含：
   - 职责一句
   - 员工包版本 ``pack_version``（来自 snapshot）
   - 建议 scope 路径（来自 snapshot）
   - 3–5 条可执行条目；**每条都必须以 `**P0**` / `**P1**` / `**P2**` 优先级前缀开头**，并按风险分级、**避免整节同一优先级**：
     · P0 = 影响线上/安全/认证，或该岗有近期失败需立即处理；
     · P1 = 契约/联调/集成漂移、重要重构或测试缺口；
     · P2 = 纯文档/README/runbook 补齐、低风险维护。
     （updates 偏维护，patches 偏 diff/修复；两份清单都要体现优先级梯度）
5. 简体中文；不要输出 JSON 以外的任何文字。
6. 版本号由服务端统一写入文首，你无需重复输出版本表。
7. 「进化事实信号」段落（pytest 失败 / incident / 性能探针）优先级高于三端截图分析；补丁清单须优先覆盖这些事实。"""


def resolve_vibe_prep_version_context(
    *,
    digest_day: str,
    digest_subject: str,
    record_id: int = 0,
    mode: str = "auto",
) -> Dict[str, Any]:
    """解析与每日摘要/Git 基线绑定的清单版本号（更新与补丁共享基线，后缀区分类型）。"""
    from modstore_server.daily_digest import _digest_git_branch_and_head, _repo_root

    git_branch, git_commit = _digest_git_branch_and_head(_repo_root())
    day = (digest_day or "").strip() or "unknown"
    rid = int(record_id or 0)
    branch = git_branch if git_branch and git_branch != "—" else "unknown"
    commit = git_commit if git_commit and git_commit != "—" else "unknown"
    base = f"{day}#{branch}+{commit}"
    if rid > 0:
        base = f"{base}#r{rid}"
    ctx: Dict[str, Any] = {
        "digest_day": day,
        "digest_subject": (digest_subject or "").strip(),
        "digest_record_id": rid,
        "git_branch": branch,
        "git_commit": commit,
        "base_version": base,
        "updates_version": f"{base}-updates",
        "patches_version": f"{base}-patches",
        "mode": str(mode or "auto"),
    }
    if rid > 0:
        try:
            from modstore_server.release_train import release_train_context_for_digest

            ctx.update(release_train_context_for_digest(rid))
        except Exception:
            pass
    else:
        try:
            from modstore_server.release_train import snapshot_public

            snap = snapshot_public()
            rt = str(snap.get("current") or "1.0.0.0")
            ctx.update(
                {
                    "release_train": rt,
                    "release_train_before": rt,
                    "release_train_after": rt,
                    "release_kind": "daily",
                }
            )
        except Exception:
            pass
    return ctx


def _version_header_block(kind: str, ctx: Dict[str, Any]) -> str:
    label = "更新清单" if kind == "updates" else "补丁清单"
    list_ver = ctx.get("updates_version") if kind == "updates" else ctx.get("patches_version")
    mode_label = "手动重跑" if str(ctx.get("mode") or "") == "manual" else "08:00 自动"
    rid = int(ctx.get("digest_record_id") or 0)
    archive = f"#{rid}" if rid > 0 else "—"
    return (
        f"| 字段 | 值 |\n"
        f"| --- | --- |\n"
        f"| 清单类型 | {label} |\n"
        f"| 清单版本 | `{list_ver}` |\n"
        f"| 基线版本 | `{ctx.get('base_version')}` |\n"
        f"| release_train | `{ctx.get('release_train', '—')}` |\n"
        f"| release_kind | {ctx.get('release_kind', 'daily')} |\n"
        f"| 摘要日期 | {ctx.get('digest_day')} |\n"
        f"| 摘要存档 | {archive} |\n"
        f"| Git | {ctx.get('git_branch')} @ {ctx.get('git_commit')} |\n"
        f"| 生成模式 | {mode_label} |\n"
    )


def _apply_version_stamp(kind: str, body: str, ctx: Dict[str, Any]) -> str:
    """在 Markdown 文首注入统一版本表（覆盖/替换 LLM 可能输出的旧版本块）。"""
    title = "# Vibe 预备 · 更新清单" if kind == "updates" else "# Vibe 预备 · 补丁清单"
    text = (body or "").strip()
    for known_h1 in ("# Vibe 预备 · 更新清单", "# Vibe 预备 · 补丁清单"):
        if text.startswith(known_h1):
            text = text[len(known_h1) :].lstrip()
            break
    text = re.sub(r"(?ms)^\| 字段 \| 值 \|\n(?:\|[^\n]*\|\n)+", "", text, count=1).lstrip()
    header = _version_header_block(kind, ctx)
    return f"{title}\n\n{header}\n{text}".rstrip() + "\n"


def _employee_pack_version(pkg_id: str) -> str:
    try:
        from modstore_server.employee_runtime import load_employee_pack
        from modstore_server.models import get_session_factory

        with get_session_factory()() as session:
            pack = load_employee_pack(session, pkg_id)
        man = pack.get("manifest") if isinstance(pack.get("manifest"), dict) else {}
        v2 = man.get("employee_config_v2") if isinstance(man, dict) else {}
        ident = v2.get("identity") if isinstance(v2.get("identity"), dict) else {}
        ver = str(ident.get("version") or man.get("version") or "").strip()
        return ver or "—"
    except Exception:
        return "—"


def _build_template_vibe_markdowns(
    *,
    employees: List[Dict[str, Any]],
    ctx: Dict[str, Any],
    digest_excerpt: str = "",
    meeting_excerpt: str = "",
    surface_audit_excerpt: str = "",
) -> Tuple[str, str]:
    """无 Bench LLM 或合成失败时的确定性清单。

    只根据摘要/员工大会/巡检中的明确事实产出任务；没有事实信号时不再为全员生成
    ``暂无 recent_failures`` 泛任务，避免自进化链路派发空补丁。
    """
    update_lines: List[str] = []
    patch_lines: List[str] = []
    emp_by_id = {str(e.get("employee_id") or ""): e for e in employees if e.get("employee_id")}
    evidence = "\n".join(
        x.strip()
        for x in (digest_excerpt, meeting_excerpt, surface_audit_excerpt)
        if str(x or "").strip()
    )
    evidence_lower = evidence.lower()

    def _emp_section(pid: str, fallback_name: str = "") -> Tuple[str, str, str]:
        emp = emp_by_id.get(pid) or {}
        name = str(emp.get("name") or fallback_name or pid)
        pack_ver = str(emp.get("pack_version") or _employee_pack_version(pid) or "—")
        scope = emp.get("scope_globs") if isinstance(emp.get("scope_globs"), list) else []
        scope_txt = "、".join(f"`{s}`" for s in scope[:6]) or "（manifest 未声明 scope）"
        return name, pack_ver, scope_txt

    def _add_update(pid: str, fallback_name: str, items: List[str]) -> None:
        name, pack_ver, scope_txt = _emp_section(pid, fallback_name)
        update_lines.append(f"## [{pid}] {name} · v{pack_ver}\n")
        update_lines.append(f"- scope：{scope_txt}")
        update_lines.extend(items)
        update_lines.append("")

    def _add_patch(pid: str, fallback_name: str, items: List[str]) -> None:
        name, pack_ver, scope_txt = _emp_section(pid, fallback_name)
        patch_lines.append(f"## [{pid}] {name} · v{pack_ver}\n")
        patch_lines.append(f"- scope：{scope_txt}")
        patch_lines.extend(items)
        patch_lines.append("")

    ps_title_issue = "智能对话 - xcagi" in evidence_lower and (
        "标题" in evidence or "title" in evidence_lower or "元数据" in evidence
    )
    if ps_title_issue:
        ps_items = [
            "- **P1** 修复 P-S 页面标题/Head 管理：巡检显示多个业务路由标题均渲染为「智能对话 - XCAGI」，需按当前 route 写入正确 title",
            "- **P2** 增加路由标题一致性断言，覆盖 `/ai-ecosystem`、`/products`、`/customers`、`/orders`、`/inventory`、`/settings` 等巡检页面",
        ]
        _add_patch("vibe-coding-maintainer", "Vibe Coding 维护员", ps_items)
        _add_patch(
            "fhd-core-maintainer",
            "FHD Core 维护员",
            [
                "- **P1** 审核前端全局标题服务/路由元数据契约，确保页面切换时不会复用首页标题",
                "- **P2** 将标题契约写入 P-S 巡检 runbook，避免后续页面新增时漏配 metadata",
            ],
        )
        _add_update(
            "test-qa-runner",
            "测试执行员",
            [
                "- **P2** 把 P-S title/route 对照表纳入每日巡检验收项，失败时生成可定位的页面清单",
            ],
        )

    if any(x in evidence for x in ("ERR_CONNECTION_CLOSED", "ERR_HTTP2_PING_FAILED")):
        _add_patch(
            "marketing-site-builder",
            "营销站点构建员",
            [
                "- **P1** 排查 P-W 静态站资源加载失败：巡检记录包含 ERR_CONNECTION_CLOSED / ERR_HTTP2_PING_FAILED，需定位 CDN、HTTP/2 或资源引用问题",
                "- **P2** 为 P-W 资源加载失败补充可重复巡检页面清单与回归步骤",
            ],
        )

    if "404" in evidence and "catalog" in evidence_lower:
        _add_patch(
            "market-frontend-dev",
            "市场前端开发员",
            [
                "- **P1** 修复 AI 员工商品页 catalog 404：巡检提到 catalog/40、catalog/50、catalog/41 等商品链接异常",
                "- **P2** 增加商品详情页存在性检查，避免市场入口指向不存在 SKU",
            ],
        )

    if "403" in evidence and ("沙箱" in evidence or "sandbox" in evidence_lower):
        _add_update(
            "sandbox-tester",
            "沙箱测试员",
            [
                "- **P2** 复核沙箱测试页 403 是否符合权限预期；若是预期行为，将巡检断言改为认证态校验",
            ],
        )

    # recent_failures 是硬事实信号；只为有失败的员工生成补丁，不再为无失败员工生成空泛任务。
    for emp in employees:
        pid = str(emp.get("employee_id") or "")
        if not pid:
            continue
        name = str(emp.get("name") or pid)
        pack_ver = str(emp.get("pack_version") or "—")
        scope = emp.get("scope_globs") if isinstance(emp.get("scope_globs"), list) else []
        scope_txt = "、".join(f"`{s}`" for s in scope[:6]) or "（manifest 未声明 scope）"
        depends = emp.get("depends_on") if isinstance(emp.get("depends_on"), list) else []
        handlers = emp.get("handlers") if isinstance(emp.get("handlers"), list) else []
        failures = (
            emp.get("recent_failures") if isinstance(emp.get("recent_failures"), list) else []
        )
        domain = str(emp.get("domain") or "").strip()

        has_failures = bool(failures)
        if not has_failures:
            continue
        dep_pr = "P0" if has_failures else "P1"
        update_lines.append(f"## [{pid}] {name} · v{pack_ver}\n")
        update_lines.append(f"- 职责域：{domain or '（见 manifest）'}")
        update_lines.append(f"- scope：{scope_txt}")
        if depends:
            update_lines.append(
                f"- **{dep_pr}** 核对 depends_on 文档与联调说明是否仍与 manifest 一致"
            )
            for dep in depends[:3]:
                update_lines.append(f"  - 依赖 `{dep}`：同步接口/契约说明")
        if handlers:
            update_lines.append("- **P2** 复核 handlers 注册与 yuangon 目录结构一致")
            for h in handlers[:3]:
                update_lines.append(f"  - handler `{h}`")
        update_lines.append("")

        patch_lines.append(f"## [{pid}] {name} · v{pack_ver}\n")
        patch_lines.append(f"- scope：{scope_txt}")
        _TRANSIENT_KEYWORDS = (
            "disconnected",
            "timeout",
            "timed out",
            "connection",
            "remotedisconnected",
        )
        for fail in failures[:2]:
            if isinstance(fail, dict):
                msg = str(fail.get("message") or fail.get("error") or fail.get("summary") or fail)
                fail_task = str(fail.get("task") or "")
            else:
                msg = str(fail)
                fail_task = ""
            msg_lower = msg.lower()
            is_transient = any(kw in msg_lower for kw in _TRANSIENT_KEYWORDS)
            if is_transient:
                suffix = "（基础设施/LLM 瞬断，优先重试而非改代码）"
                patch_lines.append(f"- **P0** 修复近期失败：{fail_task[:80] or msg[:160]}{suffix}")
            else:
                patch_lines.append(f"- **P0** 修复近期失败：{msg[:240]}")
        patch_lines.append("")

    if not update_lines and employees:
        for emp in employees[:12]:
            pid = str(emp.get("employee_id") or "").strip()
            if not pid:
                continue
            name, pack_ver, scope_txt = _emp_section(pid)
            update_lines.append(f"## [{pid}] {name} · v{pack_ver}\n")
            update_lines.append(f"- scope：{scope_txt}")
            update_lines.append("- 当前无明确证据驱动更新；保留员工版本快照用于审计。")
            update_lines.append("")

    if not patch_lines and employees:
        for emp in employees[:12]:
            pid = str(emp.get("employee_id") or "").strip()
            if not pid:
                continue
            name, pack_ver, scope_txt = _emp_section(pid)
            patch_lines.append(f"## [{pid}] {name} · v{pack_ver}\n")
            patch_lines.append(f"- scope：{scope_txt}")
            patch_lines.append("- 当前无明确证据驱动补丁；不派发空补丁。")
            patch_lines.append("")

    updates_body = "\n".join(update_lines).strip() or "（无证据驱动更新）"
    patches_body = "\n".join(patch_lines).strip() or "（无证据驱动补丁）"
    return (
        _apply_version_stamp("updates", updates_body, ctx),
        _apply_version_stamp("patches", patches_body, ctx),
    )


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
        updates = _apply_version_stamp("updates", str(synth.get("updates_markdown") or ""), ctx)
        patches = _apply_version_stamp("patches", str(synth.get("patches_markdown") or ""), ctx)
        patches, backlog_meta = _merge_event_backlog_into_patches(patches)
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

    updates, patches = _build_template_vibe_markdowns(
        employees=employees,
        ctx=ctx,
        digest_excerpt=digest_excerpt,
        meeting_excerpt=meeting_excerpt,
        surface_audit_excerpt=surface_audit_excerpt,
    )
    patches, backlog_meta = _merge_event_backlog_into_patches(patches)
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


def _merge_event_backlog_into_patches(patches_markdown: str) -> tuple[str, Dict[str, Any]]:
    """事件轨 M2：合并 ``six_line_digest_backlog.jsonl`` 进补丁清单。"""
    if (os.environ.get("MODSTORE_EVENT_BACKLOG_MERGE_ENABLED", "1") or "").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return patches_markdown, {"merged_count": 0, "skipped": True}
    try:
        from modstore_server.six_line_event_router import merge_event_backlog_into_vibe_patches

        return merge_event_backlog_into_vibe_patches(patches_markdown, consume=True)
    except Exception:
        logger.exception("digest_vibe_prep: event backlog merge failed")
        return patches_markdown, {"merged_count": 0, "error": "merge_failed"}


def _strip_html_to_text(raw: str, *, max_chars: int = 12000) -> str:
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "…"
    return text


def _lightweight_employee_snapshot(pkg_id: str, display_name: str) -> Dict[str, Any]:
    signals = _manifest_signals(pkg_id)
    failures = _recent_failures(pkg_id, limit=4)
    meta = _load_yuangon_employee_meta(pkg_id)
    scope = []
    outline = signals.get("employee_config_v2_outline") if isinstance(signals, dict) else {}
    if isinstance(outline, dict):
        scope = list(outline.get("workspace_scope_globs") or [])[:8]
    return {
        "employee_id": pkg_id,
        "name": display_name,
        "pack_version": _employee_pack_version(pkg_id),
        "area": yuangon_area_for_pkg(pkg_id) or signals.get("area") or "",
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
        out.append(_lightweight_employee_snapshot(pid, name))
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
    bench_prov, bench_mdl = resolve_platform_bench_llm()
    if not bench_prov or not bench_mdl:
        return []

    other_ids = [p for p, _ in pairs]
    sem = asyncio.Semaphore(max(1, min(concurrency, 4)))
    done = 0
    total = len(pairs)
    lock = asyncio.Lock()
    rows: List[Dict[str, Any]] = []

    async def _one(pid: str, name: str) -> Dict[str, Any]:
        nonlocal done
        async with sem:
            row = await _report_one_employee(
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
        base = _lightweight_employee_snapshot(pid, name)
        base["report_markdown"] = str(row.get("report_markdown") or "")[:2500]
        base["report_status"] = str(row.get("status") or "")
        return base

    rows = await asyncio.gather(*[_one(p, n) for p, n in pairs])
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
    except Exception:
        logger.exception("persist_vibe_prep_on_digest_record failed id=%s", record_id)


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
            build_digest_vibe_prep(
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
    except Exception as exc:  # noqa: BLE001
        logger.exception("run_digest_vibe_prep_sync failed")
        return {
            "ok": False,
            "error": str(exc),
            "updates_markdown": "",
            "patches_markdown": "",
            "mode": mode,
        }


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
    except Exception:
        logger.debug("digest_vibe_prep: evolution signals unavailable", exc_info=True)

    return (
        f"模式：{mode}\n"
        f"摘要日期：{digest_day}\n"
        f"摘要主题：{digest_subject}\n"
        f"基线版本：{ver.get('base_version') or '（待写入）'}\n"
        f"更新清单版本：{ver.get('updates_version') or ''}\n"
        f"补丁清单版本：{ver.get('patches_version') or ''}\n\n"
        f"## 进化事实信号（优先于截图）\n{evolution_block}\n\n"
        f"## 每日摘要正文节选\n{digest_excerpt or '（无）'}\n\n"
        f"## 员工大会摘要节选\n{meeting_excerpt or '（无）'}\n\n"
        f"## 三端页面截图巡检节选（辅助 · P-W 网站 · P-S 软件 · P-App 移动）\n{surface_audit_excerpt or '（无）'}\n\n"
        f"## 员工快照 JSON（{len(employees)} 人）\n```json\n{emp_json}\n```"
    )


async def _synthesize_vibe_markdowns(
    *,
    user_content: str,
    user_id: int,
) -> Dict[str, Any]:
    bench_prov, bench_mdl = resolve_platform_bench_llm()
    if not bench_prov or not bench_mdl:
        return {
            "ok": False,
            "error": "平台 Bench LLM 未配置",
            "updates_markdown": "",
            "patches_markdown": "",
            "model": "",
        }

    messages = [
        {"role": "system", "content": _VIBE_PREP_SYSTEM},
        {"role": "user", "content": user_content},
    ]
    try:
        from modstore_server.models import get_session_factory
        from modstore_server.services.llm import chat_dispatch_via_session

        sf = get_session_factory()
        with sf() as db:
            result = await chat_dispatch_via_session(
                db,
                int(user_id or 0),
                bench_prov,
                bench_mdl,
                messages,
                max_tokens=4096,
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("digest_vibe_prep synthesize failed")
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
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            try:
                parsed = json.loads(m.group(0))
            except json.JSONDecodeError:
                parsed = {}

    updates = str(parsed.get("updates_markdown") or "").strip()
    patches = str(parsed.get("patches_markdown") or "").strip()
    if not updates and not patches:
        return {
            "ok": False,
            "error": "LLM 未返回有效 JSON（缺少 updates_markdown / patches_markdown）",
            "updates_markdown": "",
            "patches_markdown": "",
            "model": f"{bench_prov}/{bench_mdl}",
            "raw_preview": raw[:800],
        }

    if updates and not updates.startswith("#"):
        updates = "# Vibe 预备 · 更新清单\n\n" + updates
    if patches and not patches.startswith("#"):
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
    cap = clamp_all_hands_max_employees(max_employees, default=52 if mode_norm == "auto" else 16)
    version_ctx = resolve_vibe_prep_version_context(
        digest_day=digest_day,
        digest_subject=digest_subject,
        record_id=record_id,
        mode=mode_norm,
    )

    async def _emit(payload: Dict[str, Any]) -> None:
        if not progress_cb:
            return
        try:
            await progress_cb(payload)
        except Exception as exc:  # noqa: BLE001
            logger.debug("digest_vibe_prep progress cb failed: %s", exc)

    pairs = _resolve_employee_pairs(employee_ids, max_employees=cap)
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
        digest_excerpt = _strip_html_to_text(digest_body_html)
    meeting_excerpt = _strip_html_to_text(meeting_minutes_html, max_chars=6000)
    surface_excerpt = (surface_audit_excerpt or "").strip()

    if mode_norm == "manual":
        employees = await _collect_manual_reports(
            pairs,
            user_id=user_id,
            concurrency=concurrency,
            progress_cb=progress_cb,
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
        employees = await _collect_lightweight(pairs, progress_cb=progress_cb)

    await _emit(
        {
            "stage": "synthesize",
            "total": len(employees),
            "completed": len(employees),
            "mode": mode_norm,
        }
    )

    synth = await _synthesize_vibe_markdowns(
        user_content=_build_llm_user_content(
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
    finalized = _finalize_vibe_result(
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
