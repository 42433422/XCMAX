"""app/http 工具单测：response_envelope / error_codes / request_context / json_response。

仅触达纯函数与轻量 Starlette 包装，无外部边界（铁律4）；覆盖空值/分支（铁律3）。
"""

from __future__ import annotations

from starlette.requests import Request

from app.http import error_codes
from app.http.json_response import json_response, json_response_tuple
from app.http.request_context import (
    get_current_http_request,
    reset_current_http_request,
    set_current_http_request,
)
from app.http.response_envelope import (
    fail,
    from_legacy_ok_payload,
    ok,
    read_success,
)


class TestResponseEnvelope:
    def test_ok_minimal(self):
        assert ok() == {"success": True}

    def test_ok_with_data_message_extra(self):
        out = ok({"id": 1}, message="done", page=2)
        assert out == {"success": True, "data": {"id": 1}, "message": "done", "page": 2}

    def test_ok_skips_none_data_and_message(self):
        assert ok(None) == {"success": True}

    def test_fail_minimal(self):
        assert fail("boom") == {"success": False, "message": "boom"}

    def test_fail_with_code_and_data(self):
        out = fail("bad", error_code="E1", data={"x": 1}, trace="t")
        assert out == {
            "success": False,
            "message": "bad",
            "error_code": "E1",
            "data": {"x": 1},
            "trace": "t",
        }

    def test_read_success_from_success_key(self):
        assert read_success({"success": True}) is True
        assert read_success({"success": 0}) is False

    def test_read_success_from_ok_key(self):
        assert read_success({"ok": 1}) is True

    def test_read_success_default_when_missing(self):
        assert read_success({}) is True
        assert read_success({}, default=False) is False

    def test_read_success_non_dict(self):
        assert read_success(None) is True
        assert read_success("x", default=False) is False

    def test_from_legacy_maps_ok_to_success(self):
        out = from_legacy_ok_payload({"ok": True, "value": 5})
        assert out == {"success": True, "value": 5}
        assert "ok" not in out

    def test_from_legacy_non_dict(self):
        assert from_legacy_ok_payload([1, 2]) == {"success": True, "data": [1, 2]}


class TestErrorCodes:
    def test_constants_are_stable_strings(self):
        assert error_codes.UNAUTHORIZED == "UNAUTHORIZED"
        assert error_codes.NOT_FOUND == "NOT_FOUND"

    def test_error_envelope_without_details(self):
        out = error_codes.error_envelope("E", "msg")
        assert out == {"success": False, "error": {"code": "E", "message": "msg"}}

    def test_error_envelope_with_details(self):
        out = error_codes.error_envelope("E", "msg", details={"field": "x"})
        assert out["error"]["details"] == {"field": "x"}

    def test_error_envelope_empty_details_omitted(self):
        out = error_codes.error_envelope("E", "msg", details={})
        assert "details" not in out["error"]


class TestRequestContext:
    def test_default_is_none(self):
        assert get_current_http_request() is None

    def test_set_get_reset(self):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
        }
        req = Request(scope)
        token = set_current_http_request(req)
        try:
            assert get_current_http_request() is req
        finally:
            reset_current_http_request(token)
        assert get_current_http_request() is None

    def test_set_none(self):
        token = set_current_http_request(None)
        assert get_current_http_request() is None
        reset_current_http_request(token)


class TestJsonResponse:
    def test_json_response_carries_payload(self):
        r = json_response({"a": 1}, 201)
        assert r.status_code == 201
        assert r.mimetype == "application/json"
        assert r.get_json() == {"a": 1}

    def test_get_json_silent_flag_ignored(self):
        r = json_response({"k": "v"})
        assert r.get_json(silent=False) == {"k": "v"}
        assert r.status_code == 200

    def test_json_response_tuple(self):
        resp, status = json_response_tuple({"x": 9}, 202)
        assert status == 202
        assert resp.get_json() == {"x": 9}
