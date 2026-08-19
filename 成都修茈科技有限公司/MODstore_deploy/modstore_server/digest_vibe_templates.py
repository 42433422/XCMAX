# ruff: noqa
"""Versioning and deterministic template generation for digest vibe prep."""
from __future__ import annotations
import importlib
import logging
import os
import re
from typing import Any, Awaitable, Callable, Dict, List, Tuple

logger = logging.getLogger("modstore_server.digest_vibe_prep")
DigestVibeProgressCallback = Callable[[Dict[str, Any]], Awaitable[None]]


def _facade():
    return importlib.import_module("modstore_server.digest_vibe_prep")


def resolve_vibe_prep_version_context(
    *, digest_day: str, digest_subject: str, record_id: int = 0, mode: str = "auto"
) -> Dict[str, Any]:
    """解析与每日摘要/Git 基线绑定的清单版本号（更新与补丁共享基线，后缀区分类型）。"""
    from modstore_server.daily_digest import _digest_git_branch_and_head, _repo_root

    (git_branch, git_commit) = _digest_git_branch_and_head(_repo_root())
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
    return f"| 字段 | 值 |\n| --- | --- |\n| 清单类型 | {label} |\n| 清单版本 | `{list_ver}` |\n| 基线版本 | `{ctx.get('base_version')}` |\n| release_train | `{ctx.get('release_train', '—')}` |\n| release_kind | {ctx.get('release_kind', 'daily')} |\n| 摘要日期 | {ctx.get('digest_day')} |\n| 摘要存档 | {archive} |\n| Git | {ctx.get('git_branch')} @ {ctx.get('git_commit')} |\n| 生成模式 | {mode_label} |\n"


def _apply_version_stamp(kind: str, body: str, ctx: Dict[str, Any]) -> str:
    """在 Markdown 文首注入统一版本表（覆盖/替换 LLM 可能输出的旧版本块）。"""
    title = "# Vibe 预备 · 更新清单" if kind == "updates" else "# Vibe 预备 · 补丁清单"
    text = (body or "").strip()
    for known_h1 in ("# Vibe 预备 · 更新清单", "# Vibe 预备 · 补丁清单"):
        if text.startswith(known_h1):
            text = text[len(known_h1) :].lstrip()
            break
    text = re.sub("(?ms)^\\| 字段 \\| 值 \\|\\n(?:\\|[^\\n]*\\|\\n)+", "", text, count=1).lstrip()
    header = _facade()._version_header_block(kind, ctx)
    return f"{title}\n\n{header}\n{text}".rstrip() + "\n"


def _include_meta_maintenance_updates() -> bool:
    raw = (os.environ.get("MODSTORE_VIBE_PREP_INCLUDE_META_UPDATES") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _include_surface_hint_tasks() -> bool:
    raw = (os.environ.get("MODSTORE_VIBE_PREP_INCLUDE_SURFACE_HINTS") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _is_actionable_failure(fail: Any, msg: str) -> bool:
    msg_lower = str(msg or "").lower()
    transient_keywords = (
        "disconnected",
        "timeout",
        "timed out",
        "connection",
        "remotedisconnected",
    )
    if any((kw in msg_lower for kw in transient_keywords)):
        return False
    if not isinstance(fail, dict):
        return True
    status = str(fail.get("status") or "").strip().lower()
    err = str(fail.get("error") or "").strip()
    tokens = int(fail.get("llm_tokens") or 0)
    task = str(fail.get("task") or "")
    if status in ("skipped", "warning") and (not err):
        return False
    if status == "failed" and (not err) and (tokens <= 0) and ("员工大会" in task):
        return False
    return True


def _short_task_reason(reason: str, *, limit: int = 180) -> str:
    text = re.sub("\\s+", " ", str(reason or "")).strip()
    if len(text) <= limit:
        return text or "未知原因"
    return text[: limit - 1].rstrip() + "…"


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
    fallback_reason: str = "",
) -> Tuple[str, str]:
    """无 Bench LLM 或合成失败时的确定性清单。

    只根据摘要/员工大会/巡检中的明确事实产出任务；没有事实信号时不再为全员生成
    ``暂无 recent_failures`` 泛任务，避免自进化链路派发空补丁。
    """
    update_lines: List[str] = []
    patch_lines: List[str] = []
    emp_by_id = {str(e.get("employee_id") or ""): e for e in employees if e.get("employee_id")}
    evidence = "\n".join(
        (
            x.strip()
            for x in (digest_excerpt, meeting_excerpt, surface_audit_excerpt)
            if str(x or "").strip()
        )
    )
    evidence_lower = evidence.lower()

    def _emp_section(pid: str, fallback_name: str = "") -> Tuple[str, str, str]:
        emp = emp_by_id.get(pid) or {}
        name = str(emp.get("name") or fallback_name or pid)
        pack_ver = str(emp.get("pack_version") or _facade()._employee_pack_version(pid) or "—")
        scope = emp.get("scope_globs") if isinstance(emp.get("scope_globs"), list) else []
        scope_txt = "、".join((f"`{s}`" for s in scope[:6])) or "（manifest 未声明 scope）"
        return (name, pack_ver, scope_txt)

    def _add_update(pid: str, fallback_name: str, items: List[str]) -> None:
        (name, pack_ver, scope_txt) = _emp_section(pid, fallback_name)
        update_lines.append(f"## [{pid}] {name} · v{pack_ver}\n")
        update_lines.append(f"- scope：{scope_txt}")
        update_lines.extend(items)
        update_lines.append("")

    def _add_patch(pid: str, fallback_name: str, items: List[str]) -> None:
        (name, pack_ver, scope_txt) = _emp_section(pid, fallback_name)
        patch_lines.append(f"## [{pid}] {name} · v{pack_ver}\n")
        patch_lines.append(f"- scope：{scope_txt}")
        patch_lines.extend(items)
        patch_lines.append("")

    reason = _facade()._short_task_reason(fallback_reason)
    if str(fallback_reason or "").strip():
        _add_patch(
            "modstore-backend-api",
            "MODstore 后端 API 员",
            [
                f"- **P0** 修复 Vibe 预备任务生成断点：{reason}；确保 Bench LLM 输出合法 JSON，或解析器能提取 updates_markdown / patches_markdown"
            ],
        )
        _add_patch(
            "task-router-officer",
            "任务派发员",
            [
                "- **P0** 修复 Vibe fallback 任务责任路由：LLM 合成失败时不能把所有断点挂给 daily-orchestrator，需按实际责任员工进入 action-items 和 AI 交流圈"
            ],
        )
        _add_patch(
            "test-qa-runner",
            "测试质量运行员",
            [
                "- **P1** 增加回归断言：template fallback 发生时必须进入 action-items、产线执行和 AI 交流圈，不能只留下会议纪要"
            ],
        )
    if _facade()._include_surface_hint_tasks():
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
                    "- **P2** 把 P-S title/route 对照表纳入每日巡检验收项，失败时生成可定位的页面清单"
                ],
            )
        if any((x in evidence for x in ("ERR_CONNECTION_CLOSED", "ERR_HTTP2_PING_FAILED"))):
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
                    "- **P2** 复核沙箱测试页 403 是否符合权限预期；若是预期行为，将巡检断言改为认证态校验"
                ],
            )
    for emp in employees:
        pid = str(emp.get("employee_id") or "")
        if not pid:
            continue
        name = str(emp.get("name") or pid)
        pack_ver = str(emp.get("pack_version") or "—")
        scope = emp.get("scope_globs") if isinstance(emp.get("scope_globs"), list) else []
        scope_txt = "、".join((f"`{s}`" for s in scope[:6])) or "（manifest 未声明 scope）"
        depends = emp.get("depends_on") if isinstance(emp.get("depends_on"), list) else []
        handlers = emp.get("handlers") if isinstance(emp.get("handlers"), list) else []
        failures = (
            emp.get("recent_failures") if isinstance(emp.get("recent_failures"), list) else []
        )
        domain = str(emp.get("domain") or "").strip()
        has_failures = bool(failures)
        if not has_failures:
            continue
        if _facade()._include_meta_maintenance_updates() and (depends or handlers):
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
        actionable_failures: List[Tuple[str, str]] = []
        for fail in failures[:2]:
            if isinstance(fail, dict):
                msg = str(fail.get("message") or fail.get("error") or fail.get("summary") or fail)
                fail_task = str(fail.get("task") or "")
            else:
                msg = str(fail)
                fail_task = ""
            if _facade()._is_actionable_failure(fail, msg):
                actionable_failures.append((msg, fail_task))
        if not actionable_failures:
            continue
        patch_lines.append(f"## [{pid}] {name} · v{pack_ver}\n")
        patch_lines.append(f"- scope：{scope_txt}")
        for msg, _fail_task in actionable_failures:
            patch_lines.append(f"- **P0** 修复近期失败：{msg[:240]}")
        patch_lines.append("")
    if not update_lines and employees:
        update_lines.append("### 员工版本快照（无派发）")
        update_lines.append("")
        update_lines.append("| employee | version |")
        update_lines.append("| --- | --- |")
        for emp in employees[:12]:
            pid = str(emp.get("employee_id") or "").strip()
            if not pid:
                continue
            (_name, pack_ver, _scope_txt) = _emp_section(pid)
            update_lines.append(f"| `{pid}` | v{pack_ver} |")
        update_lines.append("")
        update_lines.append("（无证据驱动更新；不生成派发任务）")
    if not patch_lines and employees:
        patch_lines.append("（无证据驱动补丁；不生成派发任务）")
    updates_body = "\n".join(update_lines).strip() or "（无证据驱动更新）"
    patches_body = "\n".join(patch_lines).strip() or "（无证据驱动补丁）"
    return (
        _facade()._apply_version_stamp("updates", updates_body, ctx),
        _facade()._apply_version_stamp("patches", patches_body, ctx),
    )
