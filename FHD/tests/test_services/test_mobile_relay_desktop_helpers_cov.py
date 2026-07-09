"""mobile_relay_desktop_client 纯函数分支补测。"""

from __future__ import annotations

import time
from unittest.mock import patch

from app.services import mobile_relay_desktop_client as relay


def test_api_url_joins_base():
    assert relay._api_url("/api/x", "https://example.test/fhd-api").endswith("/api/x")
    assert relay._api_url("api/x", "https://example.test/fhd-api/").endswith("/api/x")


def test_current_lan_advertise_defaults(monkeypatch):
    monkeypatch.delenv("XCAGI_API_PORT", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    with patch.object(relay, "_guess_lan_ipv4", return_value="192.168.9.9"):
        host, port = relay._current_lan_advertise(fallback_host="127.0.0.1", fallback_port=0)
    assert host == "192.168.9.9"
    assert port == 17500


def test_current_lan_advertise_keeps_valid():
    host, port = relay._current_lan_advertise(fallback_host="10.1.2.3", fallback_port=42422)
    assert host == "10.1.2.3"
    assert port == 42422


def test_guess_lan_ipv4_oserror():
    with patch.object(relay.socket, "socket", side_effect=OSError("x")):
        assert relay._guess_lan_ipv4() == "127.0.0.1"


def test_body_indicators():
    # unfinished 复用 failure markers（实现如此）
    assert relay._body_indicates_unfinished("") is False
    assert relay._body_indicates_failed("执行失败：timeout") is True
    assert relay._body_indicates_failed("成功") is False
    assert relay._body_indicates_failed("merge conflict detected") is True


def test_message_requires_execution_evidence():
    assert relay._message_requires_execution_evidence("请修复登录") is True
    assert relay._message_requires_execution_evidence("请合并分支") is True
    assert relay._message_requires_execution_evidence("你好") is False


def test_body_has_execution_evidence():
    assert relay._body_has_execution_evidence("") is False
    assert relay._body_has_execution_evidence("测试通过\npytest 12 passed") is True
    assert relay._body_has_execution_evidence("已修改 app/foo.py") is True
    assert relay._body_has_execution_evidence("思考中") is False


def test_terminal_error_summary_and_classify():
    assert "boom" in relay._terminal_error_summary("执行失败：boom", "fallback")
    assert relay._terminal_error_summary("", "fallback") == "fallback"
    ok, summary, kind = relay._classify_terminal_result(
        {"exit_code": 0, "stdout": "ok", "stderr": ""},
        message="echo hi",
    )
    assert isinstance(ok, bool)
    assert isinstance(summary, str)
    assert isinstance(kind, str)


def test_extract_branch_helpers():
    assert relay._extract_target_branch("TARGET_feature/demo-1") == "feature/demo-1"
    assert relay._extract_merge_source("merge feature/demo-1") == "feature/demo-1"
    assert relay._extract_merge_target("合并到 main") == "main"
    assert relay._trim_branch_token("feature/demo-1!!!") == "feature/demo-1"
    assert relay._text_mentions_branch_op("请合并分支", "请合并分支") is True
    assert relay._text_mentions_branch_op("普通闲聊", "普通闲聊") is False
    assert (
        relay._extract_branch_after("prefix feature/x suffix", "prefix ", " suffix") == "feature/x"
    )


def test_public_payload_from_config_empty():
    assert relay._public_payload_from_config({}) is None
    assert relay._public_payload_from_config({"relay_id": "r1"}) is None
    future = int(time.time()) + 3600
    payload = relay._public_payload_from_config(
        {
            "relay_id": "r1",
            "pairing_code": "123456",
            "relay_base_url": "https://relay.example/",
            "exp": future,
            "paired": True,
        }
    )
    assert payload is not None
    assert payload["relay_id"] == "r1"
    assert payload["pairing_code"] == "123456"


def test_public_payload_expired():
    past = int(time.time()) - 10
    assert (
        relay._public_payload_from_config({"relay_id": "r1", "pairing_code": "123456", "exp": past})
        is None
    )


def test_cached_desktop_relay_payload_paired_fallback(monkeypatch):
    monkeypatch.setattr(
        relay,
        "_read_config",
        lambda: {"relay_id": "r9", "paired": True, "relay_base_url": "https://r/"},
    )
    monkeypatch.setattr(relay, "_public_payload_from_config", lambda _c: None)
    out = relay.cached_desktop_relay_payload()
    assert out is not None
    assert out["relay_id"] == "r9"
    assert out["paired"] is True
