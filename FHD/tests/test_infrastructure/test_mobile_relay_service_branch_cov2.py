"""测试 app.services.mobile_relay_service 的辅助函数分支覆盖。

覆盖目标：
- _utc_now / _utc_after（时间格式化 / 最小 60s 钳制）
- _epoch_from_iso（正常 / 异常 / Z 后缀）
- _json_dumps（dict / list / 其他类型）
- _json_loads（空 / 异常 / 非 dict）
- _token_hash（哈希一致性）
- _row_dict（None / 含 _json 字段 / 不含 _json 字段）
- _public_base_url（空 / 无协议 / 已有协议 / 末尾斜杠）
- _public_desktop（多种 capabilities / 状态 / 端口）
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _load_mobile_relay_service_module():
    path = Path(__file__).resolve().parents[2] / "app" / "services" / "mobile_relay_service.py"
    spec = importlib.util.spec_from_file_location("mobile_relay_service_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mobile_relay_service = _load_mobile_relay_service_module()

_utc_now = mobile_relay_service._utc_now
_utc_after = mobile_relay_service._utc_after
_epoch_from_iso = mobile_relay_service._epoch_from_iso
_json_dumps = mobile_relay_service._json_dumps
_json_loads = mobile_relay_service._json_loads
_token_hash = mobile_relay_service._token_hash
_row_dict = mobile_relay_service._row_dict
_public_base_url = mobile_relay_service._public_base_url
MobileRelayService = mobile_relay_service.MobileRelayService


class TestUtcNow:
    """_utc_now 分支覆盖。"""

    def test_returns_iso_format_without_microseconds(self) -> None:
        result = _utc_now()
        assert "T" in result
        assert "." not in result
        assert "+" in result or "Z" in result

    def test_returns_recent_timestamp(self) -> None:
        before = datetime.now(UTC).replace(microsecond=0)
        result = _utc_now()
        after = datetime.now(UTC).replace(microsecond=1)
        parsed = datetime.fromisoformat(result)
        # 允许 1 秒的误差（microsecond 已被 strip）
        assert (parsed - before).total_seconds() >= -1
        assert (after - parsed).total_seconds() >= -1


class TestUtcAfter:
    """_utc_after 分支覆盖。"""

    def test_returns_future_timestamp(self) -> None:
        result = _utc_after(120)
        parsed = datetime.fromisoformat(result)
        now = datetime.now(UTC)
        assert parsed > now
        assert (parsed - now) >= timedelta(seconds=119)

    def test_clamps_to_minimum_60_seconds(self) -> None:
        result = _utc_after(10)
        parsed = datetime.fromisoformat(result)
        now = datetime.now(UTC)
        assert (parsed - now) >= timedelta(seconds=59)

    def test_handles_negative_seconds(self) -> None:
        result = _utc_after(-100)
        parsed = datetime.fromisoformat(result)
        now = datetime.now(UTC)
        assert (parsed - now) >= timedelta(seconds=59)

    def test_handles_zero_seconds(self) -> None:
        result = _utc_after(0)
        parsed = datetime.fromisoformat(result)
        now = datetime.now(UTC)
        assert (parsed - now) >= timedelta(seconds=59)


class TestEpochFromIso:
    """_epoch_from_iso 分支覆盖。"""

    def test_parses_valid_iso_with_z(self) -> None:
        result = _epoch_from_iso("2026-01-01T00:00:00Z")
        assert isinstance(result, int)
        assert result > 0

    def test_parses_valid_iso_with_offset(self) -> None:
        result = _epoch_from_iso("2026-01-01T00:00:00+00:00")
        assert isinstance(result, int)
        assert result > 0

    def test_returns_current_time_on_invalid_string(self) -> None:
        before = int(time.time())
        result = _epoch_from_iso("not a date")
        after = int(time.time())
        assert before <= result <= after

    def test_returns_current_time_on_invalid_format(self) -> None:
        # datetime.fromisoformat 对无效格式抛 ValueError
        before = int(time.time())
        result = _epoch_from_iso("2026-13-45T99:99:99")
        after = int(time.time())
        assert before <= result <= after

    def test_returns_current_time_on_empty(self) -> None:
        before = int(time.time())
        result = _epoch_from_iso("")
        after = int(time.time())
        assert before <= result <= after


class TestJsonDumps:
    """_json_dumps 分支覆盖。"""

    def test_dumps_dict(self) -> None:
        result = _json_dumps({"a": 1})
        assert json.loads(result) == {"a": 1}

    def test_dumps_list(self) -> None:
        result = _json_dumps([1, 2, 3])
        assert json.loads(result) == [1, 2, 3]

    def test_dumps_non_dict_non_list_as_empty(self) -> None:
        result = _json_dumps("string")
        assert json.loads(result) == {}

    def test_dumps_none_as_empty(self) -> None:
        result = _json_dumps(None)
        assert json.loads(result) == {}

    def test_dumps_int_as_empty(self) -> None:
        result = _json_dumps(42)
        assert json.loads(result) == {}

    def test_uses_ensure_ascii_false(self) -> None:
        result = _json_dumps({"name": "中文"})
        assert "中文" in result


class TestJsonLoads:
    """_json_loads 分支覆盖。"""

    def test_loads_valid_dict(self) -> None:
        assert _json_loads('{"a": 1}') == {"a": 1}

    def test_returns_empty_for_none(self) -> None:
        assert _json_loads(None) == {}

    def test_returns_empty_for_empty_string(self) -> None:
        assert _json_loads("") == {}

    def test_returns_empty_for_invalid_json(self) -> None:
        assert _json_loads("not json") == {}

    def test_returns_empty_for_non_dict(self) -> None:
        assert _json_loads("[1, 2, 3]") == {}

    def test_returns_empty_for_int(self) -> None:
        assert _json_loads("42") == {}


class TestTokenHash:
    """_token_hash 分支覆盖。"""

    def test_returns_sha256_hex(self) -> None:
        result = _token_hash("mytoken")
        expected = hashlib.sha256(b"mytoken").hexdigest()
        assert result == expected
        assert len(result) == 64

    def test_is_deterministic(self) -> None:
        assert _token_hash("abc") == _token_hash("abc")

    def test_different_tokens_different_hashes(self) -> None:
        assert _token_hash("abc") != _token_hash("def")

    def test_handles_unicode(self) -> None:
        result = _token_hash("中文token")
        assert len(result) == 64


class TestRowDict:
    """_row_dict 分支覆盖。"""

    def test_returns_empty_for_none(self) -> None:
        assert _row_dict(None) == {}

    def test_converts_row_to_dict(self) -> None:
        # dict(dict) 返回副本，所以可以直接传 dict
        result = _row_dict({"id": 1, "name": "test"})  # type: ignore[arg-type]
        assert result == {"id": 1, "name": "test"}

    def test_unpacks_capabilities_json(self) -> None:
        result = _row_dict({"capabilities_json": '{"x": 1}'})  # type: ignore[arg-type]
        assert "capabilities" in result
        assert "capabilities_json" not in result
        assert result["capabilities"] == {"x": 1}

    def test_unpacks_payload_json(self) -> None:
        result = _row_dict({"payload_json": '{"y": 2}'})  # type: ignore[arg-type]
        assert "payload" in result
        assert result["payload"] == {"y": 2}

    def test_unpacks_result_json(self) -> None:
        result = _row_dict({"result_json": '{"z": 3}'})  # type: ignore[arg-type]
        assert "result" in result
        assert result["result"] == {"z": 3}

    def test_keeps_non_json_fields(self) -> None:
        result = _row_dict({"id": 1, "capabilities_json": '{"x": 1}'})  # type: ignore[arg-type]
        assert result["id"] == 1
        assert result["capabilities"] == {"x": 1}

    def test_handles_invalid_json_in_field(self) -> None:
        result = _row_dict({"capabilities_json": "invalid"})  # type: ignore[arg-type]
        assert result["capabilities"] == {}

    def test_does_not_touch_other_keys(self) -> None:
        result = _row_dict({"id": 5, "name": "x", "status": "queued"})  # type: ignore[arg-type]
        assert result == {"id": 5, "name": "x", "status": "queued"}


class TestPublicBaseUrl:
    """_public_base_url 分支覆盖。"""

    def test_returns_default_when_empty(self) -> None:
        result = _public_base_url("")
        assert result == "https://xiu-ci.com/fhd-api/"

    def test_returns_default_when_none(self) -> None:
        result = _public_base_url(None)  # type: ignore[arg-type]
        assert result == "https://xiu-ci.com/fhd-api/"

    def test_returns_default_when_whitespace(self) -> None:
        result = _public_base_url("   ")
        assert result == "https://xiu-ci.com/fhd-api/"

    def test_adds_https_prefix_when_missing(self) -> None:
        result = _public_base_url("example.com")
        assert result == "https://example.com/"

    def test_keeps_http_prefix(self) -> None:
        result = _public_base_url("http://example.com")
        assert result == "http://example.com/"

    def test_keeps_https_prefix(self) -> None:
        result = _public_base_url("https://example.com")
        assert result == "https://example.com/"

    def test_strips_trailing_slash(self) -> None:
        result = _public_base_url("https://example.com/")
        assert result == "https://example.com/"

    def test_strips_multiple_trailing_slashes(self) -> None:
        result = _public_base_url("https://example.com///")
        assert result == "https://example.com/"

    def test_adds_trailing_slash_when_missing(self) -> None:
        result = _public_base_url("https://example.com/path")
        assert result == "https://example.com/path/"


class TestPublicDesktop:
    """_public_desktop 分支覆盖。"""

    def test_returns_minimal_for_empty_data(self) -> None:
        result = MobileRelayService._public_desktop(MagicMock(), {})
        assert result["relay_id"] is None
        assert result["label"] == "XCAGI 桌面执行端"
        assert result["status"] == "pending"
        assert result["local_base_url"] == ""

    def test_uses_label_when_present(self) -> None:
        data = {"desktop_label": "My Desktop", "status": "paired"}
        result = MobileRelayService._public_desktop(MagicMock(), data)
        assert result["label"] == "My Desktop"

    def test_builds_local_base_url_with_host_and_port(self) -> None:
        data = {"capabilities": {"host": "192.168.1.1", "port": 8080}, "status": "paired"}
        result = MobileRelayService._public_desktop(MagicMock(), data)
        assert result["local_base_url"] == "http://192.168.1.1:8080"

    def test_builds_local_base_url_without_port(self) -> None:
        data = {"capabilities": {"host": "192.168.1.1", "port": 0}}
        result = MobileRelayService._public_desktop(MagicMock(), data)
        assert result["local_base_url"] == "http://192.168.1.1"

    def test_skips_local_base_url_for_wildcard_host(self) -> None:
        data = {"capabilities": {"host": "0.0.0.0", "port": 8080}}
        result = MobileRelayService._public_desktop(MagicMock(), data)
        assert result["local_base_url"] == ""

    def test_skips_local_base_url_for_ipv6_wildcard(self) -> None:
        data = {"capabilities": {"host": "::", "port": 8080}}
        result = MobileRelayService._public_desktop(MagicMock(), data)
        assert result["local_base_url"] == ""

    def test_skips_local_base_url_when_no_host(self) -> None:
        data = {"capabilities": {"port": 8080}}
        result = MobileRelayService._public_desktop(MagicMock(), data)
        assert result["local_base_url"] == ""

    def test_capabilities_defaults_to_empty_dict_when_not_dict(self) -> None:
        data = {"capabilities": "not a dict"}
        result = MobileRelayService._public_desktop(MagicMock(), data)
        assert result["capabilities"] == {}

    def test_paired_at_only_when_paired(self) -> None:
        data = {"status": "paired", "updated_at": "2026-01-01T00:00:00+00:00"}
        result = MobileRelayService._public_desktop(MagicMock(), data)
        assert result["paired_at"] == "2026-01-01T00:00:00+00:00"

    def test_paired_at_empty_when_not_paired(self) -> None:
        data = {"status": "pending", "updated_at": "2026-01-01T00:00:00+00:00"}
        result = MobileRelayService._public_desktop(MagicMock(), data)
        assert result["paired_at"] == ""

    def test_uses_default_status_when_missing(self) -> None:
        data = {}
        result = MobileRelayService._public_desktop(MagicMock(), data)
        assert result["status"] == "pending"

    def test_includes_all_fields(self) -> None:
        data = {
            "relay_id": "r1",
            "desktop_label": "L",
            "device_id": "d1",
            "status": "paired",
            "relay_base_url": "https://x/",
            "capabilities": {},
            "last_seen_at": "2026-01-01",
            "created_at": "2026-01-01",
            "updated_at": "2026-01-02",
        }
        result = MobileRelayService._public_desktop(MagicMock(), data)
        assert result["relay_id"] == "r1"
        assert result["device_id"] == "d1"
        assert result["relay_base_url"] == "https://x/"
        assert result["last_seen_at"] == "2026-01-01"
        assert result["created_at"] == "2026-01-01"
        assert result["updated_at"] == "2026-01-02"
