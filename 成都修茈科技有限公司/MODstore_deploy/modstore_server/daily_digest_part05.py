# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.daily_digest")


def run_daily_digest_email() -> _facade().Dict[str, _facade().Any]:
    """由调度器每日调用。"""
    raw = _facade().os.environ.get("MODSTORE_DAILY_DIGEST_ENABLED", "1").strip().lower()
    if raw in ("0", "false", "no", "off"):
        _facade().logger.info("daily digest disabled by MODSTORE_DAILY_DIGEST_ENABLED")
        return {
            "ok": True,
            "skipped": True,
            "reason": "MODSTORE_DAILY_DIGEST_ENABLED=0",
        }
    from modstore_server.autonomy_guard_delegate import evaluate_risk

    risk_decision = evaluate_risk(
        "daily_digest",
        action_id=f"daily-digest:{_facade().datetime.now(_facade().timezone.utc).date().isoformat()}",
        source="daily_digest.cron",
    )
    if not risk_decision.allowed:
        return {
            "ok": False,
            "skipped": True,
            "reason": (
                "autonomy_guard_pending_approval"
                if risk_decision.requires_confirmation
                else "autonomy_guard_blocked"
            ),
            "risk_decision": risk_decision.to_dict(),
        }
    from modstore_server.automation_primary import skip_daily_automation_result

    delegated = skip_daily_automation_result(job="daily_digest_email")
    if delegated:
        return delegated
    stop_ephemeral_after = False
    try:
        from modstore_server.surface_audit_deps import surface_audit_stop_after_enabled

        stop_ephemeral_after = surface_audit_stop_after_enabled()
    except RECOVERABLE_ERRORS:
        stop_ephemeral_after = False
    recipients = _facade().parse_daily_digest_recipient_emails(
        _facade()
        .os.environ.get("MODSTORE_DAILY_DIGEST_EMAIL", _facade().DEFAULT_DIGEST_EMAIL)
        .strip()
    )
    if not recipients:
        _facade().logger.warning("daily digest: no valid recipient emails")
        return {"ok": False, "delivered": False, "reason": "no_valid_recipient_emails"}
    try:
        try:
            from modstore_server.inbox_poller import poll_fail_streak as _poll_fail_streak

            _streak = _poll_fail_streak()
        except RECOVERABLE_ERRORS:
            _streak = 0
        imap_alert_html = ""
        if _streak >= 3:
            imap_alert_html = '<p style="color:#b91c1c;font-size:14px"><strong>IMAP 收件轮询已连续失败 ≥3 次，请检查 MODSTORE_IMAP_HOST / MODSTORE_IMAP_USER / 密码（或 SMTP 同源凭证）。</strong></p>'
        auth_email = (
            _facade()
            .os.environ.get("MODSTORE_APPROVAL_AUTHORIZED_FROM", _facade().DEFAULT_DIGEST_EMAIL)
            .strip()
        )
        ttl_hours = int(_facade().os.environ.get("MODSTORE_APPROVAL_TOKEN_TTL_HOURS", "36"))
        expires_at = _facade().datetime.now(_facade().timezone.utc) + _facade().timedelta(
            hours=ttl_hours
        )
        sf = _facade().get_session_factory()
        _prune_zombie_pending_staged_changes()
        with sf() as session:
            pending = (
                session.query(_facade().OpsStagedChange)
                .filter(_facade().OpsStagedChange.status == "pending")
                .order_by(_facade().OpsStagedChange.id.asc())
                .all()
            )
        with sf() as session:
            existing_token_hashes = {
                str(row[0])
                for row in session.query(_facade().OpsApprovalToken.token_hash).all()
                if row[0]
            }
            token_batch, staged_section_html = _facade().build_digest_approval_bundle(
                pending=pending,
                auth_email=auth_email,
                expires_at=expires_at,
                existing_token_hashes=existing_token_hashes,
            )
        employee_briefs_html = ""
        if _facade().os.environ.get("MODSTORE_DAILY_BRIEF_ENABLED", "0").strip().lower() in (
            "1",
            "true",
            "yes",
        ):
            try:
                from modstore_server.daily_employee_briefs import (
                    build_daily_brief_html_sync,
                )

                employee_briefs_html = build_daily_brief_html_sync()
            except RECOVERABLE_ERRORS:
                _facade().logger.exception("daily digest: employee briefs failed")
                employee_briefs_html = '<div style="margin-top:16px"><p style="color:#b91c1c;font-size:14px">各岗位方案段落生成失败（见服务器日志）。</p></div>'
        try:
            from modstore_server.tls_cert_inspection import scan_tls_certificates

            cert_results = scan_tls_certificates()
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("daily digest: tls cert scan failed")
            cert_results = []
        _facade()._publish_tls_cert_security_alerts(cert_results)
        tls_cert_section_html = _facade()._tls_cert_digest_html(cert_results)
        surface_audit_bundle = _facade()._build_surface_audit_bundle()
        surface_audit_html = str(surface_audit_bundle.get("html") or "")
        surface_audit_report = surface_audit_bundle.get("report") or {}
        surface_audit_excerpt = str(surface_audit_bundle.get("excerpt_markdown") or "")
        surface_ppt_path = ""
        surface_ppt_meta: _facade().Dict[str, _facade().Any] = {}
        if surface_audit_bundle.get("ok"):
            try:
                from modstore_server.daily_digest_surface_ppt import (
                    build_surface_audit_pptx,
                )

                surface_ppt_meta = build_surface_audit_pptx(surface_audit_report)
                if surface_ppt_meta.get("ok") and (not surface_ppt_meta.get("skipped")):
                    surface_ppt_path = str(surface_ppt_meta.get("path") or "")
                    _facade().logger.info(
                        "daily digest: surface ppt built slides=%s path=%s",
                        surface_ppt_meta.get("slides"),
                        surface_ppt_path,
                    )
                elif surface_ppt_meta.get("error"):
                    _facade().logger.warning(
                        "daily digest: surface ppt error=%s",
                        surface_ppt_meta.get("error"),
                    )
            except RECOVERABLE_ERRORS:
                _facade().logger.exception("daily digest: surface ppt failed")
        else:
            _facade().logger.warning(
                "daily digest: surface ppt skipped because surface audit failed err=%s",
                surface_audit_bundle.get("error"),
            )
        if surface_ppt_path:
            slides = int(surface_ppt_meta.get("slides") or 0)
            surface_audit_html += f'<div style="padding:0 24px 4px"><div style="background:#eef2ff;border:1px solid #c7d2fe;border-radius:8px;padding:10px 14px;font-size:12px;color:#4338ca">&#x1F4CE; 本次巡检截图已拼成 PowerPoint（{slides} 页，含每页 AI 分析），见邮件附件。</div></div>'
        meeting_minutes_html = ""
        if surface_audit_bundle.get("ok"):
            meeting_minutes_html = _facade()._build_meeting_minutes_html_bounded(
                surface_audit_report=surface_audit_report
            )
        else:
            meeting_minutes_html = '<div style="background:#fff7ed;border:1px solid #fed7aa;border-radius:10px;padding:14px 16px"><p style="margin:0;font-size:13px;color:#9a3412">三端巡检未完成，员工大会摘要已跳过；日报先按降级模式发出。</p></div>'
        body = _facade().build_digest_html(
            staged_section_html=staged_section_html,
            imap_alert_html=imap_alert_html,
            employee_briefs_html=employee_briefs_html,
            tls_cert_section_html=tls_cert_section_html,
            meeting_minutes_html=meeting_minutes_html,
            surface_audit_html=surface_audit_html,
        )
        day = _facade().digest_calendar_day()
        subject = f"MODstore 每日摘要 · {day}"
        any_delivered = False
        delivery_rows: _facade().List[_facade().Dict[str, _facade().Any]] = []
        attachments = [surface_ppt_path] if surface_ppt_path else []
        for to_email in recipients:
            if attachments:
                result = _facade().send_html_email_with_attachments(
                    to_email, subject, body, attachments
                )
            else:
                result = _facade().send_simple_html_email(to_email, subject, body)
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
            _facade().logger.info("daily digest sent to=%s result=%s", to_email, result)
        if not any_delivered:
            _facade().logger.error(
                "daily digest: no email delivered delivery_rows=%s", delivery_rows
            )
        record_id = _facade()._persist_daily_digest_record(
            subject=subject,
            day=day,
            body_html=body,
            meeting_minutes_html=meeting_minutes_html,
            recipients=recipients,
            delivery_rows=delivery_rows,
            delivered=any_delivered,
        )
        if record_id and meeting_minutes_html:
            try:
                from modstore_server.employee_collab_reporter import (
                    report_meeting_minutes,
                )

                report_meeting_minutes(
                    record_id=int(record_id), day=day, minutes_html=meeting_minutes_html
                )
            except RECOVERABLE_ERRORS:
                _facade().logger.exception(
                    "collab report (meeting minutes) failed record_id=%s", record_id
                )
        if record_id:
            try:
                from modstore_server.release_train import bump_release_train

                bump_release_train(record_id=int(record_id), digest_day=day)
            except RECOVERABLE_ERRORS:
                _facade().logger.exception(
                    "daily digest: release_train bump failed record_id=%s", record_id
                )
        if record_id:
            _facade()._run_scheduled_digest_vibe_prep(
                record_id=record_id,
                day=day,
                subject=subject,
                body_html=body,
                body_text=_facade()._html_to_text_excerpt(body),
                meeting_minutes_html=meeting_minutes_html,
                surface_audit_excerpt=surface_audit_excerpt,
            )
        _facade()._notify_daily_digest_in_app(subject, any_delivered)
        if record_id:
            try:
                from modstore_server.time_rail_runtime import record_node_run

                digest_ok = bool(any_delivered)
                meta = {"record_id": int(record_id), "day": day}
                for nid in ("ASM", "P", "M", "PPTX", "SW", "SS", "SA", "V"):
                    record_node_run(nid, ok=digest_ok, source="daily_digest", meta=meta)
            except RECOVERABLE_ERRORS:
                _facade().logger.exception("daily digest: time_rail runtime record failed")
        identity_tokens = [
            t for t in token_batch or [] if getattr(t, "kind", None) == "digest_identity"
        ]
        deploy_tokens = [
            t for t in token_batch or [] if getattr(t, "kind", None) != "digest_identity"
        ]
        if identity_tokens:
            with sf() as session:
                for t in identity_tokens:
                    session.add(t)
                session.commit()
            _facade().logger.info(
                "daily digest: persisted %d digest_identity token(s)",
                len(identity_tokens),
            )
        if deploy_tokens and any_delivered:
            with sf() as session:
                for t in deploy_tokens:
                    session.add(t)
                session.commit()
            _facade().logger.info(
                "daily digest: persisted %d deploy approval token(s)",
                len(deploy_tokens),
            )
        return {
            "ok": bool(any_delivered),
            "delivered": bool(any_delivered),
            "record_id": int(record_id) if record_id else None,
            "subject": subject,
            "day": day,
            "recipients": recipients,
            "delivery_rows": delivery_rows,
            "reason": "" if any_delivered else "no_email_delivered",
        }
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("daily digest failed")
        try:
            from modstore_server.time_rail_runtime import record_node_run

            record_node_run("ASM", ok=False, source="daily_digest", meta={"error": "job_failed"})
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("daily digest: time_rail failure record failed")
        return {"ok": False, "delivered": False, "reason": "job_failed"}
    finally:
        if stop_ephemeral_after:
            try:
                from modstore_server.surface_audit_deps import (
                    stop_surface_audit_ephemeral,
                )

                stopped = stop_surface_audit_ephemeral()
                _facade().logger.info(
                    "daily digest: surface audit ephemeral stopped %s",
                    stopped.get("stopped"),
                )
            except RECOVERABLE_ERRORS:
                _facade().logger.exception("daily digest: stop surface audit ephemeral failed")


def _prune_zombie_pending_staged_changes() -> int:
    """分支已被 pr-hygiene 等机制删除的 pending 记录自动关闭，避免每日摘要反复出现无法部署的僵尸审批项。"""
    closed = 0
    try:
        import subprocess

        from modstore_server.integrations.ops_action_handlers import repo_root

        root = str(repo_root())
        sf = _facade().get_session_factory()
        with sf() as session:
            rows = (
                session.query(_facade().OpsStagedChange)
                .filter(_facade().OpsStagedChange.status == "pending")
                .all()
            )
            for row in rows:
                branch = str(row.branch or "")
                if not branch:
                    continue
                try:
                    proc = subprocess.run(
                        ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
                        cwd=root,
                        capture_output=True,
                        text=True,
                        timeout=15,
                        shell=False,
                    )
                except RECOVERABLE_ERRORS:
                    continue
                if proc.returncode == 0:
                    continue
                row.status = "rejected"
                closed += 1
            if closed:
                session.commit()
        if closed:
            _facade().logger.info(
                "daily digest: auto-closed %d pending staged change(s) whose branch no longer exists",
                closed,
            )
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("daily digest: prune zombie pending staged changes failed")
    return closed


def cron_trigger_for_digest():
    """默认每天 08:00（北京时间）。可用 ``MODSTORE_DAILY_DIGEST_HOUR`` / ``MINUTE`` 覆盖。"""
    try:
        from zoneinfo import ZoneInfo

        tz_name = _facade().os.environ.get("MODSTORE_DAILY_DIGEST_TZ", "Asia/Shanghai").strip()
        tz = ZoneInfo(tz_name)
    except RECOVERABLE_ERRORS:
        tz = None
    hour = int(_facade().os.environ.get("MODSTORE_DAILY_DIGEST_HOUR", "8"))
    minute = int(_facade().os.environ.get("MODSTORE_DAILY_DIGEST_MINUTE", "0"))
    from apscheduler.triggers.cron import CronTrigger

    if tz is not None:
        return CronTrigger(hour=hour, minute=minute, timezone=tz)
    return CronTrigger(hour=hour, minute=minute)
