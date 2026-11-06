"""A09–A18 tool-turn acceptance: real handler execution, not model JSON."""

from __future__ import annotations

import time
from datetime import date

from app.application.agent_orchestrator.tool_spec import (
    validate_schema_object,
    validate_tool_spec_fixtures,
)
from app.application.workflow.tool_turn_catalog import acceptance_tools, plan_graph_for_registry
from app.application.workflow.tool_turn_runtime import (
    ToolDef,
    TurnState,
    execute_turn,
)

TODAY = date(2026, 11, 6)
PERMS = {item for tool in acceptance_tools() for item in tool.permissions}


def _handlers(calls: list[str], payloads: dict | None = None):
    payloads = payloads or {}

    def make(name: str):
        def handler(arguments, context):
            calls.append(name)
            return {"success": True, **payloads.get(name, {"count": 1})}

        return handler

    return {tool.name: make(tool.name) for tool in acceptance_tools()}


def _run(message: str, state: TurnState | None = None, **kwargs):
    calls: list[str] = []
    result = execute_turn(
        message,
        tools=kwargs.pop("tools", acceptance_tools()),
        handlers=kwargs.pop("handlers", _handlers(calls, kwargs.pop("payloads", None))),
        state=state or TurnState(),
        permissions=kwargs.pop("permissions", set(PERMS)),
        today=kwargs.pop("today", TODAY),
        task_id="task-1",
        conversation_id="conv-1",
        employee_id="emp-1",
        **kwargs,
    )
    return result, calls


def test_order_followup_keeps_scope_and_runs_tools():
    state = TurnState()
    payloads = {
        "query_orders": {"total": 125, "paid": 100, "unpaid": 25, "amount": 156800.50},
        "export_excel": {"file": "orders.xlsx"},
        "sales_stats": {"amount": 156800.50, "total": 125},
    }
    calls: list[str] = []
    handlers = _handlers(calls, payloads)
    first, _ = _run("帮我查一下今天的订单数量。", state, handlers=handlers, payloads=payloads)
    assert first["evidence"][0]["tool_name"] == "query_orders"
    assert first["evidence"][0]["arguments"]["start_date"] == "2026-11-06"
    assert first["evidence"][0]["execution_status"] == "success"
    second, _ = _run("把今天未付款的订单筛选出来。", state, handlers=handlers)
    assert second["evidence"][0]["arguments"]["status"] == "unpaid"
    assert second["evidence"][0]["arguments"]["start_date"] == "2026-11-06"
    third, _ = _run("把这些订单导出成 Excel。", state, handlers=handlers)
    exported = third["evidence"][0]
    assert exported["tool_name"] == "export_excel"
    assert exported["arguments"]["status"] == "unpaid"
    assert exported["arguments"]["start_date"] == "2026-11-06"
    fourth, _ = _run("顺便统计一下总金额。", state, handlers=handlers)
    assert fourth["evidence"][0]["tool_name"] == "sales_stats"
    assert fourth["evidence"][0]["arguments"]["status"] == "unpaid"
    assert "156800.5" in fourth["final_response"]
    assert calls[0] == "query_orders"


def test_compound_query_export_skips_unrelated_writes():
    result, calls = _run("帮我查询今天的订单，并导出 Excel。")
    assert calls == ["query_orders", "export_excel"]
    assert result["ok"] is True
    assert "create_order" not in calls and "delete_order" not in calls


def test_chitchat_and_negation_do_not_call_tools():
    for message in ("什么是订单？", "解释一下库存周转概念", "不要查订单"):
        result, calls = _run(message)
        assert calls == []
        assert result["executed"] is False


def test_implicit_query_and_ambiguous_high_risk():
    found, calls = _run("今天有没有未付款的订单")
    assert calls == ["query_orders"]
    assert found["evidence"][0]["arguments"]["status"] == "unpaid"
    blocked, writes = _run("把订单处理一下")
    assert writes == []
    assert "不会直接执行" in blocked["final_response"] or "请补充" in blocked["final_response"]


def test_goal_change_drops_previous_order_target():
    state = TurnState()
    _run("帮我查一下今天的订单数量。", state)
    changed, calls = _run("算了，改查客户数量", state)
    assert calls == ["query_customers"]
    assert state.filters == {} or "status" not in state.filters


def test_parameter_extraction_keeps_exclusive_amount():
    result, calls = _run("帮我查一下 11 月 1 日到 11 月 5 日，成都地区，金额超过 5000 元的未付款订单。")
    arguments = result["evidence"][0]["arguments"]
    assert arguments == {
        "start_date": "2026-11-01",
        "end_date": "2026-11-05",
        "region": "成都",
        "min_amount_exclusive": 5000,
        "status": "unpaid",
    }
    assert calls == ["query_orders"]


def test_inverted_dates_do_not_execute():
    result, calls = _run("帮我查一下 11 月 5 日到 11 月 1 日的订单。")
    assert calls == []
    assert result["evidence"][0]["execution_status"] == "rejected"


def test_missing_required_blocks_until_customer_is_supplied():
    calls: list[str] = []
    state = TurnState()
    handlers = _handlers(calls)
    first, _ = _run("帮我创建一个订单，金额 5000 元。", state, handlers=handlers)
    assert calls == []
    assert first["evidence"][0]["execution_status"] == "rejected"
    assert "customer_id" in first["evidence"][0]["error"]
    second, _ = _run("客户是 C-9", state, handlers=handlers)
    assert calls == ["create_order"]
    assert second["evidence"][0]["arguments"]["customer_id"] == "C-9"
    assert second["evidence"][0]["arguments"]["amount"] == 5000


def test_schema_constraints_reject_illegal_values():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["customer_id", "amount"],
        "dependentRequired": {"notify": ["email"]},
        "properties": {
            "customer_id": {"type": "string", "minLength": 1},
            "amount": {"type": "number", "exclusiveMinimum": 0, "maximum": 1000},
            "status": {"type": "string", "enum": ["paid", "unpaid"]},
            "email": {"type": "string", "format": "email"},
            "phone": {"type": "string", "format": "phone"},
            "notify": {"type": "boolean"},
            "remark": {"type": "string", "maxLength": 4},
        },
    }
    ok, message = validate_schema_object(schema, {"customer_id": "C-1", "amount": 1000, "extra": 1})
    assert not ok and "extra" in message
    ok, message = validate_schema_object(schema, {"customer_id": "C-1", "amount": 1001})
    assert not ok and "1000" in message
    ok, message = validate_schema_object(schema, {"customer_id": "C-1", "amount": 0})
    assert not ok and "大于" in message
    ok, message = validate_schema_object(schema, {"customer_id": "C-1", "amount": 1, "status": "draft"})
    assert not ok and "允许范围" in message
    ok, message = validate_schema_object(schema, {"customer_id": "C-1", "amount": 1, "remark": "12345"})
    assert not ok and "长度" in message
    ok, message = validate_schema_object(schema, {"customer_id": "C-1", "amount": 1, "email": "bad"})
    assert not ok and "邮箱" in message
    ok, message = validate_schema_object(schema, {"customer_id": "C-1", "amount": 1, "phone": "123"})
    assert not ok and "手机号" in message
    ok, message = validate_schema_object(schema, {"customer_id": "C-1", "amount": 1, "notify": True})
    assert not ok and "email" in message
    ok, _message = validate_schema_object(
        schema, {"customer_id": "C-1", "amount": 1.5, "email": "a@b.co", "phone": "13800138000"}
    )
    assert ok
    assert validate_tool_spec_fixtures() == {}


def test_employee_types_do_not_invent_department_ids():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["employee_name", "age", "salary", "enabled", "department_ids", "start_date"],
        "properties": {
            "employee_name": {"type": "string"},
            "age": {"type": "integer", "minimum": 0, "maximum": 120},
            "salary": {"type": "number"},
            "enabled": {"type": "boolean"},
            "department_ids": {"type": "array", "items": {"type": "string"}},
            "start_date": {"type": "string", "format": "date"},
        },
    }
    tool = ToolDef("create_employee", "新增员工", schema, permissions=("hr.write",), triggers=("员工",))
    message = "新增员工张三，28 岁，工资 8500.50，启用账号，加入技术部和产品部，从 2026 年 11 月 6 日开始。"
    arguments = __import__(
        "app.application.workflow.tool_turn_runtime", fromlist=["extract_arguments"]
    ).extract_arguments(message, tool, TurnState(), today=TODAY)
    assert arguments["age"] == 28 and isinstance(arguments["age"], int)
    assert arguments["salary"] == 8500.50
    assert arguments["enabled"] is True
    assert arguments["department_ids"] == ["技术部", "产品部"]
    assert arguments["start_date"] == "2026-11-06"
    ok, _message = validate_schema_object(schema, arguments)
    assert ok
    id_schema = {
        **schema,
        "properties": {
            **schema["properties"],
            "department_ids": {"type": "array", "items": {"type": "integer"}},
        },
    }
    id_tool = ToolDef("create_employee", "新增员工", id_schema, triggers=("员工",))
    id_args = __import__(
        "app.application.workflow.tool_turn_runtime", fromlist=["extract_arguments"]
    ).extract_arguments(message, id_tool, TurnState(), today=TODAY)
    assert "department_ids" not in id_args
    assert "技术部" not in str(id_args)


def test_nested_lines_keep_integer_quantities():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["order_id", "lines"],
        "properties": {
            "order_id": {"type": "string"},
            "lines": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["sku", "qty"],
                    "properties": {"sku": {"type": "string"}, "qty": {"type": "integer", "minimum": 1}},
                },
            },
        },
    }
    ok, _message = validate_schema_object(
        schema, {"order_id": "SO-9", "lines": [{"sku": "SKU-A", "qty": 2}, {"sku": "SKU-B", "qty": 3}]}
    )
    assert ok
    bad, message = validate_schema_object(schema, {"order_id": "SO-9", "lines": [{"sku": "SKU-A", "qty": "2"}]})
    assert not bad and "qty" in message


def test_serial_chain_passes_previous_result_and_stops_on_failure():
    result, calls = _run("查询今天的销售订单，统计销售总额，按照客户分类，最后生成 Excel 报表。")
    assert calls == ["query_orders", "sales_stats", "customer_group", "export_excel"]
    assert result["evidence"][-1]["arguments"]["source_step"].endswith("customer_group")

    calls = []

    def fail_stats(arguments, context):
        calls.append("sales_stats")
        return {"success": False, "error": "统计失败"}

    handlers = _handlers(calls)
    handlers["sales_stats"] = fail_stats
    failed, _ = _run(
        "查询今天的销售订单，统计销售总额，按照客户分类，最后生成 Excel 报表。",
        handlers=handlers,
    )
    assert "export_excel" not in calls
    assert failed["ok"] is False
    assert "未全部完成" in failed["final_response"]
    assert failed["evidence"][0]["execution_status"] == "success"


def test_parallel_queries_collect_every_result_and_isolate_timeout():
    calls: list[str] = []
    started: dict[str, float] = {}

    def make(name: str):
        def handler(arguments, context):
            started[name] = time.monotonic()
            time.sleep(0.12)
            calls.append(name)
            return {"success": True, "total": {"query_orders": 3, "query_customers": 8, "query_inventory": 5}[name]}

        return handler

    tools = [tool for tool in acceptance_tools() if tool.name.startswith("query_")]
    handlers = {tool.name: make(tool.name) for tool in tools}
    began = time.monotonic()
    result, _ = _run("帮我同时查询今天的订单、客户数量和库存情况。", tools=tools, handlers=handlers)
    elapsed = time.monotonic() - began
    assert set(calls) == {"query_orders", "query_customers", "query_inventory"}
    assert elapsed < 0.3
    assert "total" in result["final_response"]
    slow_calls: list[str] = []

    def slow(arguments, context):
        time.sleep(0.4)
        slow_calls.append("query_inventory")
        return {"success": True, "total": 1}

    handlers = {name: (lambda arguments, context, name=name: {"success": True, "total": 1}) for name in ("query_orders", "query_customers")}
    handlers["query_inventory"] = slow
    mixed, _ = _run(
        "帮我同时查询今天的订单、客户数量和库存情况。",
        tools=tools,
        handlers=handlers,
        timeout_sec=0.05,
        max_workers=2,
    )
    statuses = {row["tool_name"]: row["execution_status"] for row in mixed["evidence"]}
    assert statuses["query_inventory"] == "failed"
    assert statuses["query_orders"] == "success"
    assert statuses["query_customers"] == "success"
    assert mixed["ok"] is False
    assert slow_calls == [] or statuses["query_inventory"] == "failed"


def test_parallel_limit_and_result_conflict():
    inflight = {"now": 0, "peak": 0}

    def make(name: str):
        def handler(arguments, context):
            inflight["now"] += 1
            inflight["peak"] = max(inflight["peak"], inflight["now"])
            time.sleep(0.05)
            inflight["now"] -= 1
            total = 100 if name == "query_orders" else 90
            return {"success": True, "total": total, "amount": 100000 if name == "query_orders" else 100000}

        return handler

    tools = [tool for tool in acceptance_tools() if tool.name in {"query_orders", "sales_stats"}]
    result, _calls = _run(
        "查询今天的销售订单，统计销售总额。",
        tools=tools + [tool for tool in acceptance_tools() if tool.name == "customer_group"],
        handlers={
            "query_orders": make("query_orders"),
            "sales_stats": make("sales_stats"),
            "customer_group": make("customer_group"),
        },
        max_workers=1,
    )
    assert "数据冲突" in result["final_response"]
    assert "100000" in result["final_response"]


def test_permission_version_and_unavailable_tools():
    tools = acceptance_tools()
    offline = [
        ToolDef(
            "query_orders",
            "旧订单查询",
            tools[0].schema,
            version="0.9.0",
            status="offline",
            permissions=("orders.read",),
            triggers=("订单",),
        ),
        ToolDef(
            "query_orders",
            "订单查询",
            tools[0].schema,
            version="2.0.0",
            permissions=("orders.read",),
            triggers=("订单",),
        ),
    ]
    result, calls = _run("帮我查一下今天的订单数量。", tools=offline)
    assert calls == ["query_orders"]
    assert result["evidence"][0]["tool_version"] == "2.0.0"
    denied, writes = _run("删除订单，编号 SO-9", permissions={"orders.read"})
    assert writes == []
    assert denied["executed"] is False


def test_retry_stops_and_timeout_after_commit_is_not_duplicated():
    attempts = {"count": 0}

    def flaky(arguments, context):
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise TimeoutError("temporary")
        return {"success": True, "total": 1}

    handlers = _handlers([])
    handlers["query_orders"] = flaky
    result, _calls = _run("帮我查一下今天的订单数量。", handlers=handlers, timeout_sec=1)
    assert result["ok"] is True
    assert result["evidence"][0]["retry_count"] == 1
    assert attempts["count"] == 2

    created: list[str] = []

    def create_customer(arguments, context):
        created.append(arguments["name"])
        context.mark_committed({"success": True, "id": "cust-1", "name": arguments["name"]})
        raise TimeoutError("response lost")

    handlers = _handlers([])
    handlers["create_customer"] = create_customer
    state = TurnState()
    done, _calls = _run("帮我创建一个客户档案，名字张三。", state, handlers=handlers)
    assert done["ok"] is True
    assert done["evidence"][0]["result"]["id"] == "cust-1"
    again, _calls = _run("帮我创建一个客户档案，名字张三。", state, handlers=handlers)
    assert again["ok"] is True
    assert created == ["张三"]


def test_secret_arguments_are_redacted_and_evidence_is_complete():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"api_key": {"type": "string"}, "keyword": {"type": "string"}},
    }
    tool = ToolDef("query_orders", "查询订单", schema, permissions=("orders.read",), triggers=("订单",))

    def handler(arguments, context):
        return {"success": True, "total": 1, "api_key": arguments.get("api_key", "")}

    state = TurnState(filters={"api_key": "sk-live"})
    result = execute_turn(
        "帮我查一下今天的订单数量。",
        tools=[tool],
        handlers={"query_orders": handler},
        state=state,
        permissions={"orders.read"},
        today=TODAY,
        task_id="task-9",
        conversation_id="conv-9",
        employee_id="emp-9",
    )
    row = result["evidence"][0]
    for key in (
        "task_id",
        "conversation_id",
        "employee_id",
        "tool_id",
        "tool_version",
        "intent",
        "tool_name",
        "arguments",
        "validation_result",
        "execution_status",
        "started_at",
        "finished_at",
        "retry_count",
        "result",
        "error",
    ):
        assert key in row
    assert result["final_response"]
    assert "sk-live" not in str(row)
    assert state is not None


def test_registered_plan_uses_real_tool_ids_without_extra_writes():
    registry = {name: {"actions": {"query": {}, "execute": {}}} for name in ("query_orders", "export_excel", "create_order", "delete_order")}
    plan = plan_graph_for_registry("plan-1", "帮我查询今天的订单，并导出 Excel。", registry, today=TODAY)
    assert plan is not None
    assert [node.tool_id for node in plan.nodes] == ["query_orders", "export_excel"]
    assert plan.nodes[1].depends_on
    missing = plan_graph_for_registry("plan-2", "什么是订单", registry, today=TODAY)
    assert missing is None


def test_intent_samples_cover_acceptance_floor():
    labeled = []
    for index in range(50):
        labeled.append((f"帮我查一下客户{index}的订单", True))
        labeled.append((f"什么是指标{index}", False))
    labeled.extend(
        [
            ("不要导出订单", False),
            ("把这些都处理一下", False),
            ("今天有没有库存", True),
        ]
    )
    hits = 0
    misses = []
    for message, expects_tool in labeled:
        result, calls = _run(message)
        got = bool(calls) or any(row["execution_status"] == "rejected" for row in result["evidence"])
        if expects_tool == got:
            hits += 1
        elif len(misses) < 5:
            misses.append((message, expects_tool, got, calls, result["intent"]["intent"]))
    assert hits / len(labeled) >= 0.95, misses
    same = [
        _run("帮我查询今天的订单，并导出 Excel。")[1]
        for _ in range(20)
    ]
    assert all(item == ["query_orders", "export_excel"] for item in same)
