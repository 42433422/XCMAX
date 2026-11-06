"""Employee discovery, tenant isolation, security, and latency acceptance checks."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from app.application import agent_tool_lifecycle as service
from app.application.agent_tool_lifecycle import Actor
from app.infrastructure.tenant_scope import tenant_scope
from app.utils.operational_errors import BOUNDARY_ERRORS
from tests.fixtures.agent_tool_lifecycle_support import (
    SCHEMA,
    SECRET,
    Suite,
    _base_body,
    _data,
    _err,
    _p95,
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
