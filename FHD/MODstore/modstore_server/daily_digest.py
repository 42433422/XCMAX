"""每日运维 / 质量摘要邮件（APScheduler 触发）。

环境变量：
- ``MODSTORE_DAILY_DIGEST_ENABLED``：默认 ``1``，设为 ``0`` 关闭。
- ``MODSTORE_DAILY_DIGEST_EMAIL``：收件人，默认 ``1499383833@qq.com``；支持逗号或分号分隔多个地址。
- ``MODSTORE_DAILY_DIGEST_NOTIFY_USER_IDS``：可选，逗号分隔的用户 ID；摘要邮件**至少一封投递成功**后写入站内通知（SYSTEM）。
- ``MODSTORE_DAILY_DIGEST_RUN_PYTEST``：设为 ``1`` 时在摘要中附带 ``pytest tests/ -q``（可能较慢，超时 15 分钟）。
- ``MODSTORE_REPO_ROOT``：仓库根（与运维 handler 一致）。
- ``MODSTORE_GIT_BRANCH`` / ``MODSTORE_GIT_COMMIT``：摘要「仓库分支 / 最新提交」。生产镜像通常无 ``git`` 与 ``.git``，可设环境变量或 ``/app/.modstore_build.json``；若进程能在 ``MODSTORE_REPO_ROOT``（或默认部署根）下解析到 **Git 工作副本**，则**优先于** ``.modstore_build.json`` 显示实时分支与提交（环境变量仍最优先）。亦支持 ``MODSTORE_GIT_SHA`` / ``GIT_SHA`` / ``COMMIT_SHA``（与 ``/api/health`` 一致）。另有别名 ``GIT_BRANCH``、``GIT_COMMIT``、``VCS_REF``、``SOURCE_COMMIT``。
- ``MODSTORE_DAILY_BRIEF_ENABLED``：设为 ``1`` 时在摘要中追加各 catalog 在岗员工的「工作内容摘要 + 新方案」段落（默认 ``0``）。
- ``MODSTORE_DAILY_BRIEF_MAX``：最多生成几条岗位方案（默认 ``16``）。
- ``MODSTORE_DAILY_BRIEF_GROUND_YUANGON``：岗位简报是否预读 ``yuangon/<area>/<pkg_id>/`` 下真实文件注入 LLM（默认 ``1``；关闭设 ``0``）。依赖 ``MODSTORE_REPO_ROOT`` 含 yuangon 目录。
- ``MODSTORE_DAILY_BRIEF_GROUND_MAX_CHARS``：上述节选总字符上限（默认 ``60000``，最大可调到 ``200000``）。
- ``MODSTORE_DAILY_BRIEF_STRICT_GROUNDING``：设为 ``1`` 时岗位简报使用「可核对依据」版任务提示（三条建议须带 **依据** 行；默认 ``0``）。
- ``MODSTORE_DAILY_BRIEF_EXTRA_GLOBS_JSON``：JSON 对象，键为 ``pkg_id`` 或 ``"*"``，值为相对岗位目录的 glob 字符串数组，合并进节选（在固定清单与 ``prompts``/``tasks`` 之后）。
- 员工包 ``employee_config_v2.metadata.daily_brief_ground_paths``：同上，每包额外 glob 列表（与 env 合并）。
- ``MODSTORE_DAILY_DIGEST_CONSISTENCY``：设为 ``0`` 时跳过 ``yuangon`` 文档一致性扫描（默认启用；大仓库可关闭以缩短发送耗时）。
- ``MODSTORE_DIGEST_AUDIT_HINT``：设为 ``1`` 时在摘要邮件中附带运维审计/事件计数为何常为 0 的说明（scheduler、DB、nginx 路径）。
- ``MODSTORE_DAILY_VIBE_PREP_ENABLED``（默认 ``1``）：08:00 摘要落库后自动跑 Vibe 预备双 Markdown（更新 + 补丁），写入 ``daily_digest_records``。
- ``MODSTORE_DAILY_VIBE_PREP_MAX_EMPLOYEES``（默认 ``52``）：自动任务汇总员工上限。
- ``MODSTORE_DAILY_VIBE_PREP_USER_ID``：自动任务 bench LLM 使用的用户 ID（默认同 ``MODSTORE_DAILY_BRIEF_USER_ID`` 或 ``0``）。
- ``MODSTORE_DAILY_VIBE_LINE_DISPATCH_ENABLED``（默认 ``1``）：Vibe 预备完成后将更新/补丁清单拆分写入 P-W / P-S / S-R 三产线字段。
- ``MODSTORE_DAILY_VIBE_EXECUTE_ENABLED``（默认 ``1``）：08:15 cron 消费 P-S + P-App 补丁清单并 ``dispatch_subtasks``（Phase A，不跑 P3–P9）。
- ``MODSTORE_DAILY_VIBE_EXECUTE_HOUR`` / ``MINUTE`` / ``TZ``：执行 cron 时刻（默认 08:15 北京时间）。
- ``MODSTORE_DAILY_VIBE_EXECUTE_PRIORITIES``：逗号分隔优先级过滤（默认 ``P0,P1,P2``）。
- ``MODSTORE_DAILY_VIBE_EXECUTE_MAX_UNITS``：单次最多派发条目数（默认 ``32``）。
- ``MODSTORE_DAILY_MEETING_USER_ID``（默认 ``MODSTORE_DAILY_BRIEF_USER_ID`` 或 ``0``）。
- ``MODSTORE_DAILY_SURFACE_AUDIT_ENABLED``（默认 ``1``）：08:00 摘要内 P-W 网站 / P-S 软件 / P-App 移动面 Playwright 截图与 console 分析（见 ``daily_digest_surface_audit.py``）。
- ``MODSTORE_DAILY_SURFACE_ANALYSIS_ENABLED``（默认 ``1``）：三端每条产线由「对应员工」bench LLM 生成现状 / 异常 / 改进建议分析；未配置 bench LLM 时回退规则化摘要。
- ``MODSTORE_DAILY_SURFACE_PPT_ENABLED``（默认 ``1``）：把三端截图 + 分析拼成 PowerPoint 作为邮件附件（见 ``daily_digest_surface_ppt.py``）。
- ``MODSTORE_DAILY_SURFACE_AUDIT_BASE_URL``：巡检根 URL（默认 ``https://xiu-ci.com``）。
- ``MODSTORE_APPROVAL_AUTHORIZED_FROM`` / ``MODSTORE_APPROVAL_TOKEN_TTL_HOURS``：回信审批白名单与令牌 TTL；每日摘要**无论是否有待审改动**都会附带一枚 **身份校验** 令牌（``kind=digest_identity``，6 位十六进制）；有待审分支时表格内另有按行的 ``approve_one``。``digest_identity`` 在摘要生成后即写入 ``OpsApprovalToken``（与存档 HTML 一致），**不依赖**邮件是否投递成功；按行 ``approve_one`` 仍仅在至少一封摘要邮件投递成功后才入库，避免未发邮件即可部署。
- ``MODSTORE_TLS_CERT_PATHS``：逗号/分号分隔的 PEM 证书路径（用于 TLS 到期巡检段落）；未配置则跳过。
- ``CERT_EXPIRY_INFO_DAYS`` / ``CERT_EXPIRY_WARN_DAYS`` / ``CERT_EXPIRY_CRIT_DAYS``：证书分级阈值（默认 60 / 30 / 14 天）；WARNING/CRITICAL 会写入 ``security.alert`` 事件。
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from sqlalchemy import func

from modstore_server.email_service import (
    send_html_email_with_attachments,
    send_simple_html_email,
)
from modstore_server.models import (
    CatalogItem,
    EmployeeExecutionMetric,
    IncidentEvent,
    DailyDigestRecord,
    OpsActionAuditLog,
    OpsApprovalToken,
    OpsStagedChange,
    get_session_factory,
)

logger = logging.getLogger(__name__)


def digest_calendar_day() -> str:
    """日更 ``day`` 字段与邮件标题：默认 Asia/Shanghai 日历日（与正文 CST 行一致）。"""
    tz_name = (os.environ.get("MODSTORE_DAILY_DIGEST_TZ") or "Asia/Shanghai").strip()
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

DEFAULT_DIGEST_EMAIL = "1499383833@qq.com"


def _new_unique_ops_token_plain(
    existing_hashes: set[str] | None = None,
    *,
    session: Any | None = None,
    attempts: int = 64,
) -> Tuple[str, str]:
    """Return a 6-hex token and sha256 hash that do not collide with stored tokens."""
    seen = existing_hashes if existing_hashes is not None else set()
    for _ in range(max(1, attempts)):
        plain = secrets.token_hex(3).upper()
        th = hashlib.sha256(plain.encode("utf-8")).hexdigest()
        if th in seen:
            continue
        if session is not None:
            exists = session.query(OpsApprovalToken.id).filter(OpsApprovalToken.token_hash == th).first()
            if exists:
                seen.add(th)
                continue
        seen.add(th)
        return plain, th
    raise RuntimeError("failed to generate a unique daily digest approval token")


def parse_daily_digest_recipient_emails(raw: str) -> List[str]:
    """解析 ``MODSTORE_DAILY_DIGEST_EMAIL``：逗号或分号分隔，去空白，校验含 ``@``。"""
    if not (raw or "").strip():
        return []
    out: List[str] = []
    for chunk in raw.replace(";", ",").split(","):
        e = chunk.strip()
        if e and "@" in e:
            out.append(e)
    return out


def _notify_daily_digest_in_app(subject: str, digest_delivered: bool) -> None:
    """摘要投递成功后，向配置的 ``MODSTORE_DAILY_DIGEST_NOTIFY_USER_IDS`` 发站内通知。"""
    if not digest_delivered:
        return
    raw = (os.environ.get("MODSTORE_DAILY_DIGEST_NOTIFY_USER_IDS") or "").strip()
    if not raw:
        return
    ids: List[int] = []
    for part in raw.split(","):
        p = part.strip()
        if p.isdigit():
            ids.append(int(p))
    if not ids:
        return
    try:
        from modstore_server.notification_service import NotificationType, create_notification

        body = f"MODstore 每日摘要邮件已投递：{subject}。也可在邮箱中查看全文。"
        for uid in ids:
            create_notification(
                user_id=uid,
                notification_type=NotificationType.SYSTEM,
                title="每日摘要已发送",
                content=body,
                data={"kind": "daily_digest", "subject": subject},
            )
        logger.info("daily digest in-app notifications sent user_ids=%s", ids)
    except Exception:
        logger.exception("daily digest in-app notify failed")


def _html_to_text_excerpt(body_html: str) -> str:
    """Make a readable full-text copy for search/list views while keeping the original HTML."""
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", body_html or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _persist_daily_digest_record(
    *,
    subject: str,
    day: str,
    body_html: str,
    meeting_minutes_html: str,
    recipients: Sequence[str],
    delivery_rows: Sequence[Dict[str, Any]],
    delivered: bool,
) -> int | None:
    """Store the same daily digest that was emailed so the admin UI can review it later."""
    try:
        sf = get_session_factory()
        with sf() as session:
            row = DailyDigestRecord(
                day=day,
                subject=subject,
                body_html=body_html,
                body_text=_html_to_text_excerpt(body_html),
                meeting_minutes_html=meeting_minutes_html,
                recipients_json=json.dumps(list(recipients), ensure_ascii=False),
                delivery_json=json.dumps(list(delivery_rows), ensure_ascii=False, default=str),
                delivered=bool(delivered),
                source="daily_digest",
            )
            session.add(row)
            session.flush()
            record_id = int(row.id)
            session.commit()
            return record_id
    except Exception:
        logger.exception("daily digest: persist record failed")
        return None


def _run_scheduled_digest_vibe_prep(
    *,
    record_id: int,
    day: str,
    subject: str,
    body_html: str,
    body_text: str,
    meeting_minutes_html: str,
    surface_audit_excerpt: str = "",
) -> None:
    """08:00 摘要 cron 落库后：自动汇总全员并写入更新/补丁 Markdown。"""
    enabled = (os.environ.get("MODSTORE_DAILY_VIBE_PREP_ENABLED", "1") or "").strip().lower()
    if enabled in ("0", "false", "no", "off"):
        logger.info("daily digest: vibe prep disabled by MODSTORE_DAILY_VIBE_PREP_ENABLED")
        return
    try:
        max_emp = max(1, min(int(os.environ.get("MODSTORE_DAILY_VIBE_PREP_MAX_EMPLOYEES", "52")), 128))
    except ValueError:
        max_emp = 52
    raw_uid = (
        os.environ.get("MODSTORE_DAILY_VIBE_PREP_USER_ID")
        or os.environ.get("MODSTORE_DAILY_BRIEF_USER_ID")
        or "0"
    ).strip()
    user_id = int(raw_uid) if raw_uid.isdigit() else 0

    from modstore_server.digest_vibe_prep import persist_vibe_prep_on_digest_record, run_digest_vibe_prep_sync

    result = run_digest_vibe_prep_sync(
        digest_day=day,
        digest_subject=subject,
        digest_body_html=body_html,
        digest_body_text=body_text,
        meeting_minutes_html=meeting_minutes_html,
        surface_audit_excerpt=surface_audit_excerpt,
        mode="auto",
        max_employees=max_emp,
        user_id=user_id,
        record_id=record_id,
    )
    persist_vibe_prep_on_digest_record(record_id, result)
    # Agentic Business OS 数据底座：解析双清单为结构化行动条目落库（驱动断点清单/路线图页）。
    if result.get("ok"):
        try:
            from modstore_server.digest_action_items import parse_and_store_action_items

            rt_after = ""
            try:
                from modstore_server.release_train import release_train_context_for_digest

                rt_after = str((release_train_context_for_digest(record_id) or {}).get("release_train_after") or "")
            except Exception:
                rt_after = ""
            ai = parse_and_store_action_items(
                day=day,
                record_id=record_id,
                updates_markdown=str(result.get("updates_markdown") or ""),
                patches_markdown=str(result.get("patches_markdown") or ""),
                rt_version=rt_after,
            )
            logger.info("daily digest: action items record_id=%s patch=%s update=%s", record_id, ai.get("patch"), ai.get("update"))
        except Exception:
            logger.exception("daily digest: action items store failed record_id=%s", record_id)
    if result.get("ok"):
        from modstore_server.digest_vibe_line_dispatch import dispatch_vibe_prep_to_production_lines

        dispatch = dispatch_vibe_prep_to_production_lines(record_id, result)
        if dispatch.get("ok"):
            logger.info(
                "daily digest: vibe line dispatch ok record_id=%s sections=%s pw=%s ps=%s sr=%s",
                record_id,
                dispatch.get("total_sections"),
                (dispatch.get("line_meta") or {}).get("P-W", {}).get("total_sections"),
                (dispatch.get("line_meta") or {}).get("P-S", {}).get("total_sections"),
                (dispatch.get("line_meta") or {}).get("S-R", {}).get("total_sections"),
            )
        elif not dispatch.get("skipped"):
            logger.warning(
                "daily digest: vibe line dispatch failed record_id=%s err=%s",
                record_id,
                dispatch.get("error"),
            )
    if result.get("ok"):
        logger.info(
            "daily digest: vibe prep ok record_id=%s employees=%s model=%s",
            record_id,
            result.get("employee_count"),
            result.get("model"),
        )
    else:
        logger.warning(
            "daily digest: vibe prep failed record_id=%s err=%s",
            record_id,
            result.get("error"),
        )


def _repo_root() -> Path:
    env = os.environ.get("MODSTORE_REPO_ROOT", "").strip()
    if env:
        return Path(env).resolve()
    try:
        from modstore_server.integrations.ops_action_handlers import repo_root as _ops_rr

        return Path(_ops_rr())
    except Exception:
        p = Path(__file__).resolve()
        # 与镜像布局一致：…/modstore_server/daily_digest.py → 上一级目录为 MODstore_deploy（含 pyproject.toml）
        deploy = p.parents[1]
        if (deploy / "pyproject.toml").is_file():
            return deploy
        if len(p.parents) > 2:
            return p.parents[2]
        return deploy


def _consistency_check_html(repo_root: Path) -> str:
    """运行 ``run_full_consistency_check`` 并返回邮件 HTML 段落；失败或非致命异常时不阻断摘要。"""
    raw = (os.environ.get("MODSTORE_DAILY_DIGEST_CONSISTENCY") or "1").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return ""
    try:
        from modstore_server.tools.doc_consistency_checker import run_full_consistency_check

        result = run_full_consistency_check(repo_root)
    except Exception as exc:  # noqa: BLE001
        logger.exception("daily digest: doc consistency check failed")
        esc = html.escape(str(exc)[:400])
        return f"""
<div style="padding:0 24px 12px">
  <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:10px;padding:12px 14px;font-size:13px;color:#b91c1c">
    <strong>文档一致性校验</strong> 未能完成：{esc}
  </div>
</div>
"""

    status = str(result.get("status") or "")
    total_errors = int(result.get("total_errors") or 0)
    total_issues = int(result.get("total_issues") or 0)
    issues = result.get("issues") if isinstance(result.get("issues"), list) else []
    max_lines = 48
    rows: List[str] = []
    for it in issues[:max_lines]:
        if not isinstance(it, dict):
            continue
        emp = html.escape(str(it.get("employee") or "?"))
        sev = html.escape(str(it.get("severity") or ""))
        typ = html.escape(str(it.get("type") or ""))
        desc = html.escape(str(it.get("description") or "")[:500])
        rows.append(
            f"<tr><td style=\"padding:4px 8px;border-bottom:1px solid #e2e8f0;font-size:11px\">{emp}</td>"
            f"<td style=\"padding:4px 8px;border-bottom:1px solid #e2e8f0;font-size:11px;color:#64748b\">{sev}</td>"
            f"<td style=\"padding:4px 8px;border-bottom:1px solid #e2e8f0;font-size:11px;color:#64748b\">{typ}</td>"
            f"<td style=\"padding:4px 8px;border-bottom:1px solid #e2e8f0;font-size:11px\">{desc}</td></tr>"
        )
    extra = ""
    if len(issues) > max_lines:
        extra = (
            f'<p style="margin:8px 0 0;font-size:11px;color:#64748b">另有 {len(issues) - max_lines} 条未展示。</p>'
        )
    ok_bg = "#f0fdf4" if total_errors == 0 else "#fffbeb"
    ok_border = "#bbf7d0" if total_errors == 0 else "#fde68a"
    ok_title = "文档一致性（yuangon）" if total_errors == 0 else "文档一致性（yuangon · 存在 error）"
    summary = (
        f'<p style="margin:0 0 8px;font-size:12px;color:#475569">'
        f"状态 <code>{html.escape(status)}</code> · error 级 {total_errors} · 共 {total_issues} 条"
        f"</p>"
    )
    table = ""
    if rows:
        table = (
            '<table style="width:100%;border-collapse:collapse;margin-top:6px;font-size:11px">'
            "<thead><tr>"
            '<th align="left" style="padding:6px 8px;border-bottom:2px solid #e2e8f0">employee</th>'
            '<th align="left" style="padding:6px 8px;border-bottom:2px solid #e2e8f0">severity</th>'
            '<th align="left" style="padding:6px 8px;border-bottom:2px solid #e2e8f0">type</th>'
            '<th align="left" style="padding:6px 8px;border-bottom:2px solid #e2e8f0">description</th>'
            "</tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table>"
        )
    return f"""
<div style="padding:0 24px 12px">
  <div style="display:flex;align-items:center;margin:12px 0 8px">
    <span style="font-size:16px;font-weight:700;color:#1e293b">{ok_title}</span>
  </div>
  <div style="background:{ok_bg};border:1px solid {ok_border};border-radius:10px;padding:14px 16px">
    {summary}
    {table}
    {extra}
  </div>
</div>
"""


def _git_line(args: list[str], cwd: Path, timeout: float = 8.0) -> str:
    try:
        p = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        return (p.stdout or "").strip() or (p.stderr or "").strip()[:500]
    except (OSError, subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
        return f"(git 不可用: {e})"


def _git_worktree_root(root: Path, timeout: float = 5.0) -> bool:
    """``root`` 是否为 Git 工作副本（含 ``.git`` 为文件、worktree 等）；不依赖 ``(root / '.git').is_dir()``。"""
    if not shutil.which("git"):
        return False
    try:
        p = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        return p.returncode == 0 and (p.stdout or "").strip().lower() == "true"
    except (OSError, subprocess.TimeoutExpired, subprocess.SubprocessError):
        return False


def _digest_commit_display(raw: str) -> str:
    """环境变量/构建元数据常为全 SHA，摘要里缩短展示。"""
    s = (raw or "").strip()
    if len(s) >= 12 and len(s) <= 64 and all(c in "0123456789abcdefABCDEF" for c in s):
        return s[:7]
    if len(s) > 20:
        return s[:20] + "…"
    return s


def _digest_git_branch_and_head(root: Path) -> Tuple[str, str]:
    """分支与 HEAD：环境变量 → 本地 git（若可为工作副本）→ ``.modstore_build.json`` 补缺。

    镜像内可能同时存在构建时写入的 ``.modstore_build.json`` 与挂载的真实 ``.git``；
    此时以 **git 为准**（除非环境变量已显式提供对应字段）。
    """
    br = (
        (os.environ.get("MODSTORE_GIT_BRANCH") or "").strip()
        or (os.environ.get("GIT_BRANCH") or "").strip()
    )
    co_raw = (
        (os.environ.get("MODSTORE_GIT_COMMIT") or "").strip()
        or (os.environ.get("GIT_COMMIT") or "").strip()
        or (os.environ.get("MODSTORE_GIT_SHA") or "").strip()
        or (os.environ.get("GIT_SHA") or "").strip()
        or (os.environ.get("COMMIT_SHA") or "").strip()
        or (os.environ.get("SOURCE_COMMIT") or "").strip()
        or (os.environ.get("VCS_REF") or "").strip()
    )
    co = _digest_commit_display(co_raw) if co_raw else ""

    git_ok = _git_worktree_root(root)

    def _fill_git_gaps() -> None:
        nonlocal br, co
        if not git_ok:
            return
        if not br:
            gb = _git_line(["rev-parse", "--abbrev-ref", "HEAD"], root)
            if not gb.startswith("(git 不可用"):
                br = gb
        if not co:
            gh = _git_line(["rev-parse", "--short", "HEAD"], root)
            if not gh.startswith("(git 不可用"):
                co = gh

    _fill_git_gaps()

    if not br or not co:
        info = root / ".modstore_build.json"
        if info.is_file():
            try:
                data = json.loads(info.read_text(encoding="utf-8"))
                if not br:
                    br = str(data.get("branch") or data.get("ref") or "").strip()
                if not co:
                    jc = str(data.get("commit") or data.get("sha") or "").strip()
                    if jc:
                        co = _digest_commit_display(jc)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass

    _fill_git_gaps()

    return (br or "—"), (co or "—")


def _pytest_lastfailed_snippet(root: Path, limit: int = 1200) -> str:
    p = root / "MODstore_deploy" / ".pytest_cache" / "v" / "cache" / "lastfailed"
    if not p.is_file() or p.stat().st_size == 0:
        return "无（lastfailed 为空或不存在）"
    try:
        t = p.read_text(encoding="utf-8", errors="replace")[:limit]
        return html.escape(t)
    except OSError as e:
        return html.escape(str(e))


def _cursor_error_lines_count(root: Path) -> int:
    n = 0
    try:
        for f in sorted(root.glob(".cursor_*_log.txt")):
            try:
                for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                    low = line.lower()
                    if any(x in low for x in ("error", "fail", "exception")):
                        n += 1
            except OSError:
                continue
    except OSError:
        pass
    return n


def _audit_digest_hint_html() -> str:
    """可选：解释为何运维审计 / 事件计数可能为 0（``MODSTORE_DIGEST_AUDIT_HINT=1``）。"""
    raw = os.environ.get("MODSTORE_DIGEST_AUDIT_HINT", "").strip().lower()
    if raw not in ("1", "true", "yes"):
        return ""
    db_path = (os.environ.get("MODSTORE_DB_PATH") or "").strip() or "（默认 SQLite 路径）"
    sch_running = False
    try:
        from modstore_server.workflow_scheduler import _scheduler as _sch

        sch_running = _sch is not None and bool(getattr(_sch, "running", False))
    except Exception:
        pass
    nginx_p = os.environ.get("OPS_NGINX_ERROR_LOG", "").strip() or "/var/log/nginx/error.log"
    return (
        '<div style="margin-top:12px;padding:10px;border:1px solid #e2e8f0;border-radius:8px;background:#f8fafc">'
        "<p style=\"margin:0 0 8px;font-size:13px;color:#334155\"><strong>计数说明（调试）</strong>："
        "近 24h「运维审计」仅在执行过运维 shell 指令并写入审计表后增加；"
        "「事件入库」依赖 APScheduler 定时采集器命中 pytest/nginx/cursor 规则。</p>"
        f"<ul style=\"margin:0;padding-left:18px;font-size:12px;color:#64748b;line-height:1.5\">"
        f"<li>MODSTORE_DB_PATH：<code>{html.escape(db_path)}</code></li>"
        f"<li>APScheduler 运行中：{'是' if sch_running else '否'}（未启动则采集任务不跑）</li>"
        f"<li>OPS_NGINX_ERROR_LOG：<code>{html.escape(nginx_p)}</code>（文件不存在则跳过 nginx 采集）</li>"
        "</ul></div>"
    )


def _publish_tls_cert_security_alerts(results: Sequence[Any]) -> None:
    """WARNING/CRITICAL 写入 ``security.alert``（按 UTC 日期去重，避免 incident_bus 10 分钟窗重复）。"""
    if not results:
        return
    try:
        from modstore_server.incident_bus import publish as incident_publish
    except Exception:
        logger.exception("tls cert: incident_bus unavailable")
        return
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for r in results:
        level = getattr(r, "level", "")
        if level not in ("WARNING", "CRITICAL"):
            continue
        path = str(getattr(r, "path", "") or "")
        days_remaining = getattr(r, "days_remaining", None)
        na = getattr(r, "not_after_utc", None)
        na_iso = na.isoformat() if na is not None else ""
        fp_raw = f"tls_cert_expiry:{path}:{today}:{level}"
        fp = hashlib.sha256(fp_raw.encode("utf-8")).hexdigest()[:64]
        try:
            incident_publish(
                "security.alert",
                {
                    "kind": "tls_certificate_expiry",
                    "level": level,
                    "path": path,
                    "days_remaining": days_remaining,
                    "not_after": na_iso,
                },
                source="daily_digest",
                fingerprint=fp,
            )
        except Exception:
            logger.exception("tls cert: incident publish failed path=%s", path[:160])


def _tls_cert_digest_html(results: Sequence[Any]) -> str:
    """TLS 巡检表格（INFO/WARNING/CRITICAL）；无命中返回空串。"""
    if not results:
        return ""
    rows_html: List[str] = []
    for r in results:
        level = getattr(r, "level", "OK")
        if level == "OK":
            continue
        path_e = html.escape(str(getattr(r, "path", "")))
        na = getattr(r, "not_after_utc", None)
        na_s = na.strftime("%Y-%m-%d %H:%M UTC") if na is not None else "?"
        badge_bg, badge_fg = "#fef2f2", "#b91c1c"
        if level == "INFO":
            badge_bg, badge_fg = "#eff6ff", "#1e40af"
        elif level == "WARNING":
            badge_bg, badge_fg = "#fffbeb", "#b45309"
        dr = getattr(r, "days_remaining", "?")
        rows_html.append(
            "<tr>"
            f'<td style="padding:6px 8px;border-bottom:1px solid #e2e8f0;font-size:12px">'
            f'<span style="background:{badge_bg};color:{badge_fg};padding:2px 8px;'
            f'border-radius:6px;font-weight:600">{html.escape(str(level))}</span></td>'
            f'<td style="padding:6px 8px;border-bottom:1px solid #e2e8f0;font-size:11px;word-break:break-all">{path_e}</td>'
            f'<td style="padding:6px 8px;border-bottom:1px solid #e2e8f0;font-size:11px">{html.escape(str(dr))}</td>'
            f'<td style="padding:6px 8px;border-bottom:1px solid #e2e8f0;font-size:11px">{html.escape(na_s)}</td>'
            "</tr>"
        )
    if not rows_html:
        return ""
    table = (
        '<table style="width:100%;border-collapse:collapse;margin-top:8px;font-size:11px">'
        "<thead><tr>"
        '<th align="left" style="padding:6px 8px;border-bottom:2px solid #e2e8f0">级别</th>'
        '<th align="left" style="padding:6px 8px;border-bottom:2px solid #e2e8f0">证书路径</th>'
        '<th align="left" style="padding:6px 8px;border-bottom:2px solid #e2e8f0">剩余天数</th>'
        '<th align="left" style="padding:6px 8px;border-bottom:2px solid #e2e8f0">notAfter</th>'
        "</tr></thead><tbody>"
        + "".join(rows_html)
        + "</tbody></table>"
    )
    return (
        '<div style="padding:0 24px 12px">'
        '<div style="display:flex;align-items:center;margin:12px 0 8px">'
        '<span style="font-size:16px;font-weight:700;color:#1e293b">TLS 证书到期巡检</span>'
        "</div>"
        '<div style="background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:14px 16px;font-size:13px;color:#92400e">'
        "<p style=\"margin:0 0 8px\">以下证书已达到 INFO/WARNING/CRITICAL 阈值（见 CERT_EXPIRY_*）。"
        "WARNING/CRITICAL 已写入安全事件 <code>security.alert</code>。</p>"
        f"{table}"
        "</div></div>"
    )


def _nginx_tail_hint() -> str:
    log_path = os.environ.get("OPS_NGINX_ERROR_LOG", "").strip() or "/var/log/nginx/error.log"
    p = Path(log_path)
    if not p.is_file():
        return f"日志文件不存在或未挂载: {html.escape(log_path)}"
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
        tail = "".join(text.splitlines(True)[-40:])
        low = tail.lower()
        flag = "含 error 关键字" if "error" in low else "未见明显 error 尾部"
        return f"{html.escape(flag)}（末尾约 40 行，路径 {html.escape(log_path)}）"
    except OSError as e:
        return html.escape(str(e))


def _run_pytest_summary(repo: Path) -> str:
    deploy = repo / "MODstore_deploy"
    if not (deploy / "tests").is_dir():
        return "<pre>跳过：未找到 MODstore_deploy/tests</pre>"
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests",
                "-q",
                "--tb=no",
                "--maxfail=15",
            ],
            cwd=str(deploy),
            capture_output=True,
            text=True,
            timeout=int(os.environ.get("MODSTORE_DAILY_DIGEST_PYTEST_TIMEOUT", "900")),
            shell=False,
            env={**os.environ, "PYTHONWARNINGS": "ignore"},
        )
        out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        out = out[-12000:]
        esc = html.escape(out)
        rc = proc.returncode
        status = "通过" if rc == 0 else f"失败 exit={rc}"
        return f"<p><strong>pytest</strong>：{html.escape(status)}</p><pre style=\"white-space:pre-wrap;font-size:12px\">{esc}</pre>"
    except subprocess.TimeoutExpired:
        return "<pre>pytest 超时（见 MODSTORE_DAILY_DIGEST_PYTEST_TIMEOUT）</pre>"
    except Exception as e:  # noqa: BLE001
        return f"<pre>{html.escape(str(e))}</pre>"


def _digest_system_work_summary_html(
    *,
    host: str,
    git_branch: str,
    git_head: str,
    repo_root: Path,
    emp_n: int,
    met_ok: int,
    met_fail: int,
    ops_n: int,
    inc_n: int,
    cursor_hits: int,
) -> str:
    """邮件「一、系统状态」：结构化键值对展示，替代原文段落。"""
    rb = html.escape(str(repo_root))
    total = met_ok + met_fail
    rate = f"{met_ok * 100 // total}%" if total > 0 else "--"

    def _kv_row(label: str, value: str, extra_style: str = "") -> str:
        return (
            f'<tr style="{extra_style}">'
            f'<td style="padding:7px 12px;color:#64748b;font-size:13px;white-space:nowrap;border-bottom:1px solid #f1f5f9">{label}</td>'
            f'<td style="padding:7px 12px;color:#1e293b;font-size:13px;font-weight:600;border-bottom:1px solid #f1f5f9">{value}</td>'
            f"</tr>"
        )

    rows = [
        _kv_row("仓库分支", html.escape(git_branch)),
        _kv_row("最新提交", f'<code style="background:#f1f5f9;padding:2px 6px;border-radius:4px;font-size:12px">{html.escape(git_head)}</code>'),
        _kv_row("运行主机", html.escape(host)),
        _kv_row("数据目录", f'<span style="font-size:11px;word-break:break-all">{rb}</span>'),
    ]

    system_table = (
        '<table style="width:100%;border-collapse:collapse;margin:0">'
        + "".join(rows)
        + "</table>"
    )

    rows2 = [
        _kv_row("在岗员工", f"{emp_n} 人"),
        _kv_row("今日任务执行", f"{total} 次"),
        _kv_row("成功率", rate, extra_style="" if met_fail == 0 else "background:#fef2f2"),
        _kv_row("运维操作记录", f"{ops_n} 条"),
        _kv_row("系统事件", f"{inc_n} 条", extra_style="" if inc_n == 0 else "background:#fffbeb"),
    ]

    team_table = (
        '<table style="width:100%;border-collapse:collapse;margin:0">'
        + "".join(rows2)
        + "</table>"
    )

    cursor_alert = ""
    if cursor_hits > 0:
        cursor_alert = (
            f'<div style="margin-top:10px;padding:10px 14px;background:#fffbeb;border-left:3px solid #f59e0b;border-radius:4px">'
            f'<span style="font-size:13px;color:#92400e">代码助手异常：近 24h 有 <strong>{cursor_hits}</strong> 行 error，建议排查。</span>'
            f"</div>"
        )

    return f"""
<div style="padding:0 24px 16px">
  <div style="display:flex;align-items:center;margin:18px 0 10px">
    <span style="font-size:20px;margin-right:8px">&#x1F4CB;</span>
    <span style="font-size:16px;font-weight:700;color:#1e293b">系统状态</span>
  </div>
  <div style="background:#f8fafc;border-radius:10px;padding:2px 14px 8px;margin-bottom:14px;border:1px solid #e2e8f0">
    {system_table}
  </div>
  <div style="display:flex;align-items:center;margin:0 0 10px">
    <span style="font-size:20px;margin-right:8px">&#x1F465;</span>
    <span style="font-size:16px;font-weight:700;color:#1e293b">团队活跃度</span>
  </div>
  <div style="background:#f8fafc;border-radius:10px;padding:2px 14px 8px;border:1px solid #e2e8f0">
    {team_table}
  </div>
  {cursor_alert}
</div>
"""


def _digest_kpi_cards_html(
    *,
    met_ok: int,
    met_fail: int,
    emp_n: int,
    ops_n: int,
    inc_n: int,
) -> str:
    """邮件顶部 KPI 卡片区：4 个核心指标，大数字 + 颜色编码。"""
    cards: List[str] = []

    def _card(
        value: str,
        label: str,
        bg: str,
        border: str,
        color: str,
        sub: str = "",
    ) -> str:
        sub_html = (
            f'<div style="font-size:12px;color:#94a3b8;margin-top:2px">{sub}</div>'
            if sub
            else ""
        )
        return (
            f'<td style="width:25%;padding:4px;vertical-align:top">'
            f'<div style="background:{bg};border-radius:8px;padding:14px 8px;text-align:center;border:1px solid {border}">'
            f'<div style="font-size:26px;font-weight:700;color:{color};line-height:1.2">{value}</div>'
            f'<div style="font-size:11px;color:#64748b;margin-top:4px">{label}</div>'
            f"{sub_html}"
            f"</div></td>"
        )

    exec_color = "#16a34a" if met_fail == 0 else "#ea580c"
    exec_bg = "#f0fdf4" if met_fail == 0 else "#fff7ed"
    exec_border = "#bbf7d0" if met_fail == 0 else "#fed7aa"
    exec_sub = (
        f"失败 {met_fail} 次" if met_fail > 0 else "全部成功"
    )

    inc_color = "#16a34a" if inc_n == 0 else "#ea580c"
    inc_bg = "#f0fdf4" if inc_n == 0 else "#fffbeb"
    inc_border = "#bbf7d0" if inc_n == 0 else "#fde68a"
    inc_label = "系统事件" if inc_n == 0 else "系统事件（有异常）"

    ops_color = "#64748b" if ops_n == 0 else "#1a56db"
    ops_bg = "#f8fafc" if ops_n == 0 else "#eff6ff"
    ops_border = "#e2e8f0" if ops_n == 0 else "#bfdbfe"

    cards.append(_card(str(emp_n), "在岗员工", "#eff6ff", "#bfdbfe", "#1a56db"))
    cards.append(_card(str(met_ok), "任务执行成功", exec_bg, exec_border, exec_color, exec_sub))
    cards.append(_card(str(ops_n), "运维操作记录", ops_bg, ops_border, ops_color))
    cards.append(_card(str(inc_n), inc_label, inc_bg, inc_border, inc_color))

    return (
        '<table style="width:100%;border-collapse:collapse;margin:0"><tr>'
        + "".join(cards)
        + "</tr></table>"
    )


def _meeting_minutes_md_to_html(text: str) -> str:
    """把 ``synthesize_meeting_minutes`` 五段式输出转成邮件 HTML 卡片片段。

    严格按 system prompt 约定的结构（``会议摘要`` / ``一、…`` … ``五、…``）渲染：
    - ``一、…`` ``二、…`` ``三、…`` ``四、…`` ``五、…`` 行作为小节标题
    - 三、四下的 ``- `` / ``* `` 行渲染为 ``<ul>``
    - 其余行渲染为 ``<p>``，整体 HTML 转义；失败回退到 ``<pre>`` 原文。
    """
    raw = (text or "").strip()
    if not raw:
        return ""

    section_re = re.compile(r"^([一二三四五六七八九十])、(.*)$")
    out: List[str] = []
    in_ul = False
    have_seen_title = False

    def _close_ul() -> None:
        nonlocal in_ul
        if in_ul:
            out.append("</ul>")
            in_ul = False

    for raw_line in raw.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            _close_ul()
            continue

        if stripped == "会议摘要" or stripped.startswith("# "):
            _close_ul()
            have_seen_title = True
            continue

        m = section_re.match(stripped)
        if m:
            _close_ul()
            num, rest = m.group(1), html.escape(m.group(2).strip())
            out.append(
                f'<div style="margin:12px 0 6px"><span style="display:inline-block;min-width:24px;color:#1a56db;font-weight:700">{num}、</span>'
                f'<span style="font-size:14px;font-weight:700;color:#1e293b">{rest}</span></div>'
            )
            continue

        if stripped.startswith(("- ", "* ", "・", "• ")):
            item = stripped[1:].lstrip() if stripped[0] in "-*" else stripped[1:].lstrip()
            if not in_ul:
                out.append('<ul style="margin:4px 0 6px 4px;padding-left:20px;font-size:13px;color:#334155;line-height:1.6">')
                in_ul = True
            out.append(f'<li style="margin:3px 0">{html.escape(item)}</li>')
            continue

        _close_ul()
        out.append(
            f'<p style="margin:4px 0;font-size:13px;color:#334155;line-height:1.6">{html.escape(stripped)}</p>'
        )

    _close_ul()
    if not have_seen_title:
        out.insert(
            0,
            '<div style="font-size:14px;font-weight:700;color:#1e293b;margin-bottom:6px">会议摘要</div>',
        )
    return "".join(out)


def _surface_meeting_topic(surface_audit_report: Dict[str, Any] | None) -> Tuple[str, List[str]]:
    """根据三端巡检结果构造「员工大会」讨论议题与对应参会员工。

    返回 ``(user_question, employee_ids)``；report 为空 / 无结果时返回 ``("", [])``，
    回退到原来的全员待机汇总模式。
    """
    if not isinstance(surface_audit_report, dict):
        return "", []
    results = surface_audit_report.get("results") if isinstance(surface_audit_report.get("results"), list) else []
    if not results:
        return "", []
    try:
        from modstore_server.daily_digest_surface_audit import (
            lane_employee_ids,
            surface_audit_excerpt_markdown,
        )
    except Exception:  # noqa: BLE001
        return "", []

    lanes_present = []
    for lane in ("P-W", "P-S", "P-App"):
        if any(str(r.get("lane")) == lane for r in results):
            lanes_present.append(lane)
    emp_ids: List[str] = []
    for lane in lanes_present:
        for pid in lane_employee_ids(lane):
            if pid not in emp_ids:
                emp_ids.append(pid)

    excerpt = surface_audit_excerpt_markdown(surface_audit_report)
    question = (
        "今天的三端页面巡检（P-W 网站 xiu-ci.com / P-S 软件 market / P-App 移动 WebView）"
        "结果与 AI 分析如下，请各产线对应员工从自己岗位视角讨论：哪些是真问题、谁来修、下一步动作。\n\n"
        f"{excerpt}"
    )
    return question, emp_ids


def build_meeting_minutes_html_sync(*, surface_audit_report: Dict[str, Any] | None = None) -> str:
    """每日摘要邮件「员工大会摘要」段落 HTML（同步）。

    流程：``build_all_hands_report`` → ``synthesize_meeting_minutes`` → markdown 渲染。
    传入 ``surface_audit_report`` 时，会把三端巡检结果作为大会议题，召集 P-W / P-S / P-App
    对应在岗员工围绕「截图 + 分析」讨论问题与下一步（替代无议题的待机汇总）。

    环境变量：
    - ``MODSTORE_DAILY_MEETING_ENABLED``（默认 ``1``）：关闭则返回空串，邮件不显示该段。
    - ``MODSTORE_DAILY_MEETING_MAX_EMPLOYEES``（默认 ``6``）：单次大会最多多少名员工。
    - ``MODSTORE_DAILY_MEETING_WITH_RESEARCH``（默认 ``0``）：是否开启员工汇报内的联网调研。
    - ``MODSTORE_DAILY_MEETING_TIMEOUT_SECONDS``（默认 ``600``）：整轮大会硬超时。
    - ``MODSTORE_DAILY_MEETING_USER_ID``（默认 ``MODSTORE_DAILY_BRIEF_USER_ID`` 或 ``0``）。
    """
    enabled = (os.environ.get("MODSTORE_DAILY_MEETING_ENABLED", "1") or "").strip().lower()
    if enabled in ("0", "false", "no", "off"):
        return ""

    try:
        max_emp = max(1, min(int(os.environ.get("MODSTORE_DAILY_MEETING_MAX_EMPLOYEES", "6")), 32))
    except ValueError:
        max_emp = 6
    try:
        timeout_s = max(60, int(os.environ.get("MODSTORE_DAILY_MEETING_TIMEOUT_SECONDS", "600")))
    except ValueError:
        timeout_s = 600
    with_research = (os.environ.get("MODSTORE_DAILY_MEETING_WITH_RESEARCH", "0") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    raw_uid = (
        os.environ.get("MODSTORE_DAILY_MEETING_USER_ID")
        or os.environ.get("MODSTORE_DAILY_BRIEF_USER_ID")
        or "0"
    ).strip()
    user_id = int(raw_uid) if raw_uid.isdigit() else 0

    def _err_card(msg: str) -> str:
        return (
            '<div style="background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:14px 16px">'
            f'<p style="margin:0;font-size:13px;color:#92400e">员工大会未生成摘要：{html.escape(msg)}</p>'
            "</div>"
        )

    topic_question, topic_emp_ids = _surface_meeting_topic(surface_audit_report)

    try:
        import asyncio as _aio
        from modstore_server.all_hands_report import (
            build_all_hands_report,
            synthesize_meeting_minutes,
        )

        async def _run() -> Dict[str, Any]:
            report = await _aio.wait_for(
                build_all_hands_report(
                    employee_ids=(topic_emp_ids or None),
                    max_employees=max_emp,
                    with_research=with_research,
                    user_id=user_id,
                    concurrency=2,
                    user_question=(topic_question or None),
                    synthesize=bool(topic_question),
                ),
                timeout=timeout_s,
            )
            if not report.get("ok"):
                return {"report": report, "minutes": None}
            minutes = await _aio.wait_for(
                synthesize_meeting_minutes(report=report, user_id=user_id),
                timeout=max(60, timeout_s // 3),
            )
            return {"report": report, "minutes": minutes}

        from modstore_server.runtime_async import run_coro_sync

        result = run_coro_sync(_run())
    except Exception as exc:  # noqa: BLE001
        logger.exception("daily meeting failed")
        return _err_card(f"调度异常：{exc}")

    report = result.get("report") or {}
    minutes = result.get("minutes") or {}
    if not report.get("ok"):
        return _err_card(str(report.get("error") or "build_all_hands_report 未成功"))

    minutes_md = str(minutes.get("text") or "").strip()
    if not minutes_md:
        return _err_card(str(minutes.get("error") or "bench LLM 未输出会议摘要"))

    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    total = int(summary.get("total") or 0)
    ok_count = int(summary.get("ok") or 0)
    err_count = int(summary.get("error") or 0)
    bench_provider = str(summary.get("bench_provider") or "").strip()
    bench_model = str(summary.get("bench_model") or "").strip()

    body_html = _meeting_minutes_md_to_html(minutes_md)
    bench_label = (
        f'<code style="background:#eff6ff;color:#1e40af;padding:2px 8px;border-radius:4px;font-size:11px">{html.escape(bench_provider)}/{html.escape(bench_model)}</code>'
        if bench_provider and bench_model
        else ""
    )

    meta_html = (
        '<div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:10px;font-size:12px;color:#64748b">'
        f'<span>到会 <strong style="color:#1e293b">{total}</strong> 人</span>'
        f'<span style="color:#cbd5e1">·</span>'
        f'<span>成功 <strong style="color:#0f766e">{ok_count}</strong></span>'
        f'<span style="color:#cbd5e1">·</span>'
        f'<span>异常 <strong style="color:#b91c1c">{err_count}</strong></span>'
        + (f'<span style="color:#cbd5e1">·</span>{bench_label}' if bench_label else "")
        + "</div>"
    )

    return (
        '<div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:10px;padding:14px 16px">'
        + meta_html
        + body_html
        + "</div>"
    )


def build_digest_html(
    *,
    staged_section_html: str = "",
    imap_alert_html: str = "",
    employee_briefs_html: str = "",
    tls_cert_section_html: str = "",
    meeting_minutes_html: str = "",
    surface_audit_html: str = "",
) -> str:
    """生成邮件 HTML（不含外层模板）。
    ``staged_section_html``：待审分支与审批 token 说明（由 ``run_daily_digest_email`` 注入）。
    ``employee_briefs_html``：各岗位「工作内容摘要 + 新方案」（可选）。
    ``tls_cert_section_html``：TLS 证书巡检段落（可选）。
    ``meeting_minutes_html``：员工大会摘要段落（可选；空则不显示该段）。
    ``surface_audit_html``：P-W/P-S/P-App 三端页面截图巡检段落（可选）。
    """
    root = _repo_root()
    now_utc = datetime.now(timezone.utc)

    host = socket.gethostname()
    git_branch, git_head = _digest_git_branch_and_head(root)

    sf = get_session_factory()
    since = datetime.now(timezone.utc) - timedelta(hours=24)

    with sf() as session:
        emp_n = (
            session.query(func.count(CatalogItem.id))
            .filter(CatalogItem.artifact == "employee_pack")
            .scalar()
            or 0
        )
        ops_n = (
            session.query(func.count(OpsActionAuditLog.id))
            .filter(OpsActionAuditLog.created_at >= since)
            .scalar()
            or 0
        )
        inc_n = (
            session.query(func.count(IncidentEvent.id))
            .filter(IncidentEvent.created_at >= since)
            .scalar()
            or 0
        )
        met_ok = (
            session.query(func.count(EmployeeExecutionMetric.id))
            .filter(
                EmployeeExecutionMetric.created_at >= since,
                EmployeeExecutionMetric.status == "success",
            )
            .scalar()
            or 0
        )
        met_fail = (
            session.query(func.count(EmployeeExecutionMetric.id))
            .filter(
                EmployeeExecutionMetric.created_at >= since,
                EmployeeExecutionMetric.status != "success",
            )
            .scalar()
            or 0
        )

    cursor_hits = _cursor_error_lines_count(root)

    audit_hint_html = _audit_digest_hint_html()

    kpi_cards_html = _digest_kpi_cards_html(
        met_ok=int(met_ok),
        met_fail=int(met_fail),
        emp_n=int(emp_n),
        ops_n=int(ops_n),
        inc_n=int(inc_n),
    )

    consistency_block = _consistency_check_html(root)

    work_summary_html = _digest_system_work_summary_html(
        host=host,
        git_branch=git_branch,
        git_head=git_head,
        repo_root=root,
        emp_n=int(emp_n),
        met_ok=int(met_ok),
        met_fail=int(met_fail),
        ops_n=int(ops_n),
        inc_n=int(inc_n),
        cursor_hits=int(cursor_hits),
    )
    briefs_block = ""
    if (employee_briefs_html or "").strip():
        briefs_block = f"""
<div style="padding:0 24px 16px">
  <div style="display:flex;align-items:center;margin:18px 0 10px">
    <span style="font-size:20px;margin-right:8px">&#x1F4A1;</span>
    <span style="font-size:16px;font-weight:700;color:#1e293b">AI 改进建议</span>
  </div>
  <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:14px 16px">
    {employee_briefs_html}
  </div>
</div>
"""

    _weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    try:
        from zoneinfo import ZoneInfo

        cn_now = now_utc.astimezone(ZoneInfo("Asia/Shanghai"))
        weekday_cn = _weekdays[cn_now.weekday()]
        cn_display = f"{cn_now.strftime('%Y-%m-%d')} · {weekday_cn} · {cn_now.strftime('%H:%M')} CST"
    except Exception:
        cn_display = now_utc.strftime("%Y-%m-%d %H:%M UTC")

    imap_block = ""
    if imap_alert_html:
        imap_block = f"""
<div style="padding:0 24px 8px">
  <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:10px 14px;font-size:12px;color:#dc2626">
    {imap_alert_html}
  </div>
</div>
"""

    audit_block = ""
    if audit_hint_html:
        audit_block = f"""
<div style="padding:0 24px 8px">
  {audit_hint_html}
</div>
"""

    meeting_block = ""
    if (meeting_minutes_html or "").strip():
        meeting_block = f"""
<div style="padding:0 24px 16px">
  <div style="display:flex;align-items:center;margin:18px 0 10px">
    <span style="font-size:20px;margin-right:8px">&#x1F465;</span>
    <span style="font-size:16px;font-weight:700;color:#1e293b">员工大会摘要</span>
  </div>
  {meeting_minutes_html}
</div>
"""

    surface_block = ""
    if (surface_audit_html or "").strip():
        surface_block = f"""
<div style="padding:0 24px 16px">
  <div style="display:flex;align-items:center;margin:18px 0 10px">
    <span style="font-size:20px;margin-right:8px">&#x1F4F7;</span>
    <span style="font-size:16px;font-weight:700;color:#1e293b">三端页面截图巡检</span>
    <span style="margin-left:8px;font-size:11px;color:#64748b">P-W 网站 · P-S 软件 · P-App 移动</span>
  </div>
  {surface_audit_html}
</div>
"""

    return f"""
<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;line-height:1.5;color:#1e293b;background:#f1f5f9;padding:20px 12px">
<div style="max-width:640px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08)">

<div style="background:linear-gradient(135deg,#1e3a8a,#1a56db);padding:32px 24px 28px;text-align:center">
  <div style="font-size:26px;font-weight:800;color:#fff;letter-spacing:1px">MODstore</div>
  <div style="font-size:14px;color:#bfdbfe;margin-top:4px;font-weight:500">每日运营摘要</div>
  <div style="font-size:12px;color:#93c5fd;margin-top:8px">{cn_display}</div>
</div>

{imap_block}
{audit_block}

<div style="padding:8px 16px">
  {kpi_cards_html}
</div>

{consistency_block}
{tls_cert_section_html}
{staged_section_html}
{work_summary_html}
{meeting_block}
{surface_block}
{briefs_block}

<div style="border-top:1px solid #e2e8f0;padding:16px 24px;text-align:center">
  <span style="font-size:11px;color:#94a3b8">MODstore 自动发送 · 每日 08:00 CST</span>
  <br>
  <span style="font-size:11px;color:#94a3b8">回复本邮件可进行审批操作</span>
</div>

</div>
</div>
"""


def build_digest_approval_bundle(
    *,
    pending: Sequence[Any],
    auth_email: str,
    expires_at: datetime,
    existing_token_hashes: set[str] | None = None,
) -> Tuple[List[OpsApprovalToken], str]:
    """生成 ``approve_one``（若有 pending）+ 一枚 ``digest_identity`` 身份校验令牌与对应 HTML 段落。"""
    token_batch: List[OpsApprovalToken] = []
    seen_hashes = existing_token_hashes if existing_token_hashes is not None else set()
    plain_identity, identity_hash = _new_unique_ops_token_plain(seen_hashes)

    cards: List[str] = []
    for s in pending:
        plain, th = _new_unique_ops_token_plain(seen_hashes)
        token_batch.append(
            OpsApprovalToken(
                token_hash=th,
                kind="approve_one",
                payload_json=json.dumps({"staged_change_id": int(getattr(s, "id"))}, ensure_ascii=False),
                authorized_email=auth_email,
                expires_at=expires_at,
            )
        )
        summ = html.escape(
            (str(getattr(s, "diff_summary") or ""))[:240].replace("\n", " ")
        )
        branch_esc = html.escape(str(getattr(s, "branch") or ""))
        fc = int(getattr(s, "files_changed_count") or 0)
        cards.append(
            f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:14px 16px;margin-bottom:10px">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">'
            f'<code style="background:#1e293b;color:#e2e8f0;padding:3px 10px;border-radius:5px;font-size:12px">{branch_esc}</code>'
            f'<span style="background:#dbeafe;color:#1e40af;padding:2px 10px;border-radius:10px;font-size:12px;font-weight:600">{fc} 个文件</span>'
            f"</div>"
            f'<div style="font-size:12px;color:#64748b;line-height:1.5;margin-bottom:10px">{summ}</div>'
            f'<div style="display:flex;align-items:center">'
            f'<span style="font-size:12px;color:#94a3b8;margin-right:8px">批准令牌</span>'
            f'<code style="font-size:18px;font-weight:700;color:#1a56db;background:#eff6ff;padding:4px 12px;border-radius:6px;letter-spacing:2px">{plain}</code>'
            f"</div></div>"
        )

    token_batch.append(
        OpsApprovalToken(
            token_hash=identity_hash,
            kind="digest_identity",
            payload_json=json.dumps({"scope": "daily_digest"}, ensure_ascii=False),
            authorized_email=auth_email,
            expires_at=expires_at,
        )
    )

    if pending:
        staged_section_html = f"""
<div style="padding:0 24px 16px">
  <div style="display:flex;align-items:center;margin:18px 0 10px">
    <span style="font-size:20px;margin-right:8px">&#x2705;</span>
    <span style="font-size:16px;font-weight:700;color:#1e293b">待审批改动</span>
    <span style="background:#fef2f2;color:#dc2626;padding:2px 10px;border-radius:10px;font-size:12px;font-weight:600;margin-left:8px">{len(pending)} 项</span>
  </div>
  <p style="font-size:13px;color:#64748b;margin:0 0 8px;line-height:1.5">回复本邮件并附上令牌即可批准对应分支的部署。</p>
  {"".join(cards)}
  <div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;padding:14px 16px;margin-top:14px;text-align:center">
    <div style="font-size:12px;color:#64748b;margin-bottom:4px">身份校验码（不触发部署）</div>
    <code style="font-size:22px;font-weight:700;color:#1a56db;letter-spacing:3px">{plain_identity}</code>
  </div>
</div>
"""
    else:
        staged_section_html = f"""
<div style="padding:0 24px 16px">
  <div style="display:flex;align-items:center;margin:18px 0 10px">
    <span style="font-size:20px;margin-right:8px">&#x1F6E1;</span>
    <span style="font-size:16px;font-weight:700;color:#1e293b">身份校验</span>
  </div>
  <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;padding:16px;text-align:center">
    <div style="font-size:13px;color:#64748b;margin-bottom:4px">当前无待部署分支，回信不会触发部署操作</div>
    <div style="font-size:12px;color:#94a3b8;margin-bottom:6px">身份校验码（可回复本邮件验证身份）</div>
    <code style="font-size:22px;font-weight:700;color:#1a56db;letter-spacing:3px">{plain_identity}</code>
  </div>
</div>
"""

    return token_batch, staged_section_html


def run_daily_digest_email() -> None:
    """由调度器每日调用。"""
    raw = os.environ.get("MODSTORE_DAILY_DIGEST_ENABLED", "1").strip().lower()
    if raw in ("0", "false", "no", "off"):
        logger.info("daily digest disabled by MODSTORE_DAILY_DIGEST_ENABLED")
        return

    recipients = parse_daily_digest_recipient_emails(
        os.environ.get("MODSTORE_DAILY_DIGEST_EMAIL", DEFAULT_DIGEST_EMAIL).strip()
    )
    if not recipients:
        logger.warning("daily digest: no valid recipient emails")
        return

    try:
        try:
            from modstore_server.inbox_poller import poll_fail_streak as _poll_fail_streak

            _streak = _poll_fail_streak()
        except Exception:
            _streak = 0

        imap_alert_html = ""
        if _streak >= 3:
            imap_alert_html = (
                '<p style="color:#b91c1c;font-size:14px"><strong>IMAP 收件轮询已连续失败 ≥3 次，'
                "请检查 MODSTORE_IMAP_HOST / MODSTORE_IMAP_USER / 密码（或 SMTP 同源凭证）。</strong></p>"
            )

        auth_email = os.environ.get("MODSTORE_APPROVAL_AUTHORIZED_FROM", DEFAULT_DIGEST_EMAIL).strip()
        ttl_hours = int(os.environ.get("MODSTORE_APPROVAL_TOKEN_TTL_HOURS", "36"))
        expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)

        sf = get_session_factory()
        with sf() as session:
            pending = (
                session.query(OpsStagedChange)
                .filter(OpsStagedChange.status == "pending")
                .order_by(OpsStagedChange.id.asc())
                .all()
            )

        with sf() as session:
            existing_token_hashes = {
                str(row[0])
                for row in session.query(OpsApprovalToken.token_hash).all()
                if row[0]
            }
            token_batch, staged_section_html = build_digest_approval_bundle(
                pending=pending,
                auth_email=auth_email,
                expires_at=expires_at,
                existing_token_hashes=existing_token_hashes,
            )

        employee_briefs_html = ""
        if os.environ.get("MODSTORE_DAILY_BRIEF_ENABLED", "0").strip().lower() in ("1", "true", "yes"):
            try:
                from modstore_server.daily_employee_briefs import build_daily_brief_html_sync

                employee_briefs_html = build_daily_brief_html_sync()
            except Exception:
                logger.exception("daily digest: employee briefs failed")
                employee_briefs_html = (
                    '<div style="margin-top:16px"><p style="color:#b91c1c;font-size:14px">'
                    "各岗位方案段落生成失败（见服务器日志）。</p></div>"
                )

        try:
            from modstore_server.tls_cert_inspection import scan_tls_certificates

            cert_results = scan_tls_certificates()
        except Exception:
            logger.exception("daily digest: tls cert scan failed")
            cert_results = []
        _publish_tls_cert_security_alerts(cert_results)
        tls_cert_section_html = _tls_cert_digest_html(cert_results)

        # 先跑三端巡检（截图 + 对应员工 AI 分析），员工大会再围绕巡检结果讨论。
        surface_audit_html = ""
        surface_audit_report: Dict[str, Any] = {}
        try:
            from modstore_server.daily_digest_surface_audit import (
                build_surface_audit_html_sync,
                surface_audit_excerpt_markdown,
            )

            surface_audit_html, surface_audit_report = build_surface_audit_html_sync()
        except Exception:
            logger.exception("daily digest: surface audit failed")
            surface_audit_html = (
                '<div style="background:#fef2f2;border:1px solid #fecaca;border-radius:10px;padding:14px 16px">'
                '<p style="margin:0;font-size:13px;color:#b91c1c">三端页面截图巡检失败（见服务器日志）。</p>'
                "</div>"
            )

        # 三端截图 → PowerPoint（每日邮件附件）。
        surface_ppt_path = ""
        surface_ppt_meta: Dict[str, Any] = {}
        try:
            from modstore_server.daily_digest_surface_ppt import build_surface_audit_pptx

            surface_ppt_meta = build_surface_audit_pptx(surface_audit_report)
            if surface_ppt_meta.get("ok") and not surface_ppt_meta.get("skipped"):
                surface_ppt_path = str(surface_ppt_meta.get("path") or "")
                logger.info(
                    "daily digest: surface ppt built slides=%s path=%s",
                    surface_ppt_meta.get("slides"),
                    surface_ppt_path,
                )
            elif surface_ppt_meta.get("error"):
                logger.warning("daily digest: surface ppt error=%s", surface_ppt_meta.get("error"))
        except Exception:
            logger.exception("daily digest: surface ppt failed")

        if surface_ppt_path:
            slides = int(surface_ppt_meta.get("slides") or 0)
            surface_audit_html += (
                '<div style="padding:0 24px 4px">'
                '<div style="background:#eef2ff;border:1px solid #c7d2fe;border-radius:8px;'
                'padding:10px 14px;font-size:12px;color:#4338ca">'
                f"&#x1F4CE; 本次巡检截图已拼成 PowerPoint（{slides} 页，含每页 AI 分析），见邮件附件。"
                "</div></div>"
            )

        meeting_minutes_html = ""
        try:
            meeting_minutes_html = build_meeting_minutes_html_sync(
                surface_audit_report=surface_audit_report
            )
        except Exception:
            logger.exception("daily digest: meeting minutes failed")
            meeting_minutes_html = (
                '<div style="background:#fef2f2;border:1px solid #fecaca;border-radius:10px;padding:14px 16px">'
                '<p style="margin:0;font-size:13px;color:#b91c1c">员工大会段落生成失败（见服务器日志）。</p>'
                "</div>"
            )

        body = build_digest_html(
            staged_section_html=staged_section_html,
            imap_alert_html=imap_alert_html,
            employee_briefs_html=employee_briefs_html,
            tls_cert_section_html=tls_cert_section_html,
            meeting_minutes_html=meeting_minutes_html,
            surface_audit_html=surface_audit_html,
        )
        day = digest_calendar_day()
        subject = f"MODstore 每日摘要 · {day}"
        any_delivered = False
        delivery_rows: List[Dict[str, Any]] = []
        attachments = [surface_ppt_path] if surface_ppt_path else []
        for to_email in recipients:
            if attachments:
                result = send_html_email_with_attachments(to_email, subject, body, attachments)
            else:
                result = send_simple_html_email(to_email, subject, body)
            delivered = bool(result.get("delivered"))
            if delivered:
                any_delivered = True
            delivery_rows.append(
                {
                    "to": to_email,
                    "delivered": delivered,
                    "mode": str(result.get("mode") or ""),
                    "error": str(result.get("error") or ""),
                    "attached": list(result.get("attached") or []),
                }
            )
            logger.info("daily digest sent to=%s result=%s", to_email, result)

        record_id = _persist_daily_digest_record(
            subject=subject,
            day=day,
            body_html=body,
            meeting_minutes_html=meeting_minutes_html,
            recipients=recipients,
            delivery_rows=delivery_rows,
            delivered=any_delivered,
        )
        if record_id:
            try:
                from modstore_server.release_train import bump_release_train

                bump_release_train(record_id=int(record_id), digest_day=day)
            except Exception:
                logger.exception("daily digest: release_train bump failed record_id=%s", record_id)
        if record_id:
            _run_scheduled_digest_vibe_prep(
                record_id=record_id,
                day=day,
                subject=subject,
                body_html=body,
                body_text=_html_to_text_excerpt(body),
                meeting_minutes_html=meeting_minutes_html,
                surface_audit_excerpt=surface_audit_excerpt_markdown(surface_audit_report),
            )
        _notify_daily_digest_in_app(subject, any_delivered)

        # digest_identity 与邮件/存档 HTML 中展示的校验码一致；解锁校验依赖 OpsApprovalToken 行。
        # 若仅因 SMTP 失败导致 any_delivered=False，仍应入库身份码，否则后台「摘要存档」里能看到的码在市场端永远无效。
        identity_tokens = [t for t in (token_batch or []) if getattr(t, "kind", None) == "digest_identity"]
        deploy_tokens = [t for t in (token_batch or []) if getattr(t, "kind", None) != "digest_identity"]
        if identity_tokens:
            with sf() as session:
                for t in identity_tokens:
                    session.add(t)
                session.commit()
            logger.info("daily digest: persisted %d digest_identity token(s)", len(identity_tokens))
        if deploy_tokens and any_delivered:
            with sf() as session:
                for t in deploy_tokens:
                    session.add(t)
                session.commit()
            logger.info("daily digest: persisted %d deploy approval token(s)", len(deploy_tokens))
    except Exception:
        logger.exception("daily digest failed")


def cron_trigger_for_digest():
    """默认每天 08:00（北京时间）。可用 ``MODSTORE_DAILY_DIGEST_HOUR`` / ``MINUTE`` 覆盖。"""
    try:
        from zoneinfo import ZoneInfo

        tz_name = os.environ.get("MODSTORE_DAILY_DIGEST_TZ", "Asia/Shanghai").strip()
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = None

    hour = int(os.environ.get("MODSTORE_DAILY_DIGEST_HOUR", "8"))
    minute = int(os.environ.get("MODSTORE_DAILY_DIGEST_MINUTE", "0"))

    from apscheduler.triggers.cron import CronTrigger

    if tz is not None:
        return CronTrigger(hour=hour, minute=minute, timezone=tz)
    return CronTrigger(hour=hour, minute=minute)
