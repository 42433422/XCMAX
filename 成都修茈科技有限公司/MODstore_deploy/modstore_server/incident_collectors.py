"""定时采集器：写入 incident-bus（pytest / nginx 日志 / cursor 日志）。"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from modstore_server.incident_bus import publish
from modstore_server.integrations.ops_action_handlers import repo_root

logger = logging.getLogger(__name__)

_LAST_FAIL_SNAPSHOT: str | None = None
_LAST_NGINX_TAIL_HASH: str | None = None
_LAST_CURSOR_SNIP_HASH: str | None = None


def collect_pytest_failures() -> bool:
    """``lastfailed`` 非空且内容变化 → ``on_quality_fail``。"""
    global _LAST_FAIL_SNAPSHOT
    path = repo_root() / "MODstore_deploy" / ".pytest_cache" / "v" / "cache" / "lastfailed"
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return False
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if content == _LAST_FAIL_SNAPSHOT:
        return False
    _LAST_FAIL_SNAPSHOT = content
    return publish(
        "on_quality_fail",
        {
            "summary": "pytest lastfailed 非空",
            "path": str(path),
            "snippet": content[:2000],
        },
        source="pytest",
    )


def collect_nginx_error_tail() -> bool:
    """Nginx error.log 尾部变化且含 error → ``on_error``。"""
    global _LAST_NGINX_TAIL_HASH
    log_path = os.environ.get("OPS_NGINX_ERROR_LOG", "").strip() or "/var/log/nginx/error.log"
    p = Path(log_path)
    if not p.is_file():
        return False
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
        tail = "".join(text.splitlines(True)[-120:])
    except OSError:
        return False
    h = str(hash(tail))
    if h == _LAST_NGINX_TAIL_HASH:
        return False
    if "error" not in tail.lower():
        _LAST_NGINX_TAIL_HASH = h
        return False
    _LAST_NGINX_TAIL_HASH = h
    return publish(
        "on_error",
        {
            "summary": "nginx error.log 尾部含 error",
            "path": str(p),
            "snippet": tail[:2000],
        },
        source="nginx_error_log",
    )


def collect_cursor_log_spike() -> bool:
    """仓库根 .cursor_*_log.txt 错误行摘要变化 → ``on_error``。"""
    global _LAST_CURSOR_SNIP_HASH
    root = repo_root()
    lines: list[str] = []
    try:
        for f in sorted(root.glob(".cursor_*_log.txt")):
            try:
                for i, line in enumerate(
                    f.read_text(encoding="utf-8", errors="replace").splitlines()
                ):
                    low = line.lower()
                    if any(x in low for x in ("error", "fail", "exception")):
                        lines.append(f"{f.name}:{i+1}:{line[:400]}")
            except OSError:
                continue
    except OSError:
        return False
    snip = "\n".join(lines[-80:])
    h = str(hash(snip))
    if not snip or h == _LAST_CURSOR_SNIP_HASH:
        return False
    _LAST_CURSOR_SNIP_HASH = h
    return publish(
        "on_error",
        {"summary": "cursor 日志出现 error/fail/exception 行", "snippet": snip[:2000]},
        source="cursor_logs",
    )


_LAST_GIT_HEAD_SHA: str | None = None
_LAST_CI_FAIL_HASH: str | None = None


def collect_git_push_event() -> bool:
    """检测仓库 HEAD 变化 → ``git.push`` 事件（本地 post-push 替代）。"""
    global _LAST_GIT_HEAD_SHA
    try:
        import subprocess

        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root()),
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        )
    except Exception:
        return False
    if proc.returncode != 0:
        return False
    head = (proc.stdout or "").strip()
    if not head or head == _LAST_GIT_HEAD_SHA:
        return False
    prev = _LAST_GIT_HEAD_SHA
    _LAST_GIT_HEAD_SHA = head
    if prev is None:
        # 首次启动只记录基准，不派发，避免每次重启刷一条事件
        return False
    return publish(
        "git.push",
        {
            "summary": f"本地 HEAD 由 {prev[:10]} → {head[:10]}",
            "prev_sha": prev,
            "head_sha": head,
        },
        source="git_local_head",
    )


def collect_ci_failure_log() -> bool:
    """检测 ``.cursor/ci-failures.txt`` 等 CI 失败摘要 → ``ci.failed``。

    路径可由 ``MODSTORE_CI_FAIL_FILE`` 覆盖；不存在即跳过。
    """
    global _LAST_CI_FAIL_HASH
    rel = os.environ.get("MODSTORE_CI_FAIL_FILE", ".cursor/ci-failures.txt").strip()
    p = repo_root() / rel
    if not p.is_file():
        return False
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if not text.strip():
        return False
    h = str(hash(text))
    if h == _LAST_CI_FAIL_HASH:
        return False
    _LAST_CI_FAIL_HASH = h
    return publish(
        "ci.failed",
        {
            "summary": f"CI 失败摘要文件 {rel} 更新",
            "path": str(p),
            "snippet": text[:2000],
        },
        source="ci_log",
    )


def collect_incident_bus_unknown_alarm() -> bool:
    """``incident.unknown`` 在最近一小时内出现多次 → 派发 ``security.alert`` 提示运维登记。"""
    try:
        from datetime import datetime, timedelta, timezone

        from modstore_server.models import IncidentEvent, get_session_factory

        sf = get_session_factory()
        with sf() as session:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
            n = (
                session.query(IncidentEvent)
                .filter(
                    IncidentEvent.event_type == "incident.unknown",
                    IncidentEvent.created_at >= cutoff,
                )
                .count()
            )
        if n >= 3:
            return publish(
                "security.alert",
                {
                    "summary": f"近 1 小时内有 {n} 条未注册事件类型，请检查 incident_collectors / EVENT_TYPES 是否需要登记",
                    "count": int(n),
                },
                source="incident_bus_self_check",
            )
        return False
    except Exception:
        logger.exception("collect_incident_bus_unknown_alarm failed")
        return False
