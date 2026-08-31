# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.daily_digest_metrics import summarize_digest_events
import importlib


def _facade():
    return importlib.import_module("modstore_server.daily_digest")


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
    root = _facade()._repo_root()
    now_utc = _facade().datetime.now(_facade().timezone.utc)
    host = _facade().socket.gethostname()
    git_branch, git_head = _facade()._digest_git_branch_and_head(root)
    sf = _facade().get_session_factory()
    since = _facade().datetime.now(_facade().timezone.utc) - _facade().timedelta(hours=24)
    with sf() as session:
        catalog_pack_n = _facade().count_catalog_employee_packs(session)
        emp_n = _facade().count_on_duty_employees()
        ops_n = (
            session.query(_facade().func.count(_facade().OpsActionAuditLog.id))
            .filter(_facade().OpsActionAuditLog.created_at >= since)
            .scalar()
            or 0
        )
        event_rows = (
            session.query(
                _facade().IncidentEvent.id,
                _facade().IncidentEvent.event_type,
                _facade().IncidentEvent.fingerprint,
            )
            .filter(_facade().IncidentEvent.created_at >= since)
            .all()
        )
        event_n, inc_n = summarize_digest_events(event_rows)
        production_metric_filter = ~_facade().EmployeeExecutionMetric.task.like(
            "[duty-burn-in:%"
        )
        met_ok = (
            session.query(_facade().func.count(_facade().EmployeeExecutionMetric.id))
            .filter(
                _facade().EmployeeExecutionMetric.created_at >= since,
                _facade().EmployeeExecutionMetric.status == "success",
                production_metric_filter,
            )
            .scalar()
            or 0
        )
        met_fail = (
            session.query(_facade().func.count(_facade().EmployeeExecutionMetric.id))
            .filter(
                _facade().EmployeeExecutionMetric.created_at >= since,
                _facade().EmployeeExecutionMetric.status != "success",
                production_metric_filter,
            )
            .scalar()
            or 0
        )
    cursor_hits = _facade()._cursor_error_lines_count(root)
    audit_hint_html = _facade()._audit_digest_hint_html()
    kpi_cards_html = _facade()._digest_kpi_cards_html(
        met_ok=int(met_ok),
        met_fail=int(met_fail),
        emp_n=int(emp_n),
        ops_n=int(ops_n),
        inc_n=int(inc_n),
        event_n=int(event_n),
    )
    consistency_block = _facade()._consistency_check_html(root)
    work_summary_html = _facade()._digest_system_work_summary_html(
        host=host,
        git_branch=git_branch,
        git_head=git_head,
        repo_root=root,
        emp_n=int(emp_n),
        catalog_pack_n=int(catalog_pack_n),
        met_ok=int(met_ok),
        met_fail=int(met_fail),
        ops_n=int(ops_n),
        inc_n=int(inc_n),
        event_n=int(event_n),
        cursor_hits=int(cursor_hits),
    )
    briefs_block = ""
    if (employee_briefs_html or "").strip():
        briefs_block = f"""\n<div style="padding:6px 24px 16px">\n  {_facade()._section_title("AI 改进建议", icon="&#x1F4A1;", accent="#7c3aed")}\n  <div style="background:#faf9ff;border:1px solid #e9e2fb;border-radius:12px;padding:14px 16px">\n    {employee_briefs_html}\n  </div>\n</div>\n"""
    _weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    try:
        from zoneinfo import ZoneInfo

        cn_now = now_utc.astimezone(ZoneInfo("Asia/Shanghai"))
        weekday_cn = _weekdays[cn_now.weekday()]
        cn_display = (
            f"{cn_now.strftime('%Y-%m-%d')} · {weekday_cn} · {cn_now.strftime('%H:%M')} CST"
        )
    except RECOVERABLE_ERRORS:
        cn_display = now_utc.strftime("%Y-%m-%d %H:%M UTC")
    hero_html = _facade()._hero_overview_html(
        met_ok=int(met_ok),
        met_fail=int(met_fail),
        inc_n=int(inc_n),
        event_n=int(event_n),
        emp_n=int(emp_n),
        ops_n=int(ops_n),
        cursor_hits=int(cursor_hits),
    )
    imap_block = ""
    if imap_alert_html:
        imap_block = f'\n<div style="padding:14px 16px 0">\n  <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:12px;padding:12px 15px;font-size:12px;color:#b91c1c">\n    <strong style="font-weight:700">&#x1F4EE; 邮箱告警</strong>&nbsp;&nbsp;{imap_alert_html}\n  </div>\n</div>\n'
    audit_block = ""
    if audit_hint_html:
        audit_block = f'\n<div style="padding:10px 16px 0">\n  {audit_hint_html}\n</div>\n'
    autonomy_html = _facade().autonomy_decisions_digest_html()
    autonomy_block = ""
    if autonomy_html:
        autonomy_block = f'\n<div style="padding:10px 16px 0">\n  {autonomy_html}\n</div>\n'
    meeting_block = ""
    if (meeting_minutes_html or "").strip():
        meeting_block = f"""\n<div style="padding:6px 24px 16px">\n  {_facade()._section_title("员工大会摘要", icon="&#x1F465;", accent="#0891b2")}\n  {meeting_minutes_html}\n</div>\n"""
    surface_block = ""
    if (surface_audit_html or "").strip():
        surface_block = f"""\n<div style="padding:6px 24px 16px">\n  {_facade()._section_title("三端页面截图巡检", icon="&#x1F4F7;", subtitle="P-W 网站 · P-S 软件 · P-App 移动", accent="#0d9488")}\n  {surface_audit_html}\n</div>\n"""
    return _facade()._render_digest_document(
        cn_display=cn_display,
        hero_html=hero_html,
        kpi_cards_html=kpi_cards_html,
        imap_block=imap_block,
        audit_block=audit_block,
        autonomy_block=autonomy_block,
        consistency_block=consistency_block,
        tls_cert_section_html=tls_cert_section_html,
        staged_section_html=staged_section_html,
        work_summary_html=work_summary_html,
        meeting_block=meeting_block,
        surface_block=surface_block,
        briefs_block=briefs_block,
    )


def build_digest_approval_bundle(
    *,
    pending: _facade().Sequence[_facade().Any],
    auth_email: str,
    expires_at: _facade().datetime,
    existing_token_hashes: set[str] | None = None,
) -> _facade().Tuple[_facade().List[_facade().OpsApprovalToken], str]:
    """生成 ``approve_one``（若有 pending）+ 一枚 ``digest_identity`` 身份校验令牌与对应 HTML 段落。"""
    token_batch: _facade().List[_facade().OpsApprovalToken] = []
    seen_hashes = existing_token_hashes if existing_token_hashes is not None else set()
    plain_identity, identity_hash = _facade()._new_unique_ops_token_plain(seen_hashes)
    cards: _facade().List[str] = []
    for s in pending:
        plain, th = _facade()._new_unique_ops_token_plain(seen_hashes)
        token_batch.append(
            _facade().OpsApprovalToken(
                token_hash=th,
                kind="approve_one",
                payload_json=_facade().json.dumps(
                    {"staged_change_id": int(getattr(s, "id"))}, ensure_ascii=False
                ),
                authorized_email=auth_email,
                expires_at=expires_at,
            )
        )
        summ = _facade().html.escape(str(getattr(s, "diff_summary") or "")[:240].replace("\n", " "))
        branch_esc = _facade().html.escape(str(getattr(s, "branch") or ""))
        fc = int(getattr(s, "files_changed_count") or 0)
        cards.append(
            f'<div style="background:#f8fafc;border:1px solid #e6eaf0;border-radius:12px;padding:14px 16px;margin-bottom:10px"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px"><code style="background:#0f172a;color:#e2e8f0;padding:3px 10px;border-radius:6px;font-size:12px">{branch_esc}</code><span style="background:#dbeafe;color:#1e40af;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600">{fc} 个文件</span></div><div style="font-size:12px;color:#64748b;line-height:1.5;margin-bottom:10px">{summ}</div><div style="display:flex;align-items:center"><span style="font-size:12px;color:#94a3b8;margin-right:8px">批准令牌</span><code style="font-size:18px;font-weight:700;color:#1a56db;background:#eff6ff;padding:4px 12px;border-radius:6px;letter-spacing:2px">{plain}</code></div></div>'
        )
    token_batch.append(
        _facade().OpsApprovalToken(
            token_hash=identity_hash,
            kind="digest_identity",
            payload_json=_facade().json.dumps({"scope": "daily_digest"}, ensure_ascii=False),
            authorized_email=auth_email,
            expires_at=expires_at,
        )
    )
    if pending:
        staged_section_html = f"""\n<div style="padding:6px 24px 16px">\n  {_facade()._section_title("待审批改动", icon="&#x2705;", subtitle=f"{len(pending)} 项待批准", accent="#dc2626")}\n  <p style="font-size:13px;color:#64748b;margin:0 0 10px;line-height:1.6">回复本邮件并附上令牌即可批准对应分支的部署。</p>\n  {"".join(cards)}\n  <div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:12px;padding:15px 16px;margin-top:14px;text-align:center">\n    <div style="font-size:12px;color:#64748b;margin-bottom:6px">身份校验码（不触发部署）</div>\n    <code style="display:inline-block;font-size:22px;font-weight:800;color:#1d4ed8;letter-spacing:4px;background:#ffffff;border:1px solid #bfdbfe;border-radius:8px;padding:6px 16px">{plain_identity}</code>\n  </div>\n</div>\n"""
    else:
        staged_section_html = f"""\n<div style="padding:6px 24px 16px">\n  {_facade()._section_title("身份校验", icon="&#x1F6E1;&#xFE0F;", accent="#16a34a")}\n  <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:12px;padding:18px 16px;text-align:center">\n    <div style="font-size:13px;color:#475569;margin-bottom:4px">当前无待部署分支，回信不会触发部署操作</div>\n    <div style="font-size:12px;color:#94a3b8;margin-bottom:8px">身份校验码（可回复本邮件验证身份）</div>\n    <code style="display:inline-block;font-size:22px;font-weight:800;color:#1d4ed8;letter-spacing:4px;background:#ffffff;border:1px solid #bbf7d0;border-radius:8px;padding:6px 16px">{plain_identity}</code>\n  </div>\n</div>\n"""
    return (token_batch, staged_section_html)


def _surface_audit_failed_bundle(
    *, error_code: str, message: str, timed_out: bool = False
) -> _facade().Dict[str, _facade().Any]:
    return {
        "ok": False,
        "error": error_code,
        "timed_out": bool(timed_out),
        "html": f'<div style="padding:0 24px 8px"><div style="background:#fef2f2;border:1px solid #fecaca;border-radius:12px;padding:14px 16px;color:#991b1b;font-size:13px;line-height:1.7"><strong>三端巡检未完成。</strong> {message} 已降级为继续发送日报，稍后可单独补跑巡检。</div></div>',
        "report": {
            "ok": False,
            "error": error_code,
            "timed_out": bool(timed_out),
            "surfaces": [],
        },
        "excerpt_markdown": f"- 三端巡检未完成：{message}",
    }


def _build_surface_audit_bundle() -> _facade().Dict[str, _facade().Any]:
    timeout_raw = (
        _facade().os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_TIMEOUT_SEC") or ""
    ).strip()
    try:
        timeout_sec = int(timeout_raw or "180")
    except RECOVERABLE_ERRORS:
        timeout_sec = 180
    try:
        from modstore_server.daily_digest_surface_audit import (
            build_surface_audit_html_sync,
            surface_audit_excerpt_markdown,
        )
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("daily digest: surface audit import failed")
        return _facade()._surface_audit_failed_bundle(
            error_code="surface_audit_import_failed",
            message="巡检模块加载失败（见服务器日志）",
        )

    def _ok_bundle(html: str, report: _facade().Any) -> _facade().Dict[str, _facade().Any]:
        safe_report = report or {}
        try:
            excerpt = surface_audit_excerpt_markdown(safe_report)
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("daily digest: surface audit excerpt failed")
            excerpt = ""
        return {
            "ok": True,
            "error": "",
            "timed_out": False,
            "html": html,
            "report": safe_report,
            "excerpt_markdown": excerpt,
        }

    if timeout_sec <= 0:
        try:
            html, report = build_surface_audit_html_sync()
            return _ok_bundle(html, report)
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("daily digest: surface audit failed")
            return _facade()._surface_audit_failed_bundle(
                error_code="surface_audit_failed",
                message="巡检执行失败（见服务器日志）",
            )
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FuturesTimeoutError

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="digest-surface-audit")
    future = executor.submit(build_surface_audit_html_sync)
    try:
        html, report = future.result(timeout=timeout_sec)
        return _ok_bundle(html, report)
    except FuturesTimeoutError:
        _facade().logger.error("daily digest: surface audit timed out after %ss", timeout_sec)
        future.cancel()
        return _facade()._surface_audit_failed_bundle(
            error_code="surface_audit_timeout",
            message=f"巡检超时（>{timeout_sec}s）",
            timed_out=True,
        )
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("daily digest: surface audit failed")
        return _facade()._surface_audit_failed_bundle(
            error_code="surface_audit_failed", message="巡检执行失败（见服务器日志）"
        )
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
