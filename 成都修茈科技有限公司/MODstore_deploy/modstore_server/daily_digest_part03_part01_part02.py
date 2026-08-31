# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.daily_digest")


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
    except RECOVERABLE_ERRORS:
        pass
    nginx_p = (
        _facade().os.environ.get("OPS_NGINX_ERROR_LOG", "").strip() or "/var/log/nginx/error.log"
    )
    return f"""<div style="margin-top:12px;padding:10px;border:1px solid #e2e8f0;border-radius:8px;background:#f8fafc"><p style="margin:0 0 8px;font-size:13px;color:#334155"><strong>计数说明（调试）</strong>：近 24h「运维审计」仅在执行过运维 shell 指令并写入审计表后增加；「事件入库」依赖 APScheduler 定时采集器命中 pytest/nginx/cursor 规则。</p><ul style="margin:0;padding-left:18px;font-size:12px;color:#64748b;line-height:1.5"><li>MODSTORE_DB_PATH：<code>{_facade().html.escape(db_path)}</code></li><li>APScheduler 运行中：{("是" if sch_running else "否")}（未启动则采集任务不跑）</li><li>OPS_NGINX_ERROR_LOG：<code>{_facade().html.escape(nginx_p)}</code>（文件不存在则跳过 nginx 采集）</li></ul></div>"""


def _publish_tls_cert_security_alerts(
    results: _facade().Sequence[_facade().Any],
) -> None:
    """WARNING/CRITICAL 写入 ``security.alert``（按 UTC 日期去重，避免 incident_bus 10 分钟窗重复）。"""
    if not results:
        return
    try:
        from modstore_server.incident_bus import publish as incident_publish
    except RECOVERABLE_ERRORS:
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
        except RECOVERABLE_ERRORS:
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
        badge_bg, badge_fg = ("#fef2f2", "#b91c1c")
        if level == "INFO":
            badge_bg, badge_fg = ("#eff6ff", "#1e40af")
        elif level == "WARNING":
            badge_bg, badge_fg = ("#fffbeb", "#b45309")
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
            [
                _facade().sys.executable,
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
    except RECOVERABLE_ERRORS as e:
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
    event_n: int,
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
            _kv_row(
                "成功率",
                rate,
                extra_style="" if met_fail == 0 else "background:#fef2f2",
            ),
            _kv_row("运维操作记录", f"{ops_n} 条"),
            _kv_row("系统事件总量", f"{event_n} 条"),
            _kv_row(
                "待处理事件",
                f"{inc_n} 项",
                extra_style="" if inc_n == 0 else "background:#fffbeb",
            ),
        ]
    )
    team_table = (
        '<table style="width:100%;border-collapse:collapse;margin:0">' + "".join(rows2) + "</table>"
    )
    cursor_alert = ""
    if cursor_hits > 0:
        cursor_alert = f'<div style="margin-top:10px;padding:10px 14px;background:#fffbeb;border-left:3px solid #f59e0b;border-radius:4px"><span style="font-size:13px;color:#92400e">代码助手异常：近 24h 有 <strong>{cursor_hits}</strong> 行 error，建议排查。</span></div>'
    return f"""\n<div style="padding:14px 24px 8px">\n  {_facade()._section_title("系统状态", icon="&#x1F5A5;&#xFE0F;", accent="#2563eb")}\n  <div style="background:#f8fafc;border-radius:12px;padding:4px 14px 8px;margin-bottom:16px;border:1px solid #e6eaf0">\n    {system_table}\n  </div>\n  {_facade()._section_title("团队活跃度", icon="&#x1F4C8;", accent="#0d9488")}\n  <div style="background:#f8fafc;border-radius:12px;padding:4px 14px 8px;border:1px solid #e6eaf0">\n    {team_table}\n  </div>\n  {cursor_alert}\n</div>\n"""
