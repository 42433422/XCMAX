"""定时采集器：写入 incident-bus（pytest / nginx 日志 / cursor 日志）。"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC
from pathlib import Path

from modstore_server.incident_bus import publish
from modstore_server.integrations.ops_action_handlers import repo_root
from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_LAST_FAIL_SNAPSHOT: str | None = None
_LAST_NGINX_FILE_ID: tuple[int, int] | None = None
_LAST_NGINX_OFFSET: int | None = None
_LAST_CURSOR_SNIP_HASH: str | None = None

_NGINX_ERROR_LEVELS = ("[error]", "[crit]", "[alert]", "[emerg]")
_NGINX_MAX_NEW_BYTES = 256 * 1024


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
    """Nginx error.log 新增严重错误行 → ``on_error``。

    首次启动以及日志轮转/截断后只记录当前位置，避免把历史错误重复派发为新事故。
    """
    global _LAST_NGINX_FILE_ID, _LAST_NGINX_OFFSET
    log_path = os.environ.get("OPS_NGINX_ERROR_LOG", "").strip() or "/var/log/nginx/error.log"
    p = Path(log_path)
    if not p.is_file():
        return False
    try:
        with p.open("rb") as fh:
            stat = os.fstat(fh.fileno())
            file_id = (int(stat.st_dev), int(stat.st_ino))
            size = int(stat.st_size)

            if (
                _LAST_NGINX_FILE_ID is None
                or _LAST_NGINX_OFFSET is None
                or file_id != _LAST_NGINX_FILE_ID
                or size < _LAST_NGINX_OFFSET
            ):
                _LAST_NGINX_FILE_ID = file_id
                _LAST_NGINX_OFFSET = size
                return False

            if size == _LAST_NGINX_OFFSET:
                return False

            start = max(_LAST_NGINX_OFFSET, size - _NGINX_MAX_NEW_BYTES)
            fh.seek(start)
            new_bytes = fh.read(size - start)
    except OSError:
        return False

    _LAST_NGINX_FILE_ID = file_id
    _LAST_NGINX_OFFSET = size
    new_text = new_bytes.decode("utf-8", errors="replace")
    error_lines = [
        line
        for line in new_text.splitlines()
        if any(level in line.lower() for level in _NGINX_ERROR_LEVELS)
    ]
    if not error_lines:
        return False
    snippet = "\n".join(error_lines[-20:])[-2000:]
    return publish(
        "on_error",
        {
            "summary": "nginx error.log 出现新增严重错误",
            "path": str(p),
            "snippet": snippet,
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
                        lines.append(f"{f.name}:{i + 1}:{line[:400]}")
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


def _deployed_head_state_path() -> Path:
    runtime = str(os.environ.get("MODSTORE_RUNTIME_DIR") or "").strip()
    root = Path(runtime).expanduser() if runtime else Path.home() / ".xcmax" / "modstore-daily"
    return root / "deployed-head-sha"


def _release_manifest() -> tuple[Path, dict]:
    configured = str(os.environ.get("MODSTORE_RELEASE_MANIFEST") or "").strip()
    path = (
        Path(configured).expanduser()
        if configured
        else Path(str(os.environ.get("MODSTORE_REPO_ROOT") or repo_root())).expanduser()
        / ".xcmax-release.json"
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return path, {}
    return path, payload if isinstance(payload, dict) else {}


def _previous_release_sha(manifest_path: Path, current_sha: str) -> str:
    """Find the immediately preceding immutable release on first deployment."""

    try:
        current_release = manifest_path.resolve().parent
        releases_root = current_release.parent
        candidates: list[tuple[float, str]] = []
        for path in releases_root.glob("*/.xcmax-release.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                sha = str(payload.get("git_sha") or "").strip().lower()
                if len(sha) != 40 or sha == current_sha:
                    continue
                candidates.append((path.stat().st_mtime, sha))
            except (OSError, json.JSONDecodeError):
                continue
        return max(candidates)[1] if candidates else ""
    except (OSError, ValueError):
        return ""


def _read_previous_deployed_head(manifest_path: Path, current_sha: str) -> str:
    path = _deployed_head_state_path()
    try:
        previous = path.read_text(encoding="utf-8").strip().lower()
    except OSError:
        previous = ""
    if len(previous) == 40 and previous != current_sha:
        return previous
    return _previous_release_sha(manifest_path, current_sha) if not previous else ""


def _remember_deployed_head(sha: str) -> None:
    path = _deployed_head_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(sha + "\n", encoding="utf-8")
    tmp.replace(path)


def collect_git_push_event() -> bool:
    """检测生产不可变发布 SHA 变化 → ``git.push`` 事件。

    生产发布目录不包含 ``.git``，而且调度器会随发布重启。因此以签名发布
    manifest 和持久化上次 SHA 为真相源，避免把每次真实发布当成“首次基线”吞掉。
    """
    global _LAST_GIT_HEAD_SHA
    manifest_path, release = _release_manifest()
    head = str(release.get("git_sha") or "").strip().lower()
    if len(head) != 40 or any(char not in "0123456789abcdef" for char in head):
        return False
    if head == _LAST_GIT_HEAD_SHA:
        return False
    prev = _LAST_GIT_HEAD_SHA or _read_previous_deployed_head(manifest_path, head)
    _LAST_GIT_HEAD_SHA = head
    try:
        _remember_deployed_head(head)
    except OSError:
        logger.exception("incident collector: persist deployed head failed")
    if not prev or prev == head:
        return False
    return publish(
        "git.push",
        {
            "summary": f"生产发布 SHA 由 {prev[:10]} → {head[:10]}",
            "prev_sha": prev,
            "head_sha": head,
            "release_id": str(release.get("release_id") or head),
            "update_context": {
                "version": str(release.get("release_id") or head[:12]),
                "branch": "production/immutable-release",
                "commit_sha": head,
                "git_clean": True,
                "changes": [f"immutable release {prev[:10]} -> {head[:10]}"],
                "rollback": f"git:{prev}",
                "target_tier": "production",
            },
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
        from datetime import datetime, timedelta

        from modstore_server.models import IncidentEvent, get_session_factory

        sf = get_session_factory()
        with sf() as session:
            cutoff = datetime.now(UTC) - timedelta(hours=1)
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
    except RECOVERABLE_ERRORS:
        logger.exception("collect_incident_bus_unknown_alarm failed")
        return False
