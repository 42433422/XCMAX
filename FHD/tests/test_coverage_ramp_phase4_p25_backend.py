"""COVERAGE_RAMP Phase 4 round 25: tools legacy branches."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.tools_payload_legacy import dispatch_legacy_tool_payload


def _j(data, status=200):
    return {"body": data, "status": status}


def _hdr(_k, default=""):
    return default


def _dispatch(tool_id, action, params=None):
    return dispatch_legacy_tool_payload(
        tool_id,
        action,
        params or {},
        json_response_fn=_j,
        hdr_getter=_hdr,
        parse_order_text_fn=lambda _t: {},
    )


# ---------------------------------------------------------------------------
# tools_payload_legacy — 剩余分支
# ---------------------------------------------------------------------------


def test_legacy_products_view_no_keyword() -> None:
    resp = _dispatch("products", "view", {})
    assert resp["body"]["redirect"] == "/console?view=products"


def test_legacy_products_default_message() -> None:
    resp = _dispatch("products", "other_action", {})
    assert resp["body"]["message"] == "产品管理"


def test_legacy_ocr_view() -> None:
    resp = _dispatch("ocr", "view", {})
    assert resp["body"]["redirect"] == "/console?view=ocr"


def test_legacy_upload_file_redirect() -> None:
    resp = _dispatch("upload_file", "view", {})
    assert resp["body"]["success"] is True


@patch("app.services.get_system_service")
def test_legacy_system_get_info(mock_get: MagicMock) -> None:
    mock_get.return_value.get_system_info.return_value = {"os": "test"}
    resp = _dispatch("system", "get_system_info", {})
    assert resp["body"]["success"] is True
    assert resp["body"]["data"]["os"] == "test"


def test_legacy_tools_table_list() -> None:
    resp = _dispatch("tools_table", "list", {})
    assert resp["body"]["success"] is True


def test_legacy_settings_view() -> None:
    resp = _dispatch("settings", "view", {})
    assert "settings" in resp["body"]["redirect"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
