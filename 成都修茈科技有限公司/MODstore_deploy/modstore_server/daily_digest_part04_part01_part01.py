# mypy: disable-error-code="arg-type, attr-defined, misc, no-any-return, union-attr, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
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
            num, rest = (m.group(1), _facade().html.escape(m.group(2).strip()))
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
    surface_audit_report: _facade().Dict[str, _facade().Any] | None,
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
    except RECOVERABLE_ERRORS:
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
        except RECOVERABLE_ERRORS:
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
    except RECOVERABLE_ERRORS:
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
            except RECOVERABLE_ERRORS:
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
            f"""<div style="margin:10px 0 0;padding:10px 12px;border:1px solid #dbeafe;border-radius:10px;background:#ffffff"><div style="font-weight:700;color:#0f172a;margin-bottom:4px">{_facade().html.escape(label)}</div><div style="font-size:12px;color:#64748b;margin-bottom:6px">对应员工：{_facade().html.escape(", ".join(owners) or "未配置")} · 页面 {len(rows)} · 正常 {ok_lane} · 异常 {bad_lane} · console {console_lane}</div><div style="font-size:13px;color:#334155;line-height:1.65">{md_html}</div></div>"""
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
            1,
            min(
                int(_facade().os.environ.get("MODSTORE_DAILY_MEETING_MAX_EMPLOYEES", "6")),
                32,
            ),
        )
    except ValueError:
        max_emp = 6
    try:
        timeout_s = max(
            60,
            int(_facade().os.environ.get("MODSTORE_DAILY_MEETING_TIMEOUT_SECONDS", "240")),
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

    topic_question, topic_emp_ids = _facade()._surface_meeting_topic(surface_audit_report)
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
    except RECOVERABLE_ERRORS as exc:
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
    except RECOVERABLE_ERRORS:
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
        _facade().build_meeting_minutes_html_sync,
        surface_audit_report=surface_audit_report,
    )
    try:
        return future.result(timeout=timeout_sec)
    except FuturesTimeoutError:
        _facade().logger.error("daily digest: meeting minutes timed out after %ss", timeout_sec)
        future.cancel()
        return _facade()._daily_meeting_error_card(
            f"生成超时（>{timeout_sec}s）；三端巡检结果已正常写入日报，可稍后单独补跑员工大会。"
        )
    except RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("daily digest: meeting minutes failed")
        return _facade()._daily_meeting_error_card(f"调度异常：{exc}")
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
