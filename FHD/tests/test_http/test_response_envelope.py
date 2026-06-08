"""Tests for standard API response envelope."""

from app.http.response_envelope import fail, from_legacy_ok_payload, ok, read_success


def test_ok_with_data():
    body = ok({"x": 1}, message="done")
    assert body == {"success": True, "data": {"x": 1}, "message": "done"}


def test_fail_with_code():
    body = fail("bad", error_code="E001")
    assert body["success"] is False
    assert body["error_code"] == "E001"


def test_from_legacy_ok_payload():
    body = from_legacy_ok_payload({"ok": True, "data": {"n": 1}})
    assert body["success"] is True
    assert body["data"] == {"n": 1}
    assert "ok" not in body


def test_from_legacy_ok_payload_false():
    body = from_legacy_ok_payload({"ok": False, "message": "nope"})
    assert body["success"] is False


def test_read_success_prefers_success_key():
    assert read_success({"success": True}) is True
    assert read_success({"success": False}) is False


def test_read_success_falls_back_to_legacy_ok():
    assert read_success({"ok": True}) is True
    assert read_success({"ok": False}) is False
