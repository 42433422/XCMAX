# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.daily_digest")


def _status_pill(text: str, tone: str = "ok") -> str:
    """胶囊状态标签。"""
    (fg, bg, bd) = _facade()._DIGEST_TONES.get(tone, _facade()._DIGEST_TONES["muted"])
    return f'<span style="display:inline-block;padding:3px 11px;border-radius:999px;background:{bg};color:{fg};border:1px solid {bd};font-size:12px;font-weight:700;line-height:1.4;white-space:nowrap">{text}</span>'


def _section_title(
    title: str, *, icon: str = "", subtitle: str = "", accent: str = "#2563eb"
) -> str:
    """统一小节标题：左侧彩色竖条 + 图标 + 标题 +（可选）副标题。"""
    icon_html = (
        f'<span style="font-size:16px;margin-right:7px;vertical-align:-1px">{icon}</span>'
        if icon
        else ""
    )
    sub_html = (
        f'<span style="font-size:11px;color:#94a3b8;font-weight:500;margin-left:10px">{subtitle}</span>'
        if subtitle
        else ""
    )
    return f'<div style="display:flex;align-items:center;margin:0 0 12px"><span style="display:inline-block;width:4px;height:18px;border-radius:3px;background:{accent};margin-right:10px;flex:0 0 auto"></span><span style="font-size:15px;font-weight:800;color:#0f172a;letter-spacing:.2px">{icon_html}{title}</span>{sub_html}</div>'


def _hero_overview_html(
    *, met_ok: int, met_fail: int, inc_n: int, emp_n: int, ops_n: int, cursor_hits: int
) -> str:
    """页眉下方「今日总览」横幅：一句话给出健康结论 + 关键数字，开门见山。"""
    total = met_ok + met_fail
    rate = f"{met_ok * 100 // total}%" if total > 0 else "—"
    if met_fail > 0:
        (tone, verdict, dot) = ("crit", "需要处理", "#dc2626")
    elif inc_n > 0 or cursor_hits > 0:
        (tone, verdict, dot) = ("warn", "需关注", "#d97706")
    else:
        (tone, verdict, dot) = ("ok", "系统健康", "#16a34a")
    (fg, bg, bd) = _facade()._DIGEST_TONES[tone]
    notes = [f"任务成功率 {rate}", f"系统事件 {inc_n} 条", f"{emp_n} 名编制在岗"]
    if ops_n:
        notes.append(f"运维操作 {ops_n} 条")
    if cursor_hits > 0:
        notes.append(f"代码助手 {cursor_hits} 行异常")
    summary_line = " · ".join(notes)

    def _stat(value: str, label: str, color: str = "#0f172a") -> str:
        return f'<td style="padding:0 0 0 20px;text-align:center;vertical-align:middle"><div style="font-size:22px;font-weight:800;color:{color};line-height:1;font-variant-numeric:tabular-nums">{value}</div><div style="font-size:10px;color:#94a3b8;margin-top:4px;font-weight:600;letter-spacing:.3px">{label}</div></td>'

    rate_color = "#16a34a" if met_fail == 0 else "#dc2626"
    inc_color = "#16a34a" if inc_n == 0 else "#d97706"
    stats = (
        '<table role="presentation" style="border-collapse:collapse"><tr>'
        + _stat(rate, "成功率", rate_color)
        + _stat(str(inc_n), "异常", inc_color)
        + _stat(str(emp_n), "在岗")
        + "</tr></table>"
    )
    return f'\n<div style="padding:18px 16px 2px">\n  <div style="background:{bg};border:1px solid {bd};border-radius:14px;padding:15px 18px">\n    <table role="presentation" style="width:100%;border-collapse:collapse"><tr>\n      <td style="vertical-align:middle">\n        <div style="font-size:11px;font-weight:700;color:{fg};letter-spacing:1.2px">今日总览</div>\n        <div style="margin-top:5px;font-size:19px;font-weight:800;color:#0f172a;letter-spacing:.3px">\n          <span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:{dot};margin-right:8px;vertical-align:middle"></span>{verdict}\n        </div>\n        <div style="margin-top:6px;font-size:12px;color:#64748b">{summary_line}</div>\n      </td>\n      <td style="vertical-align:middle;text-align:right;white-space:nowrap">{stats}</td>\n    </tr></table>\n  </div>\n</div>\n'


def _render_digest_document(
    *,
    cn_display: str,
    hero_html: str = "",
    kpi_cards_html: str = "",
    imap_block: str = "",
    audit_block: str = "",
    autonomy_block: str = "",
    consistency_block: str = "",
    tls_cert_section_html: str = "",
    staged_section_html: str = "",
    work_summary_html: str = "",
    meeting_block: str = "",
    surface_block: str = "",
    briefs_block: str = "",
) -> str:
    """把各段 HTML 拼装为完整邮件文档（纯函数 · 无 DB，便于本地预览）。"""
    return f"""\n<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'PingFang SC','Microsoft YaHei',Helvetica,Arial,sans-serif;line-height:1.55;color:#0f172a;background:#eef2f8;padding:24px 12px">\n<div style="max-width:660px;margin:0 auto;background:#ffffff;border-radius:16px;overflow:hidden;border:1px solid #e6eaf0;box-shadow:0 12px 34px rgba(15,23,42,0.10)">\n\n<div style="height:4px;background:linear-gradient(90deg,#22d3ee,#2563eb,#4f46e5);background-color:#2563eb"></div>\n\n<div style="background:linear-gradient(135deg,#1e3a8a 0%,#1d4ed8 55%,#2563eb 100%);background-color:#1d4ed8;padding:26px 24px 24px">\n  <table role="presentation" style="width:100%;border-collapse:collapse"><tr>\n    <td style="vertical-align:middle;white-space:nowrap">\n      <span style="display:inline-block;width:40px;height:40px;border-radius:11px;background:rgba(255,255,255,0.16);border:1px solid rgba(255,255,255,0.30);color:#ffffff;font-size:21px;font-weight:800;text-align:center;line-height:40px;vertical-align:middle">M</span>\n      <span style="display:inline-block;vertical-align:middle;margin-left:13px">\n        <span style="display:block;font-size:21px;font-weight:800;color:#ffffff;letter-spacing:.6px;line-height:1.1">MODstore</span>\n        <span style="display:block;font-size:11px;color:#bfdbfe;letter-spacing:2px;margin-top:3px">AI 运营中枢</span>\n      </span>\n    </td>\n    <td style="vertical-align:middle;text-align:right">\n      <span style="display:inline-block;padding:5px 13px;border-radius:999px;background:rgba(255,255,255,0.14);border:1px solid rgba(255,255,255,0.28);color:#e0f2fe;font-size:11px;font-weight:600">每日 08:00 CST</span>\n    </td>\n  </tr></table>\n  <div style="margin-top:20px;font-size:25px;font-weight:800;color:#ffffff;letter-spacing:.5px">每日运营摘要</div>\n  <div style="margin-top:6px;font-size:13px;color:#bfdbfe">{cn_display}</div>\n</div>\n\n{hero_html}\n\n{imap_block}\n{audit_block}\n{autonomy_block}\n\n<div style="padding:14px 16px 4px">\n  {kpi_cards_html}\n</div>\n\n{consistency_block}\n{tls_cert_section_html}\n{staged_section_html}\n{work_summary_html}\n{meeting_block}\n{surface_block}\n{briefs_block}\n\n<div style="border-top:1px solid #eef2f7;padding:18px 24px;text-align:center;background:#fafbfd">\n  <div style="font-size:12px;font-weight:700;color:#475569;letter-spacing:.5px">MODstore · AI 运营中枢</div>\n  <div style="font-size:11px;color:#94a3b8;margin-top:5px">自动发送 · 每日 08:00 CST · 回复本邮件可进行审批操作</div>\n</div>\n\n</div>\n</div>\n"""


def _persist_daily_digest_record(
    *,
    subject: str,
    day: str,
    body_html: str,
    meeting_minutes_html: str,
    recipients: _facade().Sequence[str],
    delivery_rows: _facade().Sequence[_facade().Dict[str, _facade().Any]],
    delivered: bool,
) -> int | None:
    """Store the same daily digest that was emailed so the admin UI can review it later."""
    try:
        sf = _facade().get_session_factory()
        with sf() as session:
            row = _facade().DailyDigestRecord(
                day=day,
                subject=subject,
                body_html=body_html,
                body_text=_facade()._html_to_text_excerpt(body_html),
                meeting_minutes_html=meeting_minutes_html,
                recipients_json=_facade().json.dumps(list(recipients), ensure_ascii=False),
                delivery_json=_facade().json.dumps(
                    list(delivery_rows), ensure_ascii=False, default=str
                ),
                delivered=bool(delivered),
                source="daily_digest",
            )
            session.add(row)
            session.flush()
            record_id = int(row.id)
            session.commit()
            return record_id
    except Exception:
        _facade().logger.exception("daily digest: persist record failed")
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
    enabled = (
        (_facade().os.environ.get("MODSTORE_DAILY_VIBE_PREP_ENABLED", "1") or "").strip().lower()
    )
    if enabled in ("0", "false", "no", "off"):
        _facade().logger.info(
            "daily digest: vibe prep disabled by MODSTORE_DAILY_VIBE_PREP_ENABLED"
        )
        return
    try:
        max_emp = max(
            1,
            min(int(_facade().os.environ.get("MODSTORE_DAILY_VIBE_PREP_MAX_EMPLOYEES", "52")), 128),
        )
    except ValueError:
        max_emp = 52
    raw_uid = (
        _facade().os.environ.get("MODSTORE_DAILY_VIBE_PREP_USER_ID")
        or _facade().os.environ.get("MODSTORE_DAILY_BRIEF_USER_ID")
        or "0"
    ).strip()
    user_id = int(raw_uid) if raw_uid.isdigit() else 0
    from modstore_server.digest_vibe_prep import (
        persist_vibe_prep_on_digest_record,
        run_digest_vibe_prep_sync,
    )

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
    if result.get("ok"):
        try:
            from modstore_server.digest_action_items import parse_and_store_action_items

            rt_after = ""
            try:
                from modstore_server.release_train import release_train_context_for_digest

                rt_after = str(
                    (release_train_context_for_digest(record_id) or {}).get("release_train_after")
                    or ""
                )
            except Exception:
                rt_after = ""
            ai = parse_and_store_action_items(
                day=day,
                record_id=record_id,
                updates_markdown=str(result.get("updates_markdown") or ""),
                patches_markdown=str(result.get("patches_markdown") or ""),
                rt_version=rt_after,
            )
            _facade().logger.info(
                "daily digest: action items record_id=%s patch=%s update=%s",
                record_id,
                ai.get("patch"),
                ai.get("update"),
            )
            try:
                from modstore_server.employee_collab_reporter import report_action_items

                report_action_items(day=day, record_id=record_id)
            except Exception:
                _facade().logger.exception(
                    "collab report (action items) failed record_id=%s", record_id
                )
            try:
                from modstore_server.public_action_board import write_public_action_board

                pub = write_public_action_board(day=day)
                _facade().logger.info(
                    "daily digest: public action board day=%s written=%s",
                    pub.get("day"),
                    len(pub.get("written") or []),
                )
            except Exception:
                _facade().logger.exception(
                    "daily digest: public action board failed record_id=%s", record_id
                )
        except Exception:
            _facade().logger.exception(
                "daily digest: action items store failed record_id=%s", record_id
            )
    if result.get("ok"):
        from modstore_server.digest_vibe_line_dispatch import dispatch_vibe_prep_to_production_lines

        dispatch = dispatch_vibe_prep_to_production_lines(record_id, result)
        if dispatch.get("ok"):
            _facade().logger.info(
                "daily digest: vibe line dispatch ok record_id=%s sections=%s pw=%s ps=%s sr=%s",
                record_id,
                dispatch.get("total_sections"),
                (dispatch.get("line_meta") or {}).get("P-W", {}).get("total_sections"),
                (dispatch.get("line_meta") or {}).get("P-S", {}).get("total_sections"),
                (dispatch.get("line_meta") or {}).get("S-R", {}).get("total_sections"),
            )
        elif not dispatch.get("skipped"):
            _facade().logger.warning(
                "daily digest: vibe line dispatch failed record_id=%s err=%s",
                record_id,
                dispatch.get("error"),
            )
    if result.get("ok"):
        _facade().logger.info(
            "daily digest: vibe prep ok record_id=%s employees=%s model=%s",
            record_id,
            result.get("employee_count"),
            result.get("model"),
        )
    else:
        _facade().logger.warning(
            "daily digest: vibe prep failed record_id=%s err=%s", record_id, result.get("error")
        )


def _repo_root() -> _facade().Path:
    env = _facade().os.environ.get("MODSTORE_REPO_ROOT", "").strip()
    if env:
        return _facade().Path(env).resolve()
    try:
        from modstore_server.integrations.ops_action_handlers import repo_root as _ops_rr

        return _facade().Path(_ops_rr())
    except Exception:
        p = _facade().Path(__file__).resolve()
        deploy = p.parents[1]
        if (deploy / "pyproject.toml").is_file():
            return deploy
        if len(p.parents) > 2:
            return p.parents[2]
        return deploy


def _consistency_check_html(repo_root: _facade().Path) -> str:
    """运行 ``run_full_consistency_check`` 并返回邮件 HTML 段落；失败或非致命异常时不阻断摘要。"""
    raw = (_facade().os.environ.get("MODSTORE_DAILY_DIGEST_CONSISTENCY") or "1").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return ""
    try:
        from modstore_server.tools.doc_consistency_checker import run_full_consistency_check

        result = run_full_consistency_check(repo_root)
    except Exception as exc:
        _facade().logger.exception("daily digest: doc consistency check failed")
        esc = _facade().html.escape(str(exc)[:400])
        return f'\n<div style="padding:0 24px 12px">\n  <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:10px;padding:12px 14px;font-size:13px;color:#b91c1c">\n    <strong>文档一致性校验</strong> 未能完成：{esc}\n  </div>\n</div>\n'
    status = str(result.get("status") or "")
    total_errors = int(result.get("total_errors") or 0)
    total_issues = int(result.get("total_issues") or 0)
    issues = result.get("issues") if isinstance(result.get("issues"), list) else []
    max_lines = 48
    rows: _facade().List[str] = []
    for it in issues[:max_lines]:
        if not isinstance(it, dict):
            continue
        emp = _facade().html.escape(str(it.get("employee") or "?"))
        sev = _facade().html.escape(str(it.get("severity") or ""))
        typ = _facade().html.escape(str(it.get("type") or ""))
        desc = _facade().html.escape(str(it.get("description") or "")[:500])
        rows.append(
            f'<tr><td style="padding:4px 8px;border-bottom:1px solid #e2e8f0;font-size:11px">{emp}</td><td style="padding:4px 8px;border-bottom:1px solid #e2e8f0;font-size:11px;color:#64748b">{sev}</td><td style="padding:4px 8px;border-bottom:1px solid #e2e8f0;font-size:11px;color:#64748b">{typ}</td><td style="padding:4px 8px;border-bottom:1px solid #e2e8f0;font-size:11px">{desc}</td></tr>'
        )
    extra = ""
    if len(issues) > max_lines:
        extra = f'<p style="margin:8px 0 0;font-size:11px;color:#64748b">另有 {len(issues) - max_lines} 条未展示。</p>'
    ok_bg = "#f0fdf4" if total_errors == 0 else "#fffbeb"
    ok_border = "#bbf7d0" if total_errors == 0 else "#fde68a"
    ok_title = (
        "文档一致性（yuangon）" if total_errors == 0 else "文档一致性（yuangon · 存在 error）"
    )
    summary = f'<p style="margin:0 0 8px;font-size:12px;color:#475569">状态 <code>{_facade().html.escape(status)}</code> · error 级 {total_errors} · 共 {total_issues} 条</p>'
    table = ""
    if rows:
        table = (
            '<table style="width:100%;border-collapse:collapse;margin-top:6px;font-size:11px"><thead><tr><th align="left" style="padding:6px 8px;border-bottom:2px solid #e2e8f0">employee</th><th align="left" style="padding:6px 8px;border-bottom:2px solid #e2e8f0">severity</th><th align="left" style="padding:6px 8px;border-bottom:2px solid #e2e8f0">type</th><th align="left" style="padding:6px 8px;border-bottom:2px solid #e2e8f0">description</th></tr></thead><tbody>'
            + "".join(rows)
            + "</tbody></table>"
        )
    title_accent = "#16a34a" if total_errors == 0 else "#d97706"
    return f"""\n<div style="padding:6px 24px 12px">\n  {_facade()._section_title(ok_title, icon='&#x1F4D1;', accent=title_accent)}\n  <div style="background:{ok_bg};border:1px solid {ok_border};border-radius:12px;padding:14px 16px">\n    {summary}\n    {table}\n    {extra}\n  </div>\n</div>\n"""


def _git_line(args: list[str], cwd: _facade().Path, timeout: float = 8.0) -> str:
    try:
        p = _facade().subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        return (p.stdout or "").strip() or (p.stderr or "").strip()[:500]
    except (
        OSError,
        _facade().subprocess.TimeoutExpired,
        _facade().subprocess.SubprocessError,
    ) as e:
        return f"(git 不可用: {e})"


def _git_worktree_root(root: _facade().Path, timeout: float = 5.0) -> bool:
    """``root`` 是否为 Git 工作副本（含 ``.git`` 为文件、worktree 等）；不依赖 ``(root / '.git').is_dir()``。"""
    if not _facade().shutil.which("git"):
        return False
    try:
        p = _facade().subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        return p.returncode == 0 and (p.stdout or "").strip().lower() == "true"
    except (OSError, _facade().subprocess.TimeoutExpired, _facade().subprocess.SubprocessError):
        return False


def _digest_commit_display(raw: str) -> str:
    """环境变量/构建元数据常为全 SHA，摘要里缩短展示。"""
    s = (raw or "").strip()
    if len(s) >= 12 and len(s) <= 64 and all((c in "0123456789abcdefABCDEF" for c in s)):
        return s[:7]
    if len(s) > 20:
        return s[:20] + "…"
    return s


def _digest_git_branch_and_head(root: _facade().Path) -> _facade().Tuple[str, str]:
    """分支与 HEAD：环境变量 → 本地 git（若可为工作副本）→ ``.modstore_build.json`` 补缺。

    镜像内可能同时存在构建时写入的 ``.modstore_build.json`` 与挂载的真实 ``.git``；
    此时以 **git 为准**（除非环境变量已显式提供对应字段）。
    """
    br = (_facade().os.environ.get("MODSTORE_GIT_BRANCH") or "").strip() or (
        _facade().os.environ.get("GIT_BRANCH") or ""
    ).strip()
    co_raw = (
        (_facade().os.environ.get("MODSTORE_GIT_COMMIT") or "").strip()
        or (_facade().os.environ.get("GIT_COMMIT") or "").strip()
        or (_facade().os.environ.get("MODSTORE_GIT_SHA") or "").strip()
        or (_facade().os.environ.get("GIT_SHA") or "").strip()
        or (_facade().os.environ.get("COMMIT_SHA") or "").strip()
        or (_facade().os.environ.get("SOURCE_COMMIT") or "").strip()
        or (_facade().os.environ.get("VCS_REF") or "").strip()
    )
    co = _facade()._digest_commit_display(co_raw) if co_raw else ""
    git_ok = _facade()._git_worktree_root(root)

    def _fill_git_gaps() -> None:
        nonlocal br, co
        if not git_ok:
            return
        if not br:
            gb = _facade()._git_line(["rev-parse", "--abbrev-ref", "HEAD"], root)
            if not gb.startswith("(git 不可用"):
                br = gb
        if not co:
            gh = _facade()._git_line(["rev-parse", "--short", "HEAD"], root)
            if not gh.startswith("(git 不可用"):
                co = gh

    _fill_git_gaps()
    if not br or not co:
        info = root / ".modstore_build.json"
        if info.is_file():
            try:
                data = _facade().json.loads(info.read_text(encoding="utf-8"))
                if not br:
                    br = str(data.get("branch") or data.get("ref") or "").strip()
                if not co:
                    jc = str(data.get("commit") or data.get("sha") or "").strip()
                    if jc:
                        co = _facade()._digest_commit_display(jc)
            except (OSError, _facade().json.JSONDecodeError, TypeError, ValueError):
                pass
    _fill_git_gaps()
    return (br or "—", co or "—")


def _pytest_lastfailed_snippet(root: _facade().Path, limit: int = 1200) -> str:
    p = root / "MODstore_deploy" / ".pytest_cache" / "v" / "cache" / "lastfailed"
    if not p.is_file() or p.stat().st_size == 0:
        return "无（lastfailed 为空或不存在）"
    try:
        t = p.read_text(encoding="utf-8", errors="replace")[:limit]
        return _facade().html.escape(t)
    except OSError as e:
        return _facade().html.escape(str(e))


def _cursor_error_lines_count(root: _facade().Path) -> int:
    n = 0
    try:
        for f in sorted(root.glob(".cursor_*_log.txt")):
            try:
                for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                    low = line.lower()
                    if any((x in low for x in ("error", "fail", "exception"))):
                        n += 1
            except OSError:
                continue
    except OSError:
        pass
    return n


def _audit_digest_hint_html() -> str:
    """可选：解释为何运维审计 / 事件计数可能为 0（``MODSTORE_DIGEST_AUDIT_HINT=1``）。"""
    raw = _facade().os.environ.get("MODSTORE_DIGEST_AUDIT_HINT", "").strip().lower()
    if raw not in ("1", "true", "yes"):
        return ""
    db_path = (_facade().os.environ.get("MODSTORE_DB_PATH") or "").strip() or "（默认 SQLite 路径）"
    sch_running = False
    try:
        from modstore_server.workflow_scheduler import _scheduler as _sch

        sch_running = _sch is not None and bool(getattr(_sch, "running", False))
    except Exception:
        pass
    nginx_p = (
        _facade().os.environ.get("OPS_NGINX_ERROR_LOG", "").strip() or "/var/log/nginx/error.log"
    )
    return f"""<div style="margin-top:12px;padding:10px;border:1px solid #e2e8f0;border-radius:8px;background:#f8fafc"><p style="margin:0 0 8px;font-size:13px;color:#334155"><strong>计数说明（调试）</strong>：近 24h「运维审计」仅在执行过运维 shell 指令并写入审计表后增加；「事件入库」依赖 APScheduler 定时采集器命中 pytest/nginx/cursor 规则。</p><ul style="margin:0;padding-left:18px;font-size:12px;color:#64748b;line-height:1.5"><li>MODSTORE_DB_PATH：<code>{_facade().html.escape(db_path)}</code></li><li>APScheduler 运行中：{('是' if sch_running else '否')}（未启动则采集任务不跑）</li><li>OPS_NGINX_ERROR_LOG：<code>{_facade().html.escape(nginx_p)}</code>（文件不存在则跳过 nginx 采集）</li></ul></div>"""


def _publish_tls_cert_security_alerts(results: _facade().Sequence[_facade().Any]) -> None:
    """WARNING/CRITICAL 写入 ``security.alert``（按 UTC 日期去重，避免 incident_bus 10 分钟窗重复）。"""
    if not results:
        return
    try:
        from modstore_server.incident_bus import publish as incident_publish
    except Exception:
        _facade().logger.exception("tls cert: incident_bus unavailable")
        return
    today = _facade().datetime.now(_facade().timezone.utc).strftime("%Y-%m-%d")
    for r in results:
        level = getattr(r, "level", "")
        if level not in ("WARNING", "CRITICAL"):
            continue
        path = str(getattr(r, "path", "") or "")
        days_remaining = getattr(r, "days_remaining", None)
        na = getattr(r, "not_after_utc", None)
        na_iso = na.isoformat() if na is not None else ""
        fp_raw = f"tls_cert_expiry:{path}:{today}:{level}"
        fp = _facade().hashlib.sha256(fp_raw.encode("utf-8")).hexdigest()[:64]
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
            _facade().logger.exception("tls cert: incident publish failed path=%s", path[:160])


def _tls_cert_digest_html(results: _facade().Sequence[_facade().Any]) -> str:
    """TLS 巡检表格（INFO/WARNING/CRITICAL）；无命中返回空串。"""
    if not results:
        return ""
    rows_html: _facade().List[str] = []
    for r in results:
        level = getattr(r, "level", "OK")
        if level == "OK":
            continue
        path_e = _facade().html.escape(str(getattr(r, "path", "")))
        na = getattr(r, "not_after_utc", None)
        na_s = na.strftime("%Y-%m-%d %H:%M UTC") if na is not None else "?"
        (badge_bg, badge_fg) = ("#fef2f2", "#b91c1c")
        if level == "INFO":
            (badge_bg, badge_fg) = ("#eff6ff", "#1e40af")
        elif level == "WARNING":
            (badge_bg, badge_fg) = ("#fffbeb", "#b45309")
        dr = getattr(r, "days_remaining", "?")
        rows_html.append(
            f'<tr><td style="padding:6px 8px;border-bottom:1px solid #e2e8f0;font-size:12px"><span style="background:{badge_bg};color:{badge_fg};padding:2px 8px;border-radius:6px;font-weight:600">{_facade().html.escape(str(level))}</span></td><td style="padding:6px 8px;border-bottom:1px solid #e2e8f0;font-size:11px;word-break:break-all">{path_e}</td><td style="padding:6px 8px;border-bottom:1px solid #e2e8f0;font-size:11px">{_facade().html.escape(str(dr))}</td><td style="padding:6px 8px;border-bottom:1px solid #e2e8f0;font-size:11px">{_facade().html.escape(na_s)}</td></tr>'
        )
    if not rows_html:
        return ""
    table = (
        '<table style="width:100%;border-collapse:collapse;margin-top:8px;font-size:11px"><thead><tr><th align="left" style="padding:6px 8px;border-bottom:2px solid #e2e8f0">级别</th><th align="left" style="padding:6px 8px;border-bottom:2px solid #e2e8f0">证书路径</th><th align="left" style="padding:6px 8px;border-bottom:2px solid #e2e8f0">剩余天数</th><th align="left" style="padding:6px 8px;border-bottom:2px solid #e2e8f0">notAfter</th></tr></thead><tbody>'
        + "".join(rows_html)
        + "</tbody></table>"
    )
    return (
        '<div style="padding:6px 24px 12px">'
        + _facade()._section_title("TLS 证书到期巡检", icon="&#x1F510;", accent="#d97706")
        + f'<div style="background:#fffbeb;border:1px solid #fde68a;border-radius:12px;padding:14px 16px;font-size:13px;color:#92400e"><p style="margin:0 0 8px">以下证书已达到 INFO/WARNING/CRITICAL 阈值（见 CERT_EXPIRY_*）。WARNING/CRITICAL 已写入安全事件 <code>security.alert</code>。</p>{table}</div></div>'
    )


def _nginx_tail_hint() -> str:
    log_path = (
        _facade().os.environ.get("OPS_NGINX_ERROR_LOG", "").strip() or "/var/log/nginx/error.log"
    )
    p = _facade().Path(log_path)
    if not p.is_file():
        return f"日志文件不存在或未挂载: {_facade().html.escape(log_path)}"
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
        tail = "".join(text.splitlines(True)[-40:])
        low = tail.lower()
        flag = "含 error 关键字" if "error" in low else "未见明显 error 尾部"
        return (
            f"{_facade().html.escape(flag)}（末尾约 40 行，路径 {_facade().html.escape(log_path)}）"
        )
    except OSError as e:
        return _facade().html.escape(str(e))


def _run_pytest_summary(repo: _facade().Path) -> str:
    deploy = repo / "MODstore_deploy"
    if not (deploy / "tests").is_dir():
        return "<pre>跳过：未找到 MODstore_deploy/tests</pre>"
    try:
        proc = _facade().subprocess.run(
            [_facade().sys.executable, "-m", "pytest", "tests", "-q", "--tb=no", "--maxfail=15"],
            cwd=str(deploy),
            capture_output=True,
            text=True,
            timeout=int(_facade().os.environ.get("MODSTORE_DAILY_DIGEST_PYTEST_TIMEOUT", "900")),
            shell=False,
            env={**_facade().os.environ, "PYTHONWARNINGS": "ignore"},
        )
        out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        out = out[-12000:]
        esc = _facade().html.escape(out)
        rc = proc.returncode
        status = "通过" if rc == 0 else f"失败 exit={rc}"
        return f'<p><strong>pytest</strong>：{_facade().html.escape(status)}</p><pre style="white-space:pre-wrap;font-size:12px">{esc}</pre>'
    except _facade().subprocess.TimeoutExpired:
        return "<pre>pytest 超时（见 MODSTORE_DAILY_DIGEST_PYTEST_TIMEOUT）</pre>"
    except Exception as e:
        return f"<pre>{_facade().html.escape(str(e))}</pre>"


def _digest_system_work_summary_html(
    *,
    host: str,
    git_branch: str,
    git_head: str,
    repo_root: _facade().Path,
    emp_n: int,
    catalog_pack_n: int = 0,
    met_ok: int,
    met_fail: int,
    ops_n: int,
    inc_n: int,
    cursor_hits: int,
) -> str:
    """邮件「一、系统状态」：结构化键值对展示，替代原文段落。"""
    rb = _facade().html.escape(str(repo_root))
    total = met_ok + met_fail
    rate = f"{met_ok * 100 // total}%" if total > 0 else "--"

    def _kv_row(label: str, value: str, extra_style: str = "") -> str:
        return f'<tr style="{extra_style}"><td style="padding:7px 12px;color:#64748b;font-size:13px;white-space:nowrap;border-bottom:1px solid #f1f5f9">{label}</td><td style="padding:7px 12px;color:#1e293b;font-size:13px;font-weight:600;border-bottom:1px solid #f1f5f9">{value}</td></tr>'

    rows = [
        _kv_row("仓库分支", _facade().html.escape(git_branch)),
        _kv_row(
            "最新提交",
            f'<code style="background:#f1f5f9;padding:2px 6px;border-radius:4px;font-size:12px">{_facade().html.escape(git_head)}</code>',
        ),
        _kv_row("运行主机", _facade().html.escape(host)),
        _kv_row("数据目录", f'<span style="font-size:11px;word-break:break-all">{rb}</span>'),
    ]
    system_table = (
        '<table style="width:100%;border-collapse:collapse;margin:0">' + "".join(rows) + "</table>"
    )
    rows2 = [_kv_row("编制在岗", f"{emp_n} 人")]
    if catalog_pack_n and catalog_pack_n != emp_n:
        rows2.append(_kv_row("Catalog 员工包", f"{catalog_pack_n} 个"))
    rows2.extend(
        [
            _kv_row("今日任务执行", f"{total} 次"),
            _kv_row("成功率", rate, extra_style="" if met_fail == 0 else "background:#fef2f2"),
            _kv_row("运维操作记录", f"{ops_n} 条"),
            _kv_row(
                "系统事件", f"{inc_n} 条", extra_style="" if inc_n == 0 else "background:#fffbeb"
            ),
        ]
    )
    team_table = (
        '<table style="width:100%;border-collapse:collapse;margin:0">' + "".join(rows2) + "</table>"
    )
    cursor_alert = ""
    if cursor_hits > 0:
        cursor_alert = f'<div style="margin-top:10px;padding:10px 14px;background:#fffbeb;border-left:3px solid #f59e0b;border-radius:4px"><span style="font-size:13px;color:#92400e">代码助手异常：近 24h 有 <strong>{cursor_hits}</strong> 行 error，建议排查。</span></div>'
    return f"""\n<div style="padding:14px 24px 8px">\n  {_facade()._section_title('系统状态', icon='&#x1F5A5;&#xFE0F;', accent='#2563eb')}\n  <div style="background:#f8fafc;border-radius:12px;padding:4px 14px 8px;margin-bottom:16px;border:1px solid #e6eaf0">\n    {system_table}\n  </div>\n  {_facade()._section_title('团队活跃度', icon='&#x1F4C8;', accent='#0d9488')}\n  <div style="background:#f8fafc;border-radius:12px;padding:4px 14px 8px;border:1px solid #e6eaf0">\n    {team_table}\n  </div>\n  {cursor_alert}\n</div>\n"""


def _digest_kpi_cards_html(
    *, met_ok: int, met_fail: int, emp_n: int, ops_n: int, inc_n: int
) -> str:
    """邮件顶部 KPI 卡片区：4 个核心指标，图标 + 大数字 + 顶部强调条 + 颜色编码。"""
    cards: _facade().List[str] = []

    def _card(
        value: str,
        label: str,
        *,
        icon: str,
        accent: str,
        color: str,
        bg: str,
        border: str,
        sub: str = "",
        sub_color: str = "#94a3b8",
    ) -> str:
        sub_html = (
            f'<div style="font-size:11px;color:{sub_color};margin-top:3px;font-weight:600">{sub}</div>'
            if sub
            else ""
        )
        return f'<td style="width:25%;padding:5px;vertical-align:top"><div style="border-radius:12px;border:1px solid {border};background:{bg};overflow:hidden"><div style="height:3px;background:{accent};line-height:3px;font-size:0">&nbsp;</div><div style="padding:13px 8px 14px;text-align:center"><div style="font-size:17px;line-height:1">{icon}</div><div style="font-size:27px;font-weight:800;color:{color};line-height:1.15;margin-top:3px;font-variant-numeric:tabular-nums">{value}</div><div style="font-size:11px;color:#64748b;margin-top:5px;font-weight:600">{label}</div>{sub_html}</div></div></td>'

    cards.append(
        _card(
            str(emp_n),
            "编制在岗",
            icon="&#x1F465;",
            accent="#2563eb",
            color="#1d4ed8",
            bg="#eff6ff",
            border="#bfdbfe",
        )
    )
    if met_fail == 0:
        cards.append(
            _card(
                str(met_ok),
                "任务成功",
                icon="&#x2705;",
                accent="#16a34a",
                color="#047857",
                bg="#ecfdf5",
                border="#a7f3d0",
                sub="全部成功",
                sub_color="#16a34a",
            )
        )
    else:
        cards.append(
            _card(
                str(met_ok),
                "任务成功",
                icon="&#x26A0;&#xFE0F;",
                accent="#ea580c",
                color="#c2410c",
                bg="#fff7ed",
                border="#fed7aa",
                sub=f"失败 {met_fail} 次",
                sub_color="#ea580c",
            )
        )
    if ops_n == 0:
        cards.append(
            _card(
                "0",
                "运维操作",
                icon="&#x1F6E0;&#xFE0F;",
                accent="#94a3b8",
                color="#64748b",
                bg="#f8fafc",
                border="#e2e8f0",
            )
        )
    else:
        cards.append(
            _card(
                str(ops_n),
                "运维操作",
                icon="&#x1F6E0;&#xFE0F;",
                accent="#2563eb",
                color="#1d4ed8",
                bg="#eff6ff",
                border="#bfdbfe",
            )
        )
    if inc_n == 0:
        cards.append(
            _card(
                "0",
                "系统事件",
                icon="&#x1F514;",
                accent="#16a34a",
                color="#047857",
                bg="#ecfdf5",
                border="#a7f3d0",
                sub="无异常",
                sub_color="#16a34a",
            )
        )
    else:
        cards.append(
            _card(
                str(inc_n),
                "系统事件",
                icon="&#x1F514;",
                accent="#ea580c",
                color="#c2410c",
                bg="#fff7ed",
                border="#fed7aa",
                sub="待处理",
                sub_color="#ea580c",
            )
        )
    return (
        '<table role="presentation" style="width:100%;border-collapse:collapse;margin:0"><tr>'
        + "".join(cards)
        + "</tr></table>"
    )
