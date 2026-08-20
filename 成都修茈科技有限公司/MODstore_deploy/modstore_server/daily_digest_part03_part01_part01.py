# mypy: disable-error-code="arg-type, attr-defined, index, no-any-return, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.daily_digest")


def _status_pill(text: str, tone: str = "ok") -> str:
    """胶囊状态标签。"""
    fg, bg, bd = _facade()._DIGEST_TONES.get(tone, _facade()._DIGEST_TONES["muted"])
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
        tone, verdict, dot = ("crit", "需要处理", "#dc2626")
    elif inc_n > 0 or cursor_hits > 0:
        tone, verdict, dot = ("warn", "需关注", "#d97706")
    else:
        tone, verdict, dot = ("ok", "系统健康", "#16a34a")
    fg, bg, bd = _facade()._DIGEST_TONES[tone]
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
    except RECOVERABLE_ERRORS:
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
            min(
                int(_facade().os.environ.get("MODSTORE_DAILY_VIBE_PREP_MAX_EMPLOYEES", "52")),
                128,
            ),
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
                from modstore_server.release_train import (
                    release_train_context_for_digest,
                )

                rt_after = str(
                    (release_train_context_for_digest(record_id) or {}).get("release_train_after")
                    or ""
                )
            except RECOVERABLE_ERRORS:
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
            except RECOVERABLE_ERRORS:
                _facade().logger.exception(
                    "collab report (action items) failed record_id=%s", record_id
                )
            try:
                from modstore_server.public_action_board import (
                    write_public_action_board,
                )

                pub = write_public_action_board(day=day)
                _facade().logger.info(
                    "daily digest: public action board day=%s written=%s",
                    pub.get("day"),
                    len(pub.get("written") or []),
                )
            except RECOVERABLE_ERRORS:
                _facade().logger.exception(
                    "daily digest: public action board failed record_id=%s", record_id
                )
        except RECOVERABLE_ERRORS:
            _facade().logger.exception(
                "daily digest: action items store failed record_id=%s", record_id
            )
    if result.get("ok"):
        from modstore_server.digest_vibe_line_dispatch import (
            dispatch_vibe_prep_to_production_lines,
        )

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
            "daily digest: vibe prep failed record_id=%s err=%s",
            record_id,
            result.get("error"),
        )


def _repo_root() -> _facade().Path:
    env = _facade().os.environ.get("MODSTORE_REPO_ROOT", "").strip()
    if env:
        return _facade().Path(env).resolve()
    try:
        from modstore_server.integrations.ops_action_handlers import (
            repo_root as _ops_rr,
        )

        return _facade().Path(_ops_rr())
    except RECOVERABLE_ERRORS:
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
        from modstore_server.tools.doc_consistency_checker import (
            run_full_consistency_check,
        )

        result = run_full_consistency_check(repo_root)
    except RECOVERABLE_ERRORS as exc:
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
    return f"""\n<div style="padding:6px 24px 12px">\n  {_facade()._section_title(ok_title, icon="&#x1F4D1;", accent=title_accent)}\n  <div style="background:{ok_bg};border:1px solid {ok_border};border-radius:12px;padding:14px 16px">\n    {summary}\n    {table}\n    {extra}\n  </div>\n</div>\n"""


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
    except (
        OSError,
        _facade().subprocess.TimeoutExpired,
        _facade().subprocess.SubprocessError,
    ):
        return False


def _digest_commit_display(raw: str) -> str:
    """环境变量/构建元数据常为全 SHA，摘要里缩短展示。"""
    s = (raw or "").strip()
    if len(s) >= 12 and len(s) <= 64 and all((c in "0123456789abcdefABCDEF" for c in s)):
        return s[:7]
    if len(s) > 20:
        return s[:20] + "…"
    return s
