"""COVERAGE_RAMP C3.0: 审计日志失败回退 / append_audit_event 错误路径。

覆盖：
- audit_log 输出 JSON 行
- audit_log 调用 append_audit_event 但失败时静默
- append_audit_event 未配置 AUDIT_LOG_PATH 时跳过
- append_audit_event 父目录创建
- append_audit_event 写入异常被吞掉
- append_audit_event 自动补 ts 字段
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AUDIT_LOG_PATH", raising=False)
    yield


def test_audit_log_emits_json(monkeypatch: pytest.MonkeyPatch, caplog):
    import logging

    from app.utils import audit_logger
    from app.utils.audit_logger import audit_log

    # 阻断对 append_audit_event 的真实调用（避免 os env 副作用）
    with patch.object(audit_logger, "append_audit_event") as m:
        with caplog.at_level(logging.INFO, logger="audit"):
            audit_log("login", "u-1", "127.0.0.1", {"success": True})
    # 主 logger 收到 json
    body = json.loads(caplog.records[0].getMessage())
    assert body["event_type"] == "login"
    assert body["user_id"] == "u-1"
    assert body["ip_address"] == "127.0.0.1"
    assert body["details"] == {"success": True}
    assert body["success"] is True
    # 副作用：调用了 append_audit_event
    m.assert_called_once()
    rec = m.call_args[0][0]
    assert rec["action"] == "login"
    assert rec["actor"] == "u-1"


def test_audit_log_failure_path(monkeypatch: pytest.MonkeyPatch, caplog):
    """append_audit_event 抛错时，audit_log 必须静默（不能向上抛）。"""
    import logging

    from app.utils import audit_logger
    from app.utils.audit_logger import audit_log

    def boom(_):
        raise RuntimeError("disk full")

    with patch.object(audit_logger, "append_audit_event", side_effect=boom):
        with caplog.at_level(logging.INFO, logger="audit"):
            audit_log("logout", None, None, {"k": "v"}, success=False)  # 不抛错
    body = json.loads(caplog.records[0].getMessage())
    assert body["success"] is False
    assert body["user_id"] is None


def test_audit_log_user_id_none_serialized():
    """当 user_id 为 None 时，actor 应为 None 而非 'None'。"""
    from app.utils import audit_logger
    from app.utils.audit_logger import audit_log

    with patch.object(audit_logger, "append_audit_event") as m:
        audit_log("x", None, "ip", {})
    rec = m.call_args[0][0]
    assert rec["actor"] is None


def test_audit_log_ip_none_serialized():
    from app.utils import audit_logger
    from app.utils.audit_logger import audit_log

    with patch.object(audit_logger, "append_audit_event") as m:
        audit_log("x", "u", None, {})
    rec = m.call_args[0][0]
    assert rec["client_host"] is None


def test_append_audit_event_skips_when_no_path():
    from app.utils.audit_events import append_audit_event

    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("AUDIT_LOG_PATH", None)
        # 不配置路径 → 直接返回
        append_audit_event({"action": "x"})  # 不抛错


def test_append_audit_event_writes_line(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from app.utils.audit_events import append_audit_event

    from app.utils import audit_events

    p = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit_events, "audit_log_path", lambda: str(p))
    append_audit_event({"action": "login", "actor": "u-1"})
    line = p.read_text(encoding="utf-8").strip()
    rec = json.loads(line)
    assert rec["action"] == "login"
    assert rec["actor"] == "u-1"
    assert "ts" in rec


def test_append_audit_event_keeps_existing_ts(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from app.utils.audit_events import append_audit_event

    from app.utils import audit_events

    p = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit_events, "audit_log_path", lambda: str(p))
    append_audit_event({"action": "x", "ts": "2026-01-01T00:00:00Z"})
    rec = json.loads(p.read_text(encoding="utf-8").strip())
    assert rec["ts"] == "2026-01-01T00:00:00Z"


def test_append_audit_event_creates_parent_dir(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from app.utils.audit_events import append_audit_event

    from app.utils import audit_events

    p = tmp_path / "nested" / "dir" / "a.jsonl"
    monkeypatch.setattr(audit_events, "audit_log_path", lambda: str(p))
    append_audit_event({"action": "x"})
    assert p.is_file()


def test_append_audit_event_open_failure_silent(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from app.utils.audit_events import append_audit_event

    from app.utils import audit_events

    monkeypatch.setattr(audit_events, "audit_log_path", lambda: "/dev/null/forbidden/path")
    # open 必定失败；append_audit_event 必须吞掉
    append_audit_event({"action": "x"})  # 不抛错
