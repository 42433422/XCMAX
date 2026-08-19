# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.daily_digest")


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
    section_re = _facade().re.compile("^([一二三四五六七八九十])、(.*)$")
    out: _facade().List[str] = []
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
            (num, rest) = (m.group(1), _facade().html.escape(m.group(2).strip()))
            out.append(
                f'<div style="margin:12px 0 6px"><span style="display:inline-block;min-width:24px;color:#1a56db;font-weight:700">{num}、</span><span style="font-size:14px;font-weight:700;color:#1e293b">{rest}</span></div>'
            )
            continue
        if stripped.startswith(("- ", "* ", "・", "• ")):
            item = stripped[1:].lstrip() if stripped[0] in "-*" else stripped[1:].lstrip()
            if not in_ul:
                out.append(
                    '<ul style="margin:4px 0 6px 4px;padding-left:20px;font-size:13px;color:#334155;line-height:1.6">'
                )
                in_ul = True
            out.append(f'<li style="margin:3px 0">{_facade().html.escape(item)}</li>')
            continue
        _close_ul()
        out.append(
            f'<p style="margin:4px 0;font-size:13px;color:#334155;line-height:1.6">{_facade().html.escape(stripped)}</p>'
        )
    _close_ul()
    if not have_seen_title:
        out.insert(
            0,
            '<div style="font-size:14px;font-weight:700;color:#1e293b;margin-bottom:6px">会议摘要</div>',
        )
    return "".join(out)


def _surface_meeting_topic(
    surface_audit_report: _facade().Dict[str, _facade().Any] | None
) -> _facade().Tuple[str, _facade().List[str]]:
    """根据三端巡检结果构造「员工大会」讨论议题与对应参会员工。

    返回 ``(user_question, employee_ids)``；report 为空 / 无结果时返回 ``("", [])``，
    回退到原来的全员待机汇总模式。
    """
    if not isinstance(surface_audit_report, dict):
        return ("", [])
    results = (
        surface_audit_report.get("results")
        if isinstance(surface_audit_report.get("results"), list)
        else []
    )
    if not results:
        return ("", [])
    try:
        from modstore_server.daily_digest_surface_audit import (
            lane_employee_ids,
            surface_audit_excerpt_markdown,
        )
    except Exception:
        return ("", [])
    lanes_present = []
    for lane in ("P-W", "P-S", "P-App"):
        if any((str(r.get("lane")) == lane for r in results)):
            lanes_present.append(lane)
    emp_ids: _facade().List[str] = []
    for lane in lanes_present:
        for pid in lane_employee_ids(lane):
            if pid not in emp_ids:
                emp_ids.append(pid)
    excerpt = surface_audit_excerpt_markdown(surface_audit_report)
    question = f"今天的三端页面巡检（P-W 网站 xiu-ci.com / P-S 软件 market / P-App adb 模拟器原生屏）结果与 AI 分析如下，请各产线对应员工从自己岗位视角讨论：哪些是真问题、谁来修、下一步动作。\n\n{excerpt}"
    return (question, emp_ids)


def _surface_audit_meeting_minutes_html(
    surface_audit_report: _facade().Dict[str, _facade().Any] | None,
    *,
    employee_ids: _facade().List[str],
) -> str:
    report = surface_audit_report if isinstance(surface_audit_report, dict) else {}
    results = report.get("results") if isinstance(report.get("results"), list) else []
    lane_analysis = (
        report.get("lane_analysis") if isinstance(report.get("lane_analysis"), dict) else {}
    )
    lanes = [("P-W", "网站 P-W"), ("P-S", "软件 P-S"), ("P-App", "移动 P-App")]

    def _row_ok(row: _facade().Dict[str, _facade().Any]) -> bool:
        try:
            status = int(row.get("status") or 0)
        except Exception:
            status = 0
        return status < 400 and (not str(row.get("error") or "").strip())

    total = len(results)
    ok_count = sum((1 for r in results if isinstance(r, dict) and _row_ok(r)))
    bad_rows = [r for r in results if isinstance(r, dict) and (not _row_ok(r))]
    console_count = sum(
        (len(r.get("console_errors") or []) for r in results if isinstance(r, dict))
    )
    owners_seen: _facade().List[str] = []
    for lane, _label in lanes:
        la = lane_analysis.get(lane) if isinstance(lane_analysis.get(lane), dict) else {}
        for owner in la.get("owners") or []:
            if str(owner).strip() and str(owner).strip() not in owners_seen:
                owners_seen.append(str(owner).strip())
    for eid in employee_ids:
        if str(eid).strip() and str(eid).strip() not in owners_seen:
            owners_seen.append(str(eid).strip())
    try:
        attendance_count = _facade().count_on_duty_employees()
    except Exception:
        _facade().logger.exception("daily digest: count on-duty meeting attendance failed")
        attendance_count = len(owners_seen)
    if attendance_count <= 0:
        attendance_count = len(owners_seen)
    owner_count = len(owners_seen)
    meta_html = f'<div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:10px;font-size:12px;color:#64748b"><span>到会 <strong style="color:#1e293b">{attendance_count}</strong> 人</span><span style="color:#cbd5e1">·</span><span>产线参会负责人 <strong style="color:#1e293b">{owner_count}</strong> 人</span><span style="color:#cbd5e1">·</span><span>页面 <strong style="color:#1e293b">{total}</strong></span><span style="color:#cbd5e1">·</span><span>正常 <strong style="color:#0f766e">{ok_count}</strong></span><span style="color:#cbd5e1">·</span><span>异常 <strong style="color:#b91c1c">{len(bad_rows)}</strong></span><span style="color:#cbd5e1">·</span><span>console 告警 <strong style="color:#b45309">{console_count}</strong></span></div>'
    blocks: _facade().List[str] = [
        '<p style="margin:0 0 10px;font-size:13px;color:#0f172a">本次员工大会基于三端页面巡检 manifest、截图与产线分析自动归档；不再在 08:00 邮件链路中实时等待员工 cognition 外部模型调用。</p>'
    ]
    for lane, label in lanes:
        rows = [r for r in results if isinstance(r, dict) and str(r.get("lane")) == lane]
        if not rows:
            continue
        la = lane_analysis.get(lane) if isinstance(lane_analysis.get(lane), dict) else {}
        owners = [str(x) for x in la.get("owners") or [] if str(x).strip()]
        if not owners:
            try:
                from modstore_server.daily_digest_surface_audit import lane_employee_ids

                owners = [str(x) for x in lane_employee_ids(lane) if str(x).strip()]
            except Exception:
                owners = []
        ok_lane = sum((1 for r in rows if _row_ok(r)))
        bad_lane = len(rows) - ok_lane
        console_lane = sum((len(r.get("console_errors") or []) for r in rows))
        md = str(la.get("markdown") or "").strip()
        if not md:
            md = f"现状：巡检 {len(rows)} 页，正常 {ok_lane} 页。\\n异常：{bad_lane} 页异常，console 告警 {console_lane} 条。\\n改进建议：按异常页面责任岗位继续排查。"
        md_html = "<br>".join(
            (_facade().html.escape(line) for line in md.splitlines() if line.strip())
        )
        blocks.append(
            f"""<div style="margin:10px 0 0;padding:10px 12px;border:1px solid #dbeafe;border-radius:10px;background:#ffffff"><div style="font-weight:700;color:#0f172a;margin-bottom:4px">{_facade().html.escape(label)}</div><div style="font-size:12px;color:#64748b;margin-bottom:6px">对应员工：{_facade().html.escape(', '.join(owners) or '未配置')} · 页面 {len(rows)} · 正常 {ok_lane} · 异常 {bad_lane} · console {console_lane}</div><div style="font-size:13px;color:#334155;line-height:1.65">{md_html}</div></div>"""
        )
    return (
        '<div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:10px;padding:14px 16px">'
        + meta_html
        + "".join(blocks)
        + "</div>"
    )


def build_meeting_minutes_html_sync(
    *, surface_audit_report: _facade().Dict[str, _facade().Any] | None = None
) -> str:
    """每日摘要邮件「员工大会摘要」段落 HTML（同步）。

    流程：``build_all_hands_report`` → ``synthesize_meeting_minutes`` → markdown 渲染。
    传入 ``surface_audit_report`` 时，会把三端巡检结果作为大会议题，召集 P-W / P-S / P-App
    对应在岗员工围绕「截图 + 分析」讨论问题与下一步（替代无议题的待机汇总）。

    环境变量：
    - ``MODSTORE_DAILY_MEETING_ENABLED``（默认 ``1``）：关闭则返回空串，邮件不显示该段。
    - ``MODSTORE_DAILY_MEETING_MAX_EMPLOYEES``（默认 ``6``）：单次大会最多多少名员工。
    - ``MODSTORE_DAILY_MEETING_WITH_RESEARCH``（默认 ``0``）：是否开启员工汇报内的联网调研。
    - ``MODSTORE_DAILY_MEETING_TIMEOUT_SECONDS``（默认 ``240``）：整轮大会硬超时。
    - ``MODSTORE_DAILY_MEETING_USER_ID``（默认 ``MODSTORE_DAILY_BRIEF_USER_ID`` 或 ``0``）。
    """
    enabled = (
        (_facade().os.environ.get("MODSTORE_DAILY_MEETING_ENABLED", "1") or "").strip().lower()
    )
    if enabled in ("0", "false", "no", "off"):
        return ""
    try:
        max_emp = max(
            1, min(int(_facade().os.environ.get("MODSTORE_DAILY_MEETING_MAX_EMPLOYEES", "6")), 32)
        )
    except ValueError:
        max_emp = 6
    try:
        timeout_s = max(
            60, int(_facade().os.environ.get("MODSTORE_DAILY_MEETING_TIMEOUT_SECONDS", "240"))
        )
    except ValueError:
        timeout_s = 240
    with_research = (
        _facade().os.environ.get("MODSTORE_DAILY_MEETING_WITH_RESEARCH", "0") or ""
    ).strip().lower() in ("1", "true", "yes", "on")
    raw_uid = (
        _facade().os.environ.get("MODSTORE_DAILY_MEETING_USER_ID")
        or _facade().os.environ.get("MODSTORE_DAILY_BRIEF_USER_ID")
        or "0"
    ).strip()
    user_id = int(raw_uid) if raw_uid.isdigit() else 0

    def _err_card(msg: str) -> str:
        return f'<div style="background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:14px 16px"><p style="margin:0;font-size:13px;color:#92400e">员工大会未生成摘要：{_facade().html.escape(msg)}</p></div>'

    (topic_question, topic_emp_ids) = _facade()._surface_meeting_topic(surface_audit_report)
    use_employee_executor = (
        _facade().os.environ.get("MODSTORE_DAILY_MEETING_USE_EMPLOYEE_EXECUTOR", "0") or ""
    ).strip().lower() in ("1", "true", "yes", "on")
    if surface_audit_report and (not use_employee_executor):
        return _facade()._surface_audit_meeting_minutes_html(
            surface_audit_report, employee_ids=topic_emp_ids
        )
    if topic_emp_ids:
        max_emp = max(max_emp, len(topic_emp_ids))
    try:
        import asyncio as _aio
        from modstore_server.all_hands_report import (
            build_all_hands_report,
            synthesize_meeting_minutes,
        )

        async def _run() -> _facade().Dict[str, _facade().Any]:
            report = await _aio.wait_for(
                build_all_hands_report(
                    employee_ids=topic_emp_ids or None,
                    max_employees=max_emp,
                    with_research=with_research,
                    user_id=user_id,
                    concurrency=2,
                    user_question=topic_question or None,
                    synthesize=False,
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
    except Exception as exc:
        _facade().logger.exception("daily meeting failed")
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
    body_html = _facade()._meeting_minutes_md_to_html(minutes_md)
    bench_label = (
        f'<code style="background:#eff6ff;color:#1e40af;padding:2px 8px;border-radius:4px;font-size:11px">{_facade().html.escape(bench_provider)}/{_facade().html.escape(bench_model)}</code>'
        if bench_provider and bench_model
        else ""
    )
    meta_html = (
        f'<div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:10px;font-size:12px;color:#64748b"><span>到会 <strong style="color:#1e293b">{total}</strong> 人</span><span style="color:#cbd5e1">·</span><span>成功 <strong style="color:#0f766e">{ok_count}</strong></span><span style="color:#cbd5e1">·</span><span>异常 <strong style="color:#b91c1c">{err_count}</strong></span>'
        + (f'<span style="color:#cbd5e1">·</span>{bench_label}' if bench_label else "")
        + "</div>"
    )
    return (
        '<div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:10px;padding:14px 16px">'
        + meta_html
        + body_html
        + "</div>"
    )


def _daily_meeting_error_card(msg: str) -> str:
    return f'<div style="background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:14px 16px"><p style="margin:0;font-size:13px;color:#92400e">员工大会未生成摘要：{_facade().html.escape(msg)}</p></div>'


def _daily_meeting_outer_timeout_sec() -> int:
    raw = (
        _facade().os.environ.get("MODSTORE_DAILY_MEETING_OUTER_TIMEOUT_SECONDS")
        or _facade().os.environ.get("MODSTORE_DAILY_MEETING_TIMEOUT_SECONDS")
        or "300"
    )
    try:
        return max(60, min(int(raw), 900))
    except Exception:
        return 300


def _build_meeting_minutes_html_bounded(
    *, surface_audit_report: _facade().Dict[str, _facade().Any] | None = None
) -> str:
    timeout_sec = _facade()._daily_meeting_outer_timeout_sec()
    if timeout_sec <= 0:
        return _facade().build_meeting_minutes_html_sync(surface_audit_report=surface_audit_report)
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FuturesTimeoutError

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="digest-meeting")
    future = executor.submit(
        _facade().build_meeting_minutes_html_sync, surface_audit_report=surface_audit_report
    )
    try:
        return future.result(timeout=timeout_sec)
    except FuturesTimeoutError:
        _facade().logger.error("daily digest: meeting minutes timed out after %ss", timeout_sec)
        future.cancel()
        return _facade()._daily_meeting_error_card(
            f"生成超时（>{timeout_sec}s）；三端巡检结果已正常写入日报，可稍后单独补跑员工大会。"
        )
    except Exception as exc:
        _facade().logger.exception("daily digest: meeting minutes failed")
        return _facade()._daily_meeting_error_card(f"调度异常：{exc}")
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


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
    (git_branch, git_head) = _facade()._digest_git_branch_and_head(root)
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
        inc_n = (
            session.query(_facade().func.count(_facade().IncidentEvent.id))
            .filter(_facade().IncidentEvent.created_at >= since)
            .scalar()
            or 0
        )
        met_ok = (
            session.query(_facade().func.count(_facade().EmployeeExecutionMetric.id))
            .filter(
                _facade().EmployeeExecutionMetric.created_at >= since,
                _facade().EmployeeExecutionMetric.status == "success",
            )
            .scalar()
            or 0
        )
        met_fail = (
            session.query(_facade().func.count(_facade().EmployeeExecutionMetric.id))
            .filter(
                _facade().EmployeeExecutionMetric.created_at >= since,
                _facade().EmployeeExecutionMetric.status != "success",
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
        cursor_hits=int(cursor_hits),
    )
    briefs_block = ""
    if (employee_briefs_html or "").strip():
        briefs_block = f"""\n<div style="padding:6px 24px 16px">\n  {_facade()._section_title('AI 改进建议', icon='&#x1F4A1;', accent='#7c3aed')}\n  <div style="background:#faf9ff;border:1px solid #e9e2fb;border-radius:12px;padding:14px 16px">\n    {employee_briefs_html}\n  </div>\n</div>\n"""
    _weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    try:
        from zoneinfo import ZoneInfo

        cn_now = now_utc.astimezone(ZoneInfo("Asia/Shanghai"))
        weekday_cn = _weekdays[cn_now.weekday()]
        cn_display = (
            f"{cn_now.strftime('%Y-%m-%d')} · {weekday_cn} · {cn_now.strftime('%H:%M')} CST"
        )
    except Exception:
        cn_display = now_utc.strftime("%Y-%m-%d %H:%M UTC")
    hero_html = _facade()._hero_overview_html(
        met_ok=int(met_ok),
        met_fail=int(met_fail),
        inc_n=int(inc_n),
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
        meeting_block = f"""\n<div style="padding:6px 24px 16px">\n  {_facade()._section_title('员工大会摘要', icon='&#x1F465;', accent='#0891b2')}\n  {meeting_minutes_html}\n</div>\n"""
    surface_block = ""
    if (surface_audit_html or "").strip():
        surface_block = f"""\n<div style="padding:6px 24px 16px">\n  {_facade()._section_title('三端页面截图巡检', icon='&#x1F4F7;', subtitle='P-W 网站 · P-S 软件 · P-App 移动', accent='#0d9488')}\n  {surface_audit_html}\n</div>\n"""
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
    (plain_identity, identity_hash) = _facade()._new_unique_ops_token_plain(seen_hashes)
    cards: _facade().List[str] = []
    for s in pending:
        (plain, th) = _facade()._new_unique_ops_token_plain(seen_hashes)
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
        staged_section_html = f"""\n<div style="padding:6px 24px 16px">\n  {_facade()._section_title('待审批改动', icon='&#x2705;', subtitle=f'{len(pending)} 项待批准', accent='#dc2626')}\n  <p style="font-size:13px;color:#64748b;margin:0 0 10px;line-height:1.6">回复本邮件并附上令牌即可批准对应分支的部署。</p>\n  {''.join(cards)}\n  <div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:12px;padding:15px 16px;margin-top:14px;text-align:center">\n    <div style="font-size:12px;color:#64748b;margin-bottom:6px">身份校验码（不触发部署）</div>\n    <code style="display:inline-block;font-size:22px;font-weight:800;color:#1d4ed8;letter-spacing:4px;background:#ffffff;border:1px solid #bfdbfe;border-radius:8px;padding:6px 16px">{plain_identity}</code>\n  </div>\n</div>\n"""
    else:
        staged_section_html = f"""\n<div style="padding:6px 24px 16px">\n  {_facade()._section_title('身份校验', icon='&#x1F6E1;&#xFE0F;', accent='#16a34a')}\n  <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:12px;padding:18px 16px;text-align:center">\n    <div style="font-size:13px;color:#475569;margin-bottom:4px">当前无待部署分支，回信不会触发部署操作</div>\n    <div style="font-size:12px;color:#94a3b8;margin-bottom:8px">身份校验码（可回复本邮件验证身份）</div>\n    <code style="display:inline-block;font-size:22px;font-weight:800;color:#1d4ed8;letter-spacing:4px;background:#ffffff;border:1px solid #bbf7d0;border-radius:8px;padding:6px 16px">{plain_identity}</code>\n  </div>\n</div>\n"""
    return (token_batch, staged_section_html)


def _surface_audit_failed_bundle(
    *, error_code: str, message: str, timed_out: bool = False
) -> _facade().Dict[str, _facade().Any]:
    return {
        "ok": False,
        "error": error_code,
        "timed_out": bool(timed_out),
        "html": f'<div style="padding:0 24px 8px"><div style="background:#fef2f2;border:1px solid #fecaca;border-radius:12px;padding:14px 16px;color:#991b1b;font-size:13px;line-height:1.7"><strong>三端巡检未完成。</strong> {message} 已降级为继续发送日报，稍后可单独补跑巡检。</div></div>',
        "report": {"ok": False, "error": error_code, "timed_out": bool(timed_out), "surfaces": []},
        "excerpt_markdown": f"- 三端巡检未完成：{message}",
    }


def _build_surface_audit_bundle() -> _facade().Dict[str, _facade().Any]:
    timeout_raw = (
        _facade().os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_TIMEOUT_SEC") or ""
    ).strip()
    try:
        timeout_sec = int(timeout_raw or "180")
    except Exception:
        timeout_sec = 180
    try:
        from modstore_server.daily_digest_surface_audit import (
            build_surface_audit_html_sync,
            surface_audit_excerpt_markdown,
        )
    except Exception:
        _facade().logger.exception("daily digest: surface audit import failed")
        return _facade()._surface_audit_failed_bundle(
            error_code="surface_audit_import_failed", message="巡检模块加载失败（见服务器日志）"
        )

    def _ok_bundle(html: str, report: _facade().Any) -> _facade().Dict[str, _facade().Any]:
        safe_report = report or {}
        try:
            excerpt = surface_audit_excerpt_markdown(safe_report)
        except Exception:
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
            (html, report) = build_surface_audit_html_sync()
            return _ok_bundle(html, report)
        except Exception:
            _facade().logger.exception("daily digest: surface audit failed")
            return _facade()._surface_audit_failed_bundle(
                error_code="surface_audit_failed", message="巡检执行失败（见服务器日志）"
            )
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FuturesTimeoutError

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="digest-surface-audit")
    future = executor.submit(build_surface_audit_html_sync)
    try:
        (html, report) = future.result(timeout=timeout_sec)
        return _ok_bundle(html, report)
    except FuturesTimeoutError:
        _facade().logger.error("daily digest: surface audit timed out after %ss", timeout_sec)
        future.cancel()
        return _facade()._surface_audit_failed_bundle(
            error_code="surface_audit_timeout",
            message=f"巡检超时（>{timeout_sec}s）",
            timed_out=True,
        )
    except Exception:
        _facade().logger.exception("daily digest: surface audit failed")
        return _facade()._surface_audit_failed_bundle(
            error_code="surface_audit_failed", message="巡检执行失败（见服务器日志）"
        )
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
