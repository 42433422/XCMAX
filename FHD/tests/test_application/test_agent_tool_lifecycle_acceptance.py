"""Executable acceptance for AI tool registration, discovery, and invoke."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from statistics import quantiles
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application import agent_tool_lifecycle as service
from app.application.agent_tool_lifecycle import Actor
from app.fastapi_routes.agent_tool_lifecycle import router
from app.infrastructure.tenant_scope import tenant_scope
from app.utils.operational_errors import BOUNDARY_ERRORS

SHANGHAI = ZoneInfo("Asia/Shanghai")
SECRET = "sk-testfix1"
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name"],
    "properties": {
        "name": {"type": "string"},
        "qty": {"type": "integer"},
        "price": {"type": "number"},
        "ok": {"type": "boolean", "default": True},
        "tags": {"type": "array", "items": {"type": "string"}},
        "meta": {
            "type": "object",
            "additionalProperties": False,
            "required": ["sku"],
            "properties": {
                "sku": {"type": "string"},
                "note": {"type": "string", "default": "n"},
            },
        },
    },
}


def _p95(samples: list[float]) -> float:
    if len(samples) < 2:
        return samples[0] if samples else 0.0
    return quantiles(samples, n=100, method="inclusive")[94]


class Suite:
    def __init__(self, client: TestClient, holder: dict[str, int]) -> None:
        self.client = client
        self.holder = holder
        self.results: list[dict[str, Any]] = []

    def call(
        self,
        method: str,
        path: str,
        *,
        role: str = "admin",
        actor: str = "admin-1",
        body: dict | None = None,
        params: dict | None = None,
        tenant: int = 1,
    ) -> Any:
        self.holder["tenant"] = tenant
        headers = {"X-Actor-Role": role, "X-Actor-Id": actor}
        if role != "admin":
            headers["X-Employee-Id"] = actor
        response = self.client.request(method, path, json=body, params=params, headers=headers)
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text}
        return response.status_code, payload

    def record(
        self,
        case_id: str,
        request: dict,
        response: Any,
        ok: bool,
        detail: str = "",
        *,
        status: str | None = None,
    ) -> None:
        state = status or ("pass" if ok else "fail")
        self.results.append(
            {
                "id": case_id,
                "status": state,
                "request": request,
                "response": response,
                "detail": detail,
                "at_shanghai": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
            }
        )


def _data(payload: dict) -> dict:
    return payload.get("data") or {}


def _err(payload: dict) -> dict:
    return payload.get("error") or {}


def test_agent_tool_lifecycle_acceptance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("XCAGI_AGENT_TOOL_HEADER_AUTH", "1")
    db_path = tmp_path / "agent-tools.sqlite3"
    service.reset_for_tests(str(db_path))
    holder = {"tenant": 1}
    app = FastAPI()

    @app.middleware("http")
    async def _bind_authorized_tenant(request, call_next):  # type: ignore[no-untyped-def]
        with tenant_scope(int(holder["tenant"])):
            request.state.tenant_id = int(holder["tenant"])
            return await call_next(request)

    app.include_router(router)
    caplog.set_level(logging.INFO)
    suite = Suite(TestClient(app), holder)
    try:
        _run_all(suite, caplog, db_path)
    finally:
        service.reset_for_tests(None)
    failed = [item["id"] for item in suite.results if item["status"] == "fail"]
    assert not failed, failed


def _run_all(suite: Suite, caplog: pytest.LogCaptureFixture, db_path: Path) -> None:
    _principals(suite)
    created = _section_a01(suite)
    stored = _section_a02(suite, created)
    _section_a03(suite, stored)
    published = _section_a04(suite)
    _section_a05(suite, published)
    _section_a06(suite, published)
    _section_a07(suite)
    _section_a08(suite)
    _section_ad(suite, published)
    _section_as(suite, caplog, db_path)
    _section_ap(suite)


def _principals(suite: Suite) -> None:
    for principal, role in (("emp-a", "employee"), ("emp-b", "employee"), ("reader-1", "readonly")):
        status, payload = suite.call(
            "POST", "/api/agent-tools/employees", body={"principal_id": principal, "role": role}
        )
        assert status == 201, payload


def _base_body(key: str, **extra: Any) -> dict:
    body = {
        "tool_key": key,
        "name": key,
        "description": f"desc {key}",
        "input_schema": SCHEMA,
        "tenant_id": 999,
    }
    body.update(extra)
    return body


def _section_a01(suite: Suite) -> dict:
    missing = [
        ("A01", {"name": "n", "description": "d", "input_schema": SCHEMA}, "tool_key"),
        ("A01-1", {"tool_key": "needs_name", "description": "d", "input_schema": SCHEMA}, "name"),
        ("A01-2", {"tool_key": "needs_desc", "name": "n", "input_schema": SCHEMA}, "description"),
        ("A01-3", {"tool_key": "needs_schema", "name": "n", "description": "d"}, "input_schema"),
    ]
    for case_id, body, field in missing:
        status, payload = suite.call("POST", "/api/agent-tools", body=body)
        suite.record(
            case_id,
            {"method": "POST", "path": "/api/agent-tools", "body": body},
            {"status": status, "body": payload},
            status == 400
            and _err(payload).get("code") == "field_required"
            and _err(payload).get("field") == field,
            f"expected field_required:{field}",
        )
    status, created = suite.call(
        "POST", "/api/agent-tools", body=_base_body("quote_lookup", name="Original")
    )
    status2, duplicate = suite.call(
        "POST",
        "/api/agent-tools",
        body=_base_body("quote_lookup", name="Replaced", description="other"),
    )
    status3, listed = suite.call("GET", "/api/agent-tools", params={"q": "quote_lookup"})
    items = _data(listed).get("items") or []
    suite.record(
        "A01-4",
        {"method": "POST", "body": {"tool_key": "quote_lookup"}},
        {"status": status2, "body": duplicate},
        status == 201 and status2 == 409 and _err(duplicate).get("code") == "duplicate_tool_key",
    )
    suite.record(
        "A01-5",
        {"method": "GET", "q": "quote_lookup"},
        {"status": status3, "items": items},
        len(items) == 1 and items[0]["name"] == "Original" and items[0]["tenant_id"] == 1,
    )
    bad, bad_body = suite.call("POST", "/api/agent-tools", body=_base_body("bad key"))
    suite.record(
        "A01-6",
        {"tool_key": "bad key"},
        {"status": bad, "body": bad_body},
        bad == 400 and _err(bad_body).get("code") == "invalid_tool_key",
    )
    audit_status, audit = suite.call(
        "GET", "/api/agent-tools/audit", params={"tool_id": _data(created)["id"]}
    )
    events = _data(audit).get("events") or []
    create_events = [item for item in events if item["kind"] == "create"]
    suite.record(
        "A01-7",
        {"tool_id": _data(created).get("id")},
        {"status": audit_status, "events": create_events},
        len(create_events) == 1
        and create_events[0]["actor_id"] == "admin-1"
        and create_events[0]["at_shanghai"],
    )
    return _data(created)


def _section_a02(suite: Suite, created: dict) -> dict:
    invalid = {
        "type": "object",
        "properties": {"when": {"type": "date"}},
    }
    status, payload = suite.call(
        "POST", f"/api/agent-tools/{created['id']}/validate", body={"input_schema": invalid}
    )
    suite.record(
        "A02",
        {"input_schema": invalid},
        {"status": status, "body": payload},
        status == 400 and _err(payload).get("code") == "invalid_json_schema",
    )
    status, payload = suite.call(
        "PUT",
        f"/api/agent-tools/{created['id']}",
        body={"expected_version": created["version_no"], "input_schema": SCHEMA},
    )
    params = (_data(payload).get("function") or {}).get("parameters") or {}
    properties = params.get("properties") or {}
    for case_id, name, kind in (
        ("A02-1", "name", "string"),
        ("A02-2", "qty", "integer"),
        ("A02-3", "price", "number"),
        ("A02-4", "ok", "boolean"),
        ("A02-5", "tags", "array"),
        ("A02-6", "meta", "object"),
    ):
        suite.record(
            case_id,
            {"tool_id": created["id"], "property": name},
            {"status": status, "property": properties.get(name)},
            status == 200 and (properties.get(name) or {}).get("type") == kind,
        )
    return _data(payload)


def _section_a03(suite: Suite, stored: dict) -> None:
    tool_id = stored["id"]
    suite.call("POST", f"/api/agent-tools/{tool_id}/publish", body={"scope": "tenant"})
    checks = [
        ("A03", {"qty": 1}, 400, "field_required"),
        ("A03-1", {"name": "a"}, 200, None),
        ("A03-2", {"name": "a"}, 200, None),
        ("A03-3", {"name": "a", "qty": "1"}, 400, "type_mismatch"),
        ("A03-4", {"name": "a", "extra": 1}, 400, "unexpected_property"),
        ("A03-5", {"name": "a", "qty": True}, 400, "type_mismatch"),
        ("A03-6", {"name": "a", "ok": False}, 200, None),
        ("A03-7", {"name": "a", "tags": [1]}, 400, "type_mismatch"),
        ("A03-8", {"name": "a", "meta": {}}, 400, "field_required"),
    ]
    for case_id, arguments, expect, code in checks:
        status, payload = suite.call(
            "POST", f"/api/agent-tools/{tool_id}/invoke", body={"arguments": arguments}
        )
        ok = status == expect and (code is None or _err(payload).get("code") == code)
        if case_id == "A03-1":
            ok = ok and "qty" not in (_data(payload).get("validated") or {})
        if case_id == "A03-2":
            ok = ok and (_data(payload).get("validated") or {}).get("ok") is True
        if case_id == "A03-6":
            ok = ok and (_data(payload).get("validated") or {}).get("ok") is False
        suite.record(case_id, {"arguments": arguments}, {"status": status, "body": payload}, ok)


def _section_a04(suite: Suite) -> dict[str, dict]:
    tools = {}
    for case_id, key, scope, employee in (
        ("A04-2", "global_tool", "global", None),
        ("A04-3", "tenant_tool", "tenant", None),
        ("A04-4", "employee_tool", "employee", "emp-a"),
    ):
        status, created = suite.call("POST", "/api/agent-tools", body=_base_body(key))
        body = {"scope": scope}
        if employee:
            body["employee_id"] = employee
        pub_status, published = suite.call(
            "POST", f"/api/agent-tools/{_data(created)['id']}/publish", body=body
        )
        record = _data(published).get("publish_record") or {}
        tools[key] = _data(published)
        suite.record(
            case_id,
            body,
            {"status": pub_status, "body": published},
            status == 201
            and pub_status == 200
            and _data(published).get("scope") == scope
            and record.get("actor_id") == "admin-1"
            and str(record.get("at_shanghai") or "").endswith("+08:00"),
        )
    draft_status, draft = suite.call("POST", "/api/agent-tools", body=_base_body("still_draft"))
    found, discovery = suite.call(
        "GET", "/api/agent-tools/discovery", role="employee", actor="emp-a"
    )
    names = [item["function"]["name"] for item in _data(discovery).get("tools") or []]
    suite.record(
        "A04",
        {"employee": "emp-a"},
        {"status": found, "names": names},
        draft_status == 201 and "still_draft" not in names and "global_tool" in names,
    )
    invoke_status, invoke = suite.call(
        "POST",
        f"/api/agent-tools/{_data(draft)['id']}/invoke",
        role="employee",
        actor="emp-a",
        body={"arguments": {"name": "a"}},
    )
    suite.record(
        "A04-1",
        {"tool_id": _data(draft)["id"]},
        {"status": invoke_status, "body": invoke},
        invoke_status == 403 and _err(invoke).get("code") == "tool_not_published",
    )
    record = tools["global_tool"]["publish_record"]
    suite.record(
        "A04-5",
        {"publish_record": record},
        record,
        record["actor_role"] == "admin"
        and record["at"].endswith("Z")
        and "+08:00" in record["at_shanghai"],
    )
    tool_id = tools["tenant_tool"]["id"]
    off, unpublished = suite.call("POST", f"/api/agent-tools/{tool_id}/unpublish")
    again, republished = suite.call(
        "POST", f"/api/agent-tools/{tool_id}/publish", body={"scope": "tenant"}
    )
    audit_status, audit = suite.call("GET", "/api/agent-tools/audit", params={"tool_id": tool_id})
    kinds = [item["kind"] for item in _data(audit).get("events") or []]
    unpublish_rows = [
        item for item in _data(audit).get("events") or [] if item["kind"] == "unpublish"
    ]
    republish_rows = [
        item for item in _data(audit).get("events") or [] if item["kind"] == "republish"
    ]
    suite.record(
        "A04-6",
        {"tool_id": tool_id},
        {"unpublish": off, "republish": again, "kinds": kinds},
        off == 200
        and again == 200
        and unpublish_rows
        and republish_rows
        and unpublish_rows[0]["id"] != republish_rows[0]["id"]
        and _data(unpublished)["status"] == "draft"
        and _data(republished)["status"] == "published",
    )
    tools["tenant_tool"] = _data(republished)
    return tools


def _section_a05(suite: Suite, published: dict) -> None:
    status, detail = suite.call("GET", f"/api/agent-tools/{published['global_tool']['id']}")
    stored = (_data(detail).get("function") or {}).get("parameters")
    suite.record(
        "A05",
        {"id": published["global_tool"]["id"]},
        {"status": status, "parameters": stored},
        status == 200 and stored == SCHEMA,
    )
    status, found = suite.call("GET", "/api/agent-tools", params={"q": "global_tool"})
    items = _data(found).get("items") or []
    suite.record(
        "A05-1",
        {"q": "global_tool"},
        {"status": status, "count": len(items)},
        status == 200 and len(items) == 1 and items[0]["tool_key"] == "global_tool",
    )
    status, drafts = suite.call("GET", "/api/agent-tools", params={"status": "draft"})
    suite.record(
        "A05-2",
        {"status": "draft"},
        {"status": status, "keys": [item["tool_key"] for item in _data(drafts).get("items") or []]},
        status == 200
        and all(item["status"] == "draft" for item in _data(drafts).get("items") or [])
        and "still_draft" in [item["tool_key"] for item in _data(drafts).get("items") or []],
    )
    for index in range(12):
        suite.call("POST", "/api/agent-tools", body=_base_body(f"page_tool_{index:02d}"))
    pages = []
    ok_pages = True
    for page, expected_len in ((1, 5), (2, 5), (3, 2)):
        status, payload = suite.call(
            "GET", "/api/agent-tools", params={"q": "page_tool_", "page": page, "page_size": 5}
        )
        items = _data(payload).get("items") or []
        pages.append(items)
        ok_pages = (
            ok_pages
            and status == 200
            and _data(payload)["total"] == 12
            and len(items) == expected_len
        )
    empty_status, empty = suite.call(
        "GET", "/api/agent-tools", params={"q": "page_tool_", "page": 20, "page_size": 5}
    )
    ids = [item["id"] for page in pages for item in page]
    suite.record(
        "A05-3",
        {"page_size": 5},
        {"pages": [[item["tool_key"] for item in page] for page in pages]},
        ok_pages and len(ids) == len(set(ids)),
    )
    suite.record(
        "A05-4",
        {"id": published["global_tool"]["id"]},
        {"parameters": stored},
        stored["properties"]["tags"]["items"]["type"] == "string"
        and stored["required"] == ["name"],
    )
    status, other = suite.call("GET", "/api/agent-tools", tenant=2)
    foreign, foreign_body = suite.call(
        "GET", f"/api/agent-tools/{published['global_tool']['id']}", tenant=2
    )
    suite.record(
        "A05-5",
        {"tenant_context": 2},
        {"list": other, "detail": foreign},
        status == 200 and _data(other)["total"] == 0 and foreign == 404,
    )
    status, scoped = suite.call("GET", "/api/agent-tools", params={"scope": "employee"})
    keys = [item["tool_key"] for item in _data(scoped).get("items") or []]
    suite.record(
        "A05-6", {"scope": "employee"}, {"keys": keys}, status == 200 and keys == ["employee_tool"]
    )
    suite.record(
        "A05-7",
        {"page": 20},
        {"status": empty_status, "body": empty},
        empty_status == 200 and _data(empty)["items"] == [] and _data(empty)["total"] >= 12,
    )
    seen, discovery = suite.call(
        "GET", "/api/agent-tools/discovery", role="employee", actor="emp-a"
    )
    names = [item["function"]["name"] for item in _data(discovery).get("tools") or []]
    suite.record(
        "A05-8",
        {"discovery": "emp-a"},
        {"names": names},
        seen == 200 and "still_draft" not in names and "global_tool" in names,
    )


def _section_a06(suite: Suite, published: dict) -> None:
    tool = published["global_tool"]
    warm, before = suite.call("GET", "/api/agent-tools/discovery", role="employee", actor="emp-a")
    listed, list_before = suite.call(
        "GET", "/api/agent-tools", params={"q": "global_tool", "status": "published"}
    )
    off, offline = suite.call("POST", f"/api/agent-tools/{tool['id']}/offline")
    after_status, after = suite.call(
        "GET", "/api/agent-tools/discovery", role="employee", actor="emp-a"
    )
    list_status, list_after = suite.call(
        "GET", "/api/agent-tools", params={"q": "global_tool", "status": "published"}
    )
    names_before = [item["function"]["name"] for item in _data(before).get("tools") or []]
    names_after = [item["function"]["name"] for item in _data(after).get("tools") or []]
    suite.record(
        "A06",
        {"id": tool["id"]},
        {"before": names_before, "after": names_after},
        warm == 200
        and "global_tool" in names_before
        and after_status == 200
        and "global_tool" not in names_after,
    )
    invoke, invoke_body = suite.call(
        "POST",
        f"/api/agent-tools/{tool['id']}/invoke",
        role="employee",
        actor="emp-a",
        body={"arguments": {"name": "a"}},
    )
    suite.record(
        "A06-1",
        {"id": tool["id"]},
        {"status": invoke, "body": invoke_body},
        invoke == 409 and _err(invoke_body).get("code") == "tool_offline",
    )
    published_keys = [item["tool_key"] for item in _data(list_after).get("items") or []]
    suite.record(
        "A06-2",
        {"cached_list": True},
        {
            "before": [item["tool_key"] for item in _data(list_before).get("items") or []],
            "after": published_keys,
        },
        listed == 200 and list_status == 200 and "global_tool" not in published_keys,
    )
    direct, direct_body = suite.call(
        "POST",
        f"/api/agent-tools/{tool['id']}/invoke",
        body={"arguments": {"name": "a"}, "version_id": tool["current_version_id"]},
    )
    suite.record(
        "A06-3",
        {"id": tool["id"]},
        {"status": direct, "body": direct_body},
        direct == 409 and _err(direct_body).get("code") == "tool_offline",
    )
    suite.record(
        "A06-4",
        {"version_id": tool["current_version_id"]},
        {"status": direct, "body": direct_body},
        direct == 409 and _err(direct_body).get("code") == "tool_offline",
    )
    relist, relisted = suite.call("POST", f"/api/agent-tools/{tool['id']}/relist")
    count, listing = suite.call("GET", "/api/agent-tools", params={"q": "global_tool"})
    rows = _data(listing).get("items") or []
    suite.record(
        "A06-5",
        {"id": tool["id"]},
        {"status": relist, "rows": rows},
        relist == 200
        and _data(relisted)["id"] == tool["id"]
        and _data(relisted)["status"] == "published"
        and count == 200
        and len(rows) == 1,
    )
    audit_status, audit = suite.call(
        "GET", "/api/agent-tools/audit", params={"tool_id": tool["id"]}
    )
    events = _data(audit).get("events") or []
    suite.record(
        "A06-6",
        {"id": tool["id"]},
        {"events": [item["kind"] for item in events]},
        audit_status == 200
        and any(item["kind"] == "relist" and item["actor_id"] == "admin-1" for item in events),
    )
    suite.record(
        "A06-7",
        {"id": tool["id"]},
        {"events": events},
        any(item["kind"] == "offline" and item["at_shanghai"] for item in events),
    )
    back, discovery = suite.call(
        "GET", "/api/agent-tools/discovery", role="employee", actor="emp-a"
    )
    names = [item["function"]["name"] for item in _data(discovery).get("tools") or []]
    suite.record(
        "A06-8", {"employee": "emp-a"}, {"names": names}, back == 200 and "global_tool" in names
    )


def _section_a07(suite: Suite) -> None:
    status, created = suite.call("POST", "/api/agent-tools", body=_base_body("versioned_tool"))
    tool_id = _data(created)["id"]
    suite.call("POST", f"/api/agent-tools/{tool_id}/publish", body={"scope": "tenant"})
    begin, started = suite.call(
        "POST",
        f"/api/agent-tools/{tool_id}/calls",
        role="employee",
        actor="emp-a",
        body={"arguments": {"name": "inflight"}},
    )
    old_version = _data(started).get("version_id")
    updated, update = suite.call(
        "PUT",
        f"/api/agent-tools/{tool_id}",
        body={
            "expected_version": _data(created)["version_no"],
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "qty"],
                "properties": {"name": {"type": "string"}, "qty": {"type": "integer"}},
            },
        },
    )
    suite.record(
        "A07",
        {"tool_id": tool_id, "expected_version": _data(created)["version_no"]},
        {"status": updated, "body": update},
        status == 201
        and updated == 200
        and _data(update)["version_no"] == _data(created)["version_no"] + 1
        and _data(update)["current_version_id"] != old_version,
        "update stores a new version without replacing the in-flight version id",
    )
    finished, done = suite.call(
        "POST",
        f"/api/agent-tools/calls/{_data(started).get('call_id')}/finish",
        role="employee",
        actor="emp-a",
    )
    suite.record(
        "A07-1",
        {"call_id": _data(started).get("call_id")},
        {"begin": begin, "finish": finished, "body": done},
        begin == 201
        and finished == 200
        and _data(done).get("version_id") == old_version
        and "qty" not in (_data(done).get("validated") or {}),
    )
    new_status, new_call = suite.call(
        "POST",
        f"/api/agent-tools/{tool_id}/invoke",
        role="employee",
        actor="emp-a",
        body={"arguments": {"name": "next"}},
    )
    suite.record(
        "A07-2",
        {"arguments": {"name": "next"}},
        {"status": new_status, "body": new_call},
        updated == 200
        and new_status == 400
        and _err(new_call).get("code") == "field_required"
        and _data(update)["current_version_id"] != old_version,
    )
    before, detail_before = suite.call("GET", f"/api/agent-tools/{tool_id}")
    bad, failed = suite.call(
        "PUT",
        f"/api/agent-tools/{tool_id}",
        body={
            "expected_version": _data(update)["version_no"],
            "input_schema": {"type": "object", "properties": {"x": {"type": "date"}}},
        },
    )
    after, detail_after = suite.call("GET", f"/api/agent-tools/{tool_id}")
    suite.record(
        "A07-3",
        {"expected_version": _data(update)["version_no"]},
        {
            "status": bad,
            "before": _data(detail_before).get("current_version_id"),
            "after": _data(detail_after).get("current_version_id"),
        },
        bad == 400
        and _err(failed).get("code") == "invalid_json_schema"
        and _data(detail_before)["current_version_id"] == _data(detail_after)["current_version_id"]
        and _data(detail_before)["version_no"] == _data(detail_after)["version_no"],
    )
    expected = _data(detail_after)["version_no"]
    barrier = threading.Barrier(2)
    outcomes: list[tuple[int, dict]] = []

    def _race(name: str) -> None:
        barrier.wait()
        with tenant_scope(1):
            try:
                payload = service.update_tool(
                    Actor("admin-1", "admin", None, 1),
                    tool_id,
                    {"expected_version": expected, "name": name},
                )
                outcomes.append((200, {"ok": True, "data": payload}))
            except service.ToolLifecycleError as exc:
                outcomes.append(
                    (exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
                )

    threads = [threading.Thread(target=_race, args=(name,)) for name in ("Winner", "Loser")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    codes = sorted(item[0] for item in outcomes)
    final_status, final_body = suite.call("GET", f"/api/agent-tools/{tool_id}")
    suite.record(
        "A07-4",
        {"path": "application service", "expected_version": expected},
        {"codes": codes, "name": _data(final_body).get("name")},
        codes == [200, 409]
        and any(
            _err(item[1]).get("code") == "version_conflict" for item in outcomes if item[0] == 409
        ),
    )
    winner = next(item[1] for item in outcomes if item[0] == 200)
    final_name = _data(final_body).get("name")
    winner_name = _data(winner).get("name")
    suite.record(
        "A07-5",
        {"concurrent_names": ["Winner", "Loser"]},
        {"final": final_name, "winner": winner_name},
        final_status == 200 and final_name == winner_name and final_name in {"Winner", "Loser"},
        "final name matches the single successful update",
    )
    versions = _data(final_body).get("versions") or []
    suite.record(
        "A07-6",
        {"id": tool_id},
        {"versions": versions},
        len(versions) >= 2
        and all(item["actor_id"] == "admin-1" and item["at_shanghai"] for item in versions),
    )
    first = versions[0]
    pin_status, pinned = suite.call(
        "POST",
        f"/api/agent-tools/{tool_id}/invoke",
        role="employee",
        actor="emp-a",
        body={"version_id": first["id"], "arguments": {"qty": "bad"}},
    )
    suite.record(
        "A07-7",
        {"version_id": first["id"], "arguments": {"qty": "bad"}},
        {"status": pin_status, "body": pinned},
        pin_status == 400
        and _err(pinned).get("code") == "incompatible_params"
        and len({item["id"] for item in versions}) == len(versions),
    )
    current = _data(final_body)["current_version_id"]
    rolled, rollback = suite.call(
        "POST", f"/api/agent-tools/{tool_id}/rollback", body={"version_id": first["id"]}
    )
    deprecated, deprecate = suite.call(
        "POST", f"/api/agent-tools/{tool_id}/deprecate", body={"version_id": current}
    )
    rejected, reject_body = suite.call(
        "POST",
        f"/api/agent-tools/{tool_id}/invoke",
        role="employee",
        actor="emp-a",
        body={"version_id": current, "arguments": {"name": "a"}},
    )
    detail_status, detail = suite.call("GET", f"/api/agent-tools/{tool_id}")
    calls = _data(detail).get("calls") or []
    matched = [item for item in calls if item["version_id"] == old_version]
    suite.record(
        "A07-8",
        {"rollback_to": first["id"], "deprecate": current},
        {"rollback": rolled, "deprecate": deprecated, "invoke": rejected, "calls": len(calls)},
        rolled == 200
        and _data(rollback)["current_version_id"] == first["id"]
        and deprecated == 200
        and rejected == 409
        and _err(reject_body).get("code") == "version_deprecated"
        and _err(deprecate).get("code", "") == ""
        and matched
        and matched[0]["definition"]["function"]["parameters"]["properties"]["name"]["type"]
        == "string"
        and detail_status == 200,
    )


def _section_a08(suite: Suite) -> None:
    status, created = suite.call("POST", "/api/agent-tools", body=_base_body("grant_tool"))
    tool_id = _data(created)["id"]
    pub, published = suite.call(
        "POST",
        f"/api/agent-tools/{tool_id}/publish",
        body={"scope": "employee", "employee_id": "emp-a"},
    )
    grant_id = _data(published)["grant_id"]
    allowed, allow_body = suite.call(
        "POST",
        f"/api/agent-tools/{tool_id}/invoke",
        role="employee",
        actor="emp-a",
        body={"arguments": {"name": "a"}},
    )
    suite.record(
        "A08",
        {"grant_id": grant_id},
        {"status": allowed, "body": allow_body},
        pub == 200 and allowed == 200 and _data(allow_body).get("success") is True,
    )
    denied, deny_body = suite.call(
        "POST",
        "/api/agent-tools/permissions",
        body={
            "tool_id": tool_id,
            "subject_type": "employee",
            "subject_id": "emp-a",
            "effect": "deny",
        },
    )
    blocked, blocked_body = suite.call(
        "POST",
        f"/api/agent-tools/{tool_id}/invoke",
        role="employee",
        actor="emp-a",
        body={"arguments": {"name": "a"}},
    )
    suite.record(
        "A08-1",
        {"effect": "deny"},
        {"status": blocked, "body": blocked_body},
        denied == 201 and blocked == 403 and _err(blocked_body).get("code") == "invoke_denied",
    )
    revoke, _revoked = suite.call("POST", f"/api/agent-tools/permissions/{grant_id}/revoke")
    # Remove the deny so the only remaining access path is the revoked grant.
    deny_id = _data(deny_body)["permission_id"]
    suite.call("POST", f"/api/agent-tools/permissions/{deny_id}/revoke")
    after_revoke, revoke_body = suite.call(
        "POST",
        f"/api/agent-tools/{tool_id}/invoke",
        role="employee",
        actor="emp-a",
        body={"arguments": {"name": "a"}},
    )
    suite.record(
        "A08-2",
        {"permission_id": grant_id},
        {"status": after_revoke, "body": revoke_body},
        revoke == 200
        and after_revoke == 403
        and _err(revoke_body).get("code") == "invoke_forbidden",
    )
    admin_status, admin_body = suite.call(
        "POST", f"/api/agent-tools/{tool_id}/invoke", body={"arguments": {"name": "admin"}}
    )
    reader_status, reader_body = suite.call(
        "POST",
        f"/api/agent-tools/{tool_id}/invoke",
        role="readonly",
        actor="reader-1",
        body={"arguments": {"name": "a"}},
    )
    suite.record(
        "A08-3",
        {"roles": ["admin", "employee", "readonly"]},
        {"admin": admin_status, "employee": after_revoke, "readonly": reader_status},
        admin_status == 200
        and _data(admin_body).get("success") is True
        and reader_status == 403
        and _err(reader_body).get("code") == "invoke_forbidden",
    )
    employee_pub, employee_pub_body = suite.call(
        "POST",
        f"/api/agent-tools/{tool_id}/publish",
        role="employee",
        actor="emp-a",
        body={"scope": "tenant"},
    )
    suite.record(
        "A08-4",
        {"role": "employee"},
        {"status": employee_pub, "body": employee_pub_body},
        employee_pub == 403 and _err(employee_pub_body).get("code") == "admin_required",
    )
    forged, forged_body = suite.call(
        "POST",
        "/api/agent-tools/permissions",
        body={
            "tool_id": tool_id,
            "subject_type": "employee",
            "subject_id": "missing-emp",
            "effect": "grant",
        },
    )
    suite.record(
        "A08-5",
        {"subject_id": "missing-emp"},
        {"status": forged, "body": forged_body},
        forged == 404 and _err(forged_body).get("code") == "forged_employee",
    )
    missing_tool, missing_body = suite.call(
        "POST",
        "/api/agent-tools/permissions",
        body={
            "tool_id": "not-a-tool",
            "subject_type": "role",
            "subject_id": "employee",
            "effect": "grant",
        },
    )
    suite.record(
        "A08-6",
        {"tool_id": "not-a-tool"},
        {"status": missing_tool, "body": missing_body},
        missing_tool == 404 and _err(missing_body).get("code") == "unknown_tool",
    )
    missing_perm, missing_perm_body = suite.call(
        "POST", "/api/agent-tools/permissions/not-a-permission/revoke"
    )
    suite.record(
        "A08-7",
        {"permission_id": "not-a-permission"},
        {"status": missing_perm, "body": missing_perm_body},
        missing_perm == 404 and _err(missing_perm_body).get("code") == "unknown_permission",
    )
    restored, restored_body = suite.call(
        "POST",
        "/api/agent-tools/permissions",
        body={
            "tool_id": tool_id,
            "subject_type": "employee",
            "subject_id": "emp-a",
            "effect": "grant",
        },
    )
    seen, discovery = suite.call(
        "GET", "/api/agent-tools/discovery", role="employee", actor="emp-a"
    )
    names = [item["function"]["name"] for item in _data(discovery).get("tools") or []]
    suite.call(
        "POST", f"/api/agent-tools/permissions/{_data(restored_body)['permission_id']}/revoke"
    )
    hidden, after = suite.call("GET", "/api/agent-tools/discovery", role="employee", actor="emp-a")
    names_after = [item["function"]["name"] for item in _data(after).get("tools") or []]
    audit_status, audit = suite.call("GET", "/api/agent-tools/audit", params={"tool_id": tool_id})
    kinds = [item["kind"] for item in _data(audit).get("events") or []]
    suite.record(
        "A08-8",
        {"tool": "grant_tool"},
        {"before": names, "after": names_after, "kinds": kinds},
        restored == 201
        and seen == 200
        and "grant_tool" in names
        and hidden == 200
        and "grant_tool" not in names_after
        and {"grant", "deny", "revoke"} <= set(kinds)
        and audit_status == 200,
    )


def _section_ad(suite: Suite, published: dict) -> None:
    from app.application.employee_runtime.tool_scope import resolve_employee_tools

    status, discovery = suite.call(
        "GET", "/api/agent-tools/discovery", role="employee", actor="emp-a"
    )
    tools = {item["function"]["name"]: item for item in _data(discovery).get("tools") or []}
    global_tool = tools.get("global_tool")
    with tenant_scope(1):
        runtime = {
            item["function"]["name"]: item
            for item in resolve_employee_tools("emp-a", {"description": "general"}, {})
            if isinstance(item, dict) and isinstance(item.get("function"), dict)
        }
    runtime_tool = runtime.get("global_tool")
    suite.record(
        "AD01",
        {"employee": "emp-a"},
        {"http": status, "runtime_name": (runtime_tool or {}).get("function", {}).get("name")},
        status == 200 and runtime_tool and runtime_tool["function"]["name"] == "global_tool",
    )
    suite.record(
        "AD02",
        {"name": "global_tool"},
        {"description": (runtime_tool or {}).get("function", {}).get("description")},
        bool(runtime_tool) and runtime_tool["function"]["description"] == "desc global_tool",
    )
    suite.record(
        "AD03",
        {"name": "global_tool"},
        {"schema": (runtime_tool or {}).get("function", {}).get("parameters")},
        bool(runtime_tool) and runtime_tool["function"]["parameters"]["type"] == "object",
    )
    required = ((runtime_tool or {}).get("function") or {}).get("parameters", {}).get("required")
    properties = (
        ((runtime_tool or {}).get("function") or {}).get("parameters", {}).get("properties", {})
    )
    suite.record(
        "AD04",
        {"required": required},
        {"properties": sorted(properties)},
        required == ["name"] and "qty" in properties and "qty" not in required,
    )
    suite.record(
        "AD05",
        {"runtime": sorted(runtime)},
        {"names": sorted(runtime)},
        "still_draft" not in runtime,
    )
    suite.call("POST", f"/api/agent-tools/{published['employee_tool']['id']}/offline")
    with tenant_scope(1):
        runtime_off = {
            item["function"]["name"]: item
            for item in resolve_employee_tools("emp-a", {}, {})
            if isinstance(item, dict) and isinstance(item.get("function"), dict)
        }
    suite.record(
        "AD06",
        {"offline": "employee_tool"},
        {"names": sorted(runtime_off)},
        "employee_tool" not in runtime_off,
    )
    with tenant_scope(2):
        other = resolve_employee_tools("emp-a", {}, {})
    other_names = [
        (item.get("function") or {}).get("name") for item in other if isinstance(item, dict)
    ]
    suite.record(
        "AD07",
        {"tenant": 2},
        {"names": other_names},
        "global_tool" not in other_names
        and "tenant_tool" not in other_names
        and "secret_tool" not in other_names,
    )
    with tenant_scope(1):
        emp_b = {
            (item.get("function") or {}).get("name")
            for item in resolve_employee_tools("emp-b", {}, {})
            if isinstance(item, dict)
        }
    suite.record(
        "AD08",
        {"employee": "emp-b"},
        {"names": sorted(name for name in emp_b if name)},
        "employee_tool" not in emp_b and "tenant_tool" in emp_b,
    )
    exec_status, executed = suite.call(
        "POST",
        f"/api/agent-tools/{published['global_tool']['id']}/invoke",
        role="employee",
        actor="emp-a",
        body={"arguments": {"name": "schema"}},
    )
    with tenant_scope(1):
        from app.application.tools.workflow import execute_workflow_tool

        raw = execute_workflow_tool(
            "global_tool",
            {"name": "schema"},
            runtime_context={"employee_id": "emp-a", "source": "employee_runtime"},
        )
    workflow = json.loads(raw)
    http_schema = (_data(executed).get("definition") or {}).get("function", {}).get("parameters")
    runtime_schema = (runtime_tool or {}).get("function", {}).get("parameters")
    workflow_schema = (workflow.get("definition") or {}).get("function", {}).get("parameters")
    suite.record(
        "AD09",
        {"tool": "global_tool"},
        {"http": http_schema, "runtime": runtime_schema, "workflow_ok": workflow.get("ok")},
        exec_status == 200 and http_schema == runtime_schema == workflow_schema == SCHEMA,
    )
    # grant_tool was revoked in A08. emp-a must not receive it from the runtime catalog.
    suite.record(
        "AD10",
        {"tool": "grant_tool"},
        {"names": sorted(runtime_off)},
        "grant_tool" not in runtime_off,
    )


def _section_as(suite: Suite, caplog: pytest.LogCaptureFixture, db_path: Path) -> None:
    status, created = suite.call(
        "POST",
        "/api/agent-tools",
        body=_base_body(
            "secret_tool", description=f"call with {SECRET} and token=super-secret-value"
        ),
    )
    tool_id = _data(created)["id"]
    suite.call("POST", f"/api/agent-tools/{tool_id}/publish", body={"scope": "tenant"})
    seen, discovery = suite.call(
        "GET", "/api/agent-tools/discovery", role="employee", actor="emp-a"
    )
    blob = json.dumps(discovery, ensure_ascii=False)
    suite.record(
        "AS01",
        {"tool": "secret_tool"},
        {"discovery": blob},
        seen == 200 and SECRET not in blob and "super-secret-value" not in blob,
    )
    log_text = caplog.text
    db_text = db_path.read_bytes().decode("utf-8", errors="ignore")
    suite.record(
        "AS02",
        {"log": True},
        {"secret_in_log": SECRET in log_text, "secret_in_db": SECRET in db_text},
        SECRET not in log_text and SECRET not in db_text and "super-secret-value" not in log_text,
    )
    detail_status, detail = suite.call("GET", f"/api/agent-tools/{tool_id}")
    public = json.dumps(detail, ensure_ascii=False)
    suite.record(
        "AS03",
        {"id": tool_id},
        {"body": public},
        detail_status == 200 and SECRET not in public and "super-secret-value" not in public,
    )
    suite.record(
        "AS04",
        {"body_tenant_id": 999},
        {"stored_tenant": _data(created).get("tenant_id")},
        _data(created).get("tenant_id") == 1,
    )
    foreign, foreign_body = suite.call("GET", f"/api/agent-tools/{tool_id}", tenant=2)
    suite.record(
        "AS05",
        {"forged_context_switch": 2},
        {"status": foreign, "body": foreign_body},
        foreign == 404 and _err(foreign_body).get("code") == "unknown_tool",
    )
    suite.call("POST", f"/api/agent-tools/{tool_id}/offline")
    offline, offline_body = suite.call(
        "POST",
        f"/api/agent-tools/{tool_id}/invoke",
        role="employee",
        actor="emp-a",
        body={"arguments": {"name": "a"}},
    )
    suite.record(
        "AS06",
        {"id": tool_id},
        {"status": offline, "body": offline_body},
        offline == 409 and _err(offline_body).get("code") == "tool_offline",
    )
    suite.call("POST", f"/api/agent-tools/{tool_id}/relist")
    executed, invoke = suite.call(
        "POST",
        f"/api/agent-tools/{tool_id}/invoke",
        role="employee",
        actor="emp-a",
        body={"arguments": {"name": "a"}},
    )
    again, discovery = suite.call(
        "GET", "/api/agent-tools/discovery", role="employee", actor="emp-a"
    )
    match = next(
        item for item in _data(discovery)["tools"] if item["function"]["name"] == "secret_tool"
    )
    suite.record(
        "AS07",
        {"tool": "secret_tool"},
        {
            "discovery": match["function"]["parameters"],
            "execution": _data(invoke)["definition"]["function"]["parameters"],
        },
        executed == 200
        and again == 200
        and match["function"]["parameters"]
        == _data(invoke)["definition"]["function"]["parameters"],
    )
    outcomes: dict[int, list] = {1: [], 2: []}

    def _worker(tenant: int) -> None:
        with tenant_scope(tenant):
            actor = Actor("admin-1", "admin", None, tenant)
            outcomes[tenant].append(
                service.create_tool(
                    actor,
                    _base_body(f"concurrent_{tenant}", description="concurrent", name="concurrent"),
                )
            )

    threads = [threading.Thread(target=_worker, args=(tenant,)) for tenant in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    with tenant_scope(1):
        own = service.list_tools(Actor("admin-1", "admin", None, 1), {"q": "concurrent_"})
    with tenant_scope(2):
        theirs = service.list_tools(Actor("admin-1", "admin", None, 2), {"q": "concurrent_"})
    suite.record(
        "AS08",
        {"tenants": [1, 2]},
        {
            "tenant1": [item["tool_key"] for item in own["items"]],
            "tenant2": [item["tool_key"] for item in theirs["items"]],
        },
        [item["tool_key"] for item in own["items"]] == ["concurrent_1"]
        and [item["tool_key"] for item in theirs["items"]] == ["concurrent_2"]
        and outcomes[1][0]["tenant_id"] == 1
        and outcomes[2][0]["tenant_id"] == 2,
    )
    suite.call("GET", "/api/agent-tools/discovery", role="employee", actor="emp-a", tenant=1)
    suite.call(
        "POST",
        "/api/agent-tools/employees",
        body={"principal_id": "emp-a", "role": "employee"},
        tenant=2,
    )
    switched, other = suite.call(
        "GET", "/api/agent-tools/discovery", role="employee", actor="emp-a", tenant=2
    )
    blob = json.dumps(other, ensure_ascii=False)
    suite.record(
        "AS09",
        {"from_tenant": 1, "to_tenant": 2},
        {"status": switched, "body": other},
        switched == 200 and (_data(other).get("tools") or []) == [],
        "switching the authorized tenant drops the previous tenant catalog",
    )
    previous = os.environ.get("XCAGI_AGENT_TOOL_HEADER_AUTH")
    os.environ["XCAGI_AGENT_TOOL_HEADER_AUTH"] = "0"
    try:
        denied, denied_body = suite.call(
            "POST", "/api/agent-tools", body=_base_body("header_admin_should_fail")
        )
    finally:
        if previous is None:
            os.environ.pop("XCAGI_AGENT_TOOL_HEADER_AUTH", None)
        else:
            os.environ["XCAGI_AGENT_TOOL_HEADER_AUTH"] = previous
    suite.record(
        "AS10",
        {"header_role": "admin", "header_auth": False},
        {"status": denied, "body": denied_body},
        denied == 401 and _err(denied_body).get("code") == "auth_required",
    )


def _section_ap(suite: Suite) -> None:
    def measure(action: Any, rounds: int = 30) -> float:
        samples = []
        for _ in range(rounds):
            started = time.perf_counter()
            action()
            samples.append(time.perf_counter() - started)
        return _p95(samples)

    counter = {"n": 0}

    def _create() -> None:
        counter["n"] += 1
        status, payload = suite.call(
            "POST", "/api/agent-tools", body=_base_body(f"perf_{counter['n']:04d}")
        )
        if status != 201:
            raise AssertionError(payload)

    create_p95 = measure(_create)
    suite.record(
        "AP01",
        {"rounds": 30},
        {"p95_seconds": create_p95},
        create_p95 <= 1.0,
        f"p95={create_p95:.4f}s",
    )
    status, created = suite.call("POST", "/api/agent-tools", body=_base_body("perf_update"))
    version = {"no": _data(created)["version_no"]}

    def _update() -> None:
        result, payload = suite.call(
            "PUT",
            f"/api/agent-tools/{_data(created)['id']}",
            body={"expected_version": version["no"], "description": f"perf {version['no']}"},
        )
        if result != 200:
            raise AssertionError(payload)
        version["no"] = _data(payload)["version_no"]

    update_p95 = measure(_update, 20)
    suite.record(
        "AP02",
        {"rounds": 20},
        {"p95_seconds": update_p95},
        update_p95 <= 1.0,
        f"p95={update_p95:.4f}s",
    )
    discover_p95 = measure(
        lambda: suite.call("GET", "/api/agent-tools/discovery", role="employee", actor="emp-a")
    )
    suite.record(
        "AP03",
        {"rounds": 30},
        {"p95_seconds": discover_p95},
        discover_p95 <= 1.0,
        f"p95={discover_p95:.4f}s",
    )
    search_p95 = measure(
        lambda: suite.call("GET", "/api/agent-tools", params={"q": "perf_", "page_size": 20})
    )
    suite.record(
        "AP04",
        {"rounds": 30},
        {"p95_seconds": search_p95},
        search_p95 <= 1.0,
        f"p95={search_p95:.4f}s",
    )
    suite.call("POST", f"/api/agent-tools/{_data(created)['id']}/publish", body={"scope": "tenant"})
    invoke_p95 = measure(
        lambda: suite.call(
            "POST",
            f"/api/agent-tools/{_data(created)['id']}/invoke",
            role="employee",
            actor="emp-a",
            body={"arguments": {"name": "perf"}},
        )
    )
    suite.record(
        "AP05",
        {"rounds": 30},
        {"p95_seconds": invoke_p95},
        invoke_p95 <= 1.0,
        f"p95={invoke_p95:.4f}s",
    )
    page_p95 = measure(
        lambda: suite.call(
            "GET", "/api/agent-tools", params={"q": "perf_", "page": 2, "page_size": 10}
        )
    )
    suite.record(
        "AP06",
        {"page": 2, "page_size": 10},
        {"p95_seconds": page_p95},
        page_p95 <= 1.0,
        f"p95={page_p95:.4f}s",
    )
    _create()
    started = time.perf_counter()
    threads = []
    errors: list[str] = []

    def _concurrent(index: int) -> None:
        try:
            with tenant_scope(1):
                service.create_tool(
                    Actor("admin-1", "admin", None, 1),
                    _base_body(f"concurrent_reg_{index:03d}"),
                )
        except BOUNDARY_ERRORS as exc:
            errors.append(f"{type(exc).__name__}: {exc}")

    for index in range(12):
        thread = threading.Thread(target=_concurrent, args=(index,))
        threads.append(thread)
        thread.start()
    for thread in threads:
        thread.join()
    elapsed = time.perf_counter() - started
    suite.record(
        "AP07",
        {"threads": 12},
        {"elapsed_seconds": elapsed, "errors": errors},
        elapsed <= 1.0 and not errors,
        f"elapsed={elapsed:.4f}s",
    )
