"""Deterministic tool-turn runtime for intent, selection, arguments, and real execution.

The model is not asked to invent a tool-call JSON. A turn is accepted only after
the chosen tools run, their arguments pass schema checks, and the reply is built
from those results.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.application.agent_orchestrator.tool_spec import validate_schema_object

ToolHandler = Callable[[dict[str, Any], "ExecContext"], dict[str, Any]]
_SECRET_KEY = re.compile(r"(api[_-]?key|token|password|secret|phone|mobile|email|id_card)", re.I)
_MAX_CALLS = 8
_MAX_RETRIES = 2


@dataclass
class ToolDef:
    name: str
    description: str
    schema: dict[str, Any]
    version: str = "1.0.0"
    status: str = "active"
    permissions: tuple[str, ...] = ()
    triggers: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    risk: str = "low"
    parallel_safe: bool = True


@dataclass
class ExecContext:
    tool_name: str
    idempotency_key: str
    attempt: int
    committed: dict[str, Any] | None = None

    def mark_committed(self, result: dict[str, Any]) -> None:
        self.committed = dict(result)


@dataclass
class TurnState:
    goal: str = ""
    filters: dict[str, Any] = field(default_factory=dict)
    pending_tool: str = ""
    pending_arguments: dict[str, Any] = field(default_factory=dict)
    committed: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class Step:
    step_id: str
    tool_name: str
    arguments: dict[str, Any]
    depends_on: tuple[str, ...] = ()
    parallel_group: str = ""
    when: dict[str, Any] | None = None
    version: str = "1.0.0"


def _version_key(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for item in str(value or "0").split("."):
        try:
            parts.append(int(item))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "***" if _SECRET_KEY.search(str(key)) else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def _today(today: date | None) -> date:
    return today or date.today()


def _shift_month(text: str, today: date) -> tuple[str, str] | None:
    match = re.search(
        r"(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*(?:到|至|—|-)\s*(?:(\d{1,2})\s*月\s*)?(\d{1,2})\s*日",
        text,
    )
    if not match:
        return None
    start_month = int(match.group(1))
    end_month = int(match.group(3) or start_month)
    start = date(today.year, start_month, int(match.group(2)))
    end = date(today.year, end_month, int(match.group(4)))
    return start.isoformat(), end.isoformat()


def _relative_dates(text: str, today: date) -> tuple[str, str] | None:
    ranged = _shift_month(text, today)
    if ranged:
        return ranged
    if "今天" in text:
        day = today.isoformat()
        return day, day
    if "昨天" in text:
        day = (today - timedelta(days=1)).isoformat()
        return day, day
    if "上周" in text:
        start = today - timedelta(days=today.weekday() + 7)
        end = start + timedelta(days=6)
        return start.isoformat(), end.isoformat()
    return None


def _amount_bound(text: str) -> dict[str, Any]:
    exclusive = re.search(r"(?:超过|大于|高于)(?!等于)\s*(\d+(?:\.\d+)?)", text)
    inclusive = re.search(r"(?:大于等于|不低于|至少|不少于)\s*(\d+(?:\.\d+)?)", text)
    if exclusive and not inclusive:
        return {"min_amount_exclusive": float(exclusive.group(1)) if "." in exclusive.group(1) else int(exclusive.group(1))}
    if inclusive:
        raw = inclusive.group(1)
        return {"min_amount": float(raw) if "." in raw else int(raw)}
    return {}


def _status(text: str) -> str:
    if "未付款" in text or "待付款" in text:
        return "unpaid"
    if "已付款" in text or "已支付" in text:
        return "paid"
    if "已取消" in text:
        return "cancelled"
    return ""


def _region(text: str) -> str:
    match = re.search(r"([\u4e00-\u9fff]{2,8})地区", text)
    return match.group(1) if match else ""


def classify_intent(message: str, state: TurnState | None = None) -> dict[str, Any]:
    """Return the turn intent. Ambiguous high-risk requests stay unexecuted."""
    text = str(message or "").strip()
    state = state or TurnState()
    negated = bool(re.search(r"(不要|别|勿|无需|不用).{0,8}(查|导出|删除|创建|统计|筛选)", text))
    knowledge = bool(re.search(r"(什么是|是什么意思|为什么|为何|解释一下|怎么理解|概念)", text))
    if negated or (knowledge and not re.search(r"(帮我|请).{0,6}(查|导出|删除|创建)", text)):
        return {"intent": "chitchat", "needs_tool": False, "subtasks": [], "clarify": ""}
    ambiguous = bool(re.search(r"(处理一下|搞一下|看着办|随便处理|那个东西)", text))
    high_risk = bool(re.search(r"(删除|清空|全部改|批量修改)", text))
    if ambiguous or (high_risk and not re.search(r"(订单号|客户号|编号)\s*[:：]?\s*[A-Za-z0-9-]{2,}", text)):
        if high_risk or "删除" in text or "修改" in text:
            return {
                "intent": "ambiguous",
                "needs_tool": False,
                "subtasks": [],
                "clarify": "请说明要操作的具体对象和编号，高风险操作不会直接执行。",
            }
        if not state.filters and not state.pending_tool:
            return {
                "intent": "ambiguous",
                "needs_tool": False,
                "subtasks": [],
                "clarify": "请补充要查询或办理的对象。",
            }
    if re.search(r"(算了|改查|改为查询|换成)", text):
        target = "customers" if "客户" in text else "orders" if "订单" in text else ""
        return {"intent": "goal_change", "needs_tool": bool(target), "subtasks": [target], "clarify": ""}
    subtasks: list[str] = []
    if re.search(r"(查|查询|有没有)", text) and re.search(r"(订单|客户|库存)", text):
        subtasks.append("query")
    if "筛选" in text or _status(text):
        subtasks.append("filter")
    if re.search(r"(统计|总额|总金额|平均)", text):
        subtasks.append("aggregate")
    if re.search(r"(分类|按客户)", text):
        subtasks.append("group")
    if re.search(r"(导出|Excel|表格)", text, re.I):
        subtasks.append("export")
    if re.search(r"(新增|创建)", text):
        subtasks.append("create")
    if "删除" in text and re.search(r"(订单号|编号)", text):
        subtasks.append("delete")
    if "同时" in text:
        for name, token in (("orders", "订单"), ("customers", "客户"), ("inventory", "库存")):
            if token in text:
                subtasks.append(name)
    intent = "chitchat"
    if len(subtasks) > 1:
        intent = "compound"
    elif subtasks == ["query"] or "有没有" in text:
        intent = "implicit_query" if "有没有" in text else "query"
    elif "filter" in subtasks:
        intent = "filter"
    elif "aggregate" in subtasks:
        intent = "aggregate"
    elif "export" in subtasks:
        intent = "export"
    elif "create" in subtasks or "delete" in subtasks:
        intent = "mutate"
    elif state.pending_tool or (state.filters and re.search(r"(这些|刚才|继续|客户是|编号是)", text)):
        intent = "continue"
    needs_tool = intent not in {"chitchat", "ambiguous"} and (bool(subtasks) or intent == "continue")
    return {"intent": intent, "needs_tool": needs_tool, "subtasks": subtasks, "clarify": ""}


def _active_tools(tools: list[ToolDef], permissions: set[str]) -> tuple[list[ToolDef], list[str]]:
    chosen: dict[str, ToolDef] = {}
    refused: list[str] = []
    for tool in tools:
        if tool.status != "active":
            refused.append(tool.name)
            continue
        if tool.permissions and "*" not in permissions and not set(tool.permissions) <= permissions:
            refused.append(tool.name)
            continue
        current = chosen.get(tool.name)
        if current is None or _version_key(tool.version) > _version_key(current.version):
            chosen[tool.name] = tool
    return list(chosen.values()), refused


def select_tools(
    message: str,
    assessment: Mapping[str, Any],
    tools: list[ToolDef],
    permissions: set[str],
    *,
    pending_tool: str = "",
) -> list[ToolDef]:
    if not assessment.get("needs_tool"):
        return []
    active, _refused = _active_tools(tools, permissions)
    subtasks = set(assessment.get("subtasks") or [])
    intent = str(assessment.get("intent") or "")
    wanted: list[str] = []
    if pending_tool and intent == "continue":
        wanted = [pending_tool]
    elif "同时" in message:
        if "订单" in message:
            wanted.append("query_orders")
        if "客户" in message:
            wanted.append("query_customers")
        if "库存" in message:
            wanted.append("query_inventory")
    else:
        if subtasks & {"query", "filter", "orders"} or intent in {"query", "implicit_query", "filter", "continue"}:
            if "客户" in message and "订单" not in message:
                wanted.append("query_customers")
            elif "库存" in message and "订单" not in message:
                wanted.append("query_inventory")
            else:
                wanted.append("query_orders")
        if "aggregate" in subtasks or "统计" in message:
            wanted.append("sales_stats")
        if "group" in subtasks:
            wanted.append("customer_group")
        if "export" in subtasks:
            wanted.append("export_excel")
        if "create" in subtasks:
            wanted.append("create_customer" if "客户" in message and "订单" not in message else "create_order")
        if "delete" in subtasks:
            wanted.append("delete_order")
        if intent == "goal_change" and "customers" in subtasks:
            wanted = ["query_customers"]
    by_name = {tool.name: tool for tool in active}
    selected: list[ToolDef] = []
    seen: set[str] = set()
    for name in wanted:
        tool = by_name.get(name)
        if tool is None or name in seen:
            continue
        if tool.triggers and not any(trigger in message or trigger in subtasks for trigger in tool.triggers):
            if name not in {"query_orders", "query_customers", "query_inventory", "sales_stats", "customer_group", "export_excel", "create_order", "create_customer", "delete_order"}:
                continue
        selected.append(tool)
        seen.add(name)
    if not wanted and not selected and intent not in {"chitchat", "ambiguous", "mutate"}:
        scored = []
        for tool in active:
            score = sum(1 for trigger in tool.triggers if trigger and trigger in message)
            if score:
                scored.append((score, tool))
        scored.sort(key=lambda item: (-item[0], item[1].name))
        if scored:
            selected.append(scored[0][1])
    return selected


def extract_arguments(
    message: str,
    tool: ToolDef,
    state: TurnState,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    current = _today(today)
    arguments = dict(state.pending_arguments if state.pending_tool == tool.name else {})
    if tool.name in {"query_orders", "sales_stats", "customer_group", "export_excel"}:
        arguments.update(state.filters)
    dates = _relative_dates(message, current)
    if dates:
        arguments["start_date"], arguments["end_date"] = dates
    region = _region(message)
    if region:
        arguments["region"] = region
    arguments.update(_amount_bound(message))
    status = _status(message)
    if status:
        arguments["status"] = status
    if re.search(r"(把|将).{0,8}金额.{0,8}改成\s*(\d+(?:\.\d+)?)", message):
        amount = re.search(r"改成\s*(\d+(?:\.\d+)?)", message)
        if amount:
            raw = amount.group(1)
            arguments["amount"] = float(raw) if "." in raw else int(raw)
    customer = re.search(r"客户(?:是|为|号)?\s*[:：]?\s*([A-Za-z0-9_-]{2,})", message)
    if customer and "customer_id" in (tool.schema.get("properties") or {}):
        arguments["customer_id"] = customer.group(1)
    amount_only = re.search(r"金额\s*(\d+(?:\.\d+)?)", message)
    if amount_only and "amount" in (tool.schema.get("properties") or {}) and "amount" not in arguments:
        raw = amount_only.group(1)
        arguments["amount"] = float(raw) if "." in raw else int(raw)
    order_no = re.search(r"(?:订单号|编号)\s*[:：]?\s*([A-Za-z0-9-]{2,})", message)
    if order_no and "order_id" in (tool.schema.get("properties") or {}):
        arguments["order_id"] = order_no.group(1)
    if tool.name == "create_customer":
        named = re.search(r"(?:名字|姓名|称为)\s*([\u4e00-\u9fff]{2,8})", message)
        if named:
            arguments["name"] = named.group(1)
    properties = tool.schema.get("properties") or {}
    if "employee_name" in properties:
        named = re.search(r"员工\s*([\u4e00-\u9fff]{2,8})", message)
        if named:
            arguments["employee_name"] = named.group(1)
        age = re.search(r"(\d{1,3})\s*岁", message)
        if age:
            arguments["age"] = int(age.group(1))
        salary = re.search(r"工资\s*(\d+(?:\.\d+)?)", message)
        if salary:
            arguments["salary"] = float(salary.group(1))
        if re.search(r"(启用|开启)", message):
            arguments["enabled"] = True
        if re.search(r"(停用|关闭)", message):
            arguments["enabled"] = False
        departments = re.search(r"加入(.+?)，", message)
        item_type = str(((properties.get("department_ids") or {}).get("items") or {}).get("type") or "")
        if departments and item_type == "string":
            arguments["department_ids"] = [part for part in re.split(r"[、和及]", departments.group(1)) if part]
        started = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", message)
        if started:
            arguments["start_date"] = date(int(started.group(1)), int(started.group(2)), int(started.group(3))).isoformat()
    if "lines" in properties:
        pairs = re.findall(r"(SKU-[A-Za-z0-9]+)\s*数量\s*(\d+)", message)
        if pairs:
            arguments["lines"] = [{"sku": sku, "qty": int(qty)} for sku, qty in pairs]
        order_id = re.search(r"订单\s*([A-Za-z0-9-]+)", message)
        if order_id:
            arguments["order_id"] = order_id.group(1)
    allowed = set(properties)
    return {key: value for key, value in arguments.items() if key in allowed and value not in ("", None, [], {})}


def _ordered_steps(message: str, tools: list[ToolDef], state: TurnState, *, today: date | None) -> list[Step]:
    parallel = "同时" in message
    steps: list[Step] = []
    previous = ""
    group = "parallel" if parallel else ""
    for index, tool in enumerate(tools, start=1):
        arguments = extract_arguments(message, tool, state, today=today)
        depends: tuple[str, ...] = ()
        if not parallel and previous:
            depends = (previous,)
            if tool.name == "export_excel":
                arguments = {**arguments, "source_step": previous}
        step_id = f"s{index}_{tool.name}"
        steps.append(
            Step(
                step_id=step_id,
                tool_name=tool.name,
                arguments=arguments,
                depends_on=depends,
                parallel_group=group,
                version=tool.version,
            )
        )
        previous = step_id
    return steps


def _evidence(
    *,
    task_id: str,
    conversation_id: str,
    employee_id: str,
    step: Step,
    validation: str,
    status: str,
    started: float,
    finished: float,
    retries: int,
    result: Any,
    error: str,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "conversation_id": conversation_id,
        "employee_id": employee_id,
        "tool_id": step.tool_name,
        "tool_version": step.version,
        "intent": "",
        "tool_name": step.tool_name,
        "arguments": redact(step.arguments),
        "validation_result": validation,
        "execution_status": status,
        "started_at": started,
        "finished_at": finished,
        "retry_count": retries,
        "result": redact(result),
        "error": error,
    }


def _invoke_handler(handler: ToolHandler, arguments: dict[str, Any], context: ExecContext, timeout_sec: float) -> dict[str, Any]:
    if timeout_sec <= 0:
        raise TimeoutError("工具执行超时")
    holder: dict[str, Any] = {}

    def target() -> None:
        try:
            holder["result"] = handler(arguments, context)
        except Exception as exc:  # noqa: BLE001 - returned to the turn runner
            holder["error"] = exc
        finally:
            holder["done"] = True

    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join(timeout_sec)
    if not holder.get("done"):
        raise TimeoutError("工具执行超时")
    if "error" in holder:
        raise holder["error"]
    result = holder.get("result")
    if not isinstance(result, dict):
        raise TypeError("工具返回必须是 JSON 对象")
    return result


def _run_handler(
    handler: ToolHandler,
    step: Step,
    state: TurnState,
    *,
    timeout_sec: float,
) -> tuple[dict[str, Any] | None, str, int, bool]:
    key = f"{step.tool_name}:{sorted(step.arguments.items())}"
    if key in state.committed and step.tool_name.startswith(("create", "delete")):
        return dict(state.committed[key]), "", 0, True
    retries = 0
    while True:
        context = ExecContext(tool_name=step.tool_name, idempotency_key=key, attempt=retries + 1)
        try:
            result = _invoke_handler(handler, dict(step.arguments), context, timeout_sec)
        except TimeoutError as exc:
            if context.committed is not None:
                state.committed[key] = dict(context.committed)
                return dict(context.committed), "", retries, True
            if retries >= _MAX_RETRIES:
                return None, str(exc), retries, False
            retries += 1
            continue
        except Exception as exc:  # noqa: BLE001 - tool failures stay inside the turn
            if retries >= _MAX_RETRIES:
                return None, str(exc), retries, False
            retries += 1
            continue
        if not isinstance(result, dict):
            return None, "工具返回必须是 JSON 对象", retries, False
        if result.get("success") is False or result.get("error"):
            return result, str(result.get("error") or "工具返回失败"), retries, False
        if step.tool_name.startswith(("create", "delete")):
            state.committed[key] = dict(result)
        return result, "", retries, True


def execute_turn(
    message: str,
    *,
    tools: list[ToolDef],
    handlers: Mapping[str, ToolHandler],
    state: TurnState | None = None,
    permissions: set[str] | None = None,
    employee_id: str = "employee",
    task_id: str = "task",
    conversation_id: str = "conversation",
    today: date | None = None,
    timeout_sec: float = 5.0,
    max_workers: int = 4,
    max_calls: int = _MAX_CALLS,
) -> dict[str, Any]:
    """Classify, validate, execute, and summarize one user turn."""
    state = state or TurnState()
    permissions = permissions if permissions is not None else {"*"}
    if "*" in permissions:
        permissions = {item for tool in tools for item in tool.permissions} | {"*"}
    assessment = classify_intent(message, state)
    if assessment["intent"] == "goal_change":
        state.filters.clear()
        state.pending_tool = ""
        state.pending_arguments.clear()
        state.goal = "customers" if "客户" in message else ""
    selected = select_tools(
        message, assessment, tools, permissions, pending_tool=state.pending_tool
    )
    allowed = {tool.name for tool in selected}
    blocked = [
        tool.name
        for tool in tools
        if tool.name not in allowed and (tool.permissions and not set(tool.permissions) <= permissions)
    ]
    if assessment.get("clarify") or (assessment["intent"] == "ambiguous"):
        return {
            "ok": True,
            "executed": False,
            "intent": assessment,
            "clarify": assessment.get("clarify") or "请补充具体对象。",
            "evidence": [],
            "final_response": assessment.get("clarify") or "请补充具体对象。",
            "blocked_tools": blocked,
        }
    if assessment.get("needs_tool") and not selected:
        return {
            "ok": False,
            "executed": False,
            "intent": assessment,
            "clarify": "没有可用工具能完成这个任务，未执行。",
            "evidence": [],
            "final_response": "没有可用工具能完成这个任务，未执行。",
            "blocked_tools": blocked,
        }
    if not assessment.get("needs_tool"):
        return {
            "ok": True,
            "executed": False,
            "intent": assessment,
            "clarify": "",
            "evidence": [],
            "final_response": "这是一般问题，不需要调用工具。",
            "blocked_tools": blocked,
        }
    steps = _ordered_steps(message, selected, state, today=today)
    if len(steps) > max_calls:
        steps = steps[:max_calls]
        truncated = True
    else:
        truncated = False
    evidence: list[dict[str, Any]] = []
    results: dict[str, dict[str, Any]] = {}
    failed = False

    def run_step(step: Step) -> dict[str, Any]:
        tool = next(item for item in selected if item.name == step.tool_name)
        ok, message_text = validate_schema_object(tool.schema, step.arguments)
        start_date = step.arguments.get("start_date")
        end_date = step.arguments.get("end_date")
        if ok and isinstance(start_date, str) and isinstance(end_date, str) and start_date > end_date:
            ok, message_text = False, "参数 开始日期不能晚于结束日期"
        started = time.monotonic()
        if not ok:
            state.pending_tool = step.tool_name
            state.pending_arguments = {
                key: value for key, value in step.arguments.items() if value not in ("", None)
            }
            row = _evidence(
                task_id=task_id,
                conversation_id=conversation_id,
                employee_id=employee_id,
                step=step,
                validation=message_text,
                status="rejected",
                started=started,
                finished=time.monotonic(),
                retries=0,
                result=None,
                error=message_text,
            )
            row["intent"] = assessment["intent"]
            return row
        if step.tool_name not in handlers:
            row = _evidence(
                task_id=task_id,
                conversation_id=conversation_id,
                employee_id=employee_id,
                step=step,
                validation="ok",
                status="missing_tool",
                started=started,
                finished=time.monotonic(),
                retries=0,
                result=None,
                error="工具不存在",
            )
            row["intent"] = assessment["intent"]
            return row
        result, error, retries, success = _run_handler(
            handlers[step.tool_name], step, state, timeout_sec=timeout_sec
        )
        row = _evidence(
            task_id=task_id,
            conversation_id=conversation_id,
            employee_id=employee_id,
            step=step,
            validation="ok",
            status="success" if success else "failed",
            started=started,
            finished=time.monotonic(),
            retries=retries,
            result=result,
            error=error,
        )
        row["intent"] = assessment["intent"]
        return row

    groups: list[list[Step]] = []
    for step in steps:
        if step.parallel_group and groups and groups[-1][0].parallel_group == step.parallel_group:
            groups[-1].append(step)
        else:
            groups.append([step])
    calls = 0
    for group in groups:
        if failed or calls >= max_calls:
            break
        runnable = []
        for step in group:
            dependency_ok = all(item in results and results[item].get("success") is not False for item in step.depends_on)
            if not dependency_ok:
                failed = True
                break
            runnable.append(step)
        if not runnable:
            break
        if len(runnable) == 1 or not runnable[0].parallel_group:
            for step in runnable:
                if calls >= max_calls:
                    truncated = True
                    break
                row = run_step(step)
                evidence.append(row)
                calls += 1
                if row["execution_status"] != "success":
                    failed = True
                    break
                results[step.step_id] = row["result"] or {}
            continue
        with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(runnable)))) as pool:
            futures = []
            for step in runnable:
                if calls >= max_calls:
                    truncated = True
                    break
                calls += 1
                futures.append(pool.submit(run_step, step))
            for future in as_completed(futures):
                row = future.result()
                evidence.append(row)
                if row["execution_status"] != "success":
                    failed = True
                else:
                    results[row["tool_name"]] = row["result"] or {}
    if selected and selected[0].name.startswith("query") and evidence and evidence[0]["execution_status"] == "success":
        state.filters = {
            key: value
            for key, value in evidence[0]["arguments"].items()
            if key in {"start_date", "end_date", "region", "status", "min_amount", "min_amount_exclusive"}
        }
        state.goal = selected[0].name
        state.pending_tool = ""
    summary = _summarize(evidence)
    if truncated:
        summary += " 已达到最大调用次数，未继续执行。"
    if failed:
        summary = (summary + " 任务未全部完成。").strip()
    return {
        "ok": not failed,
        "executed": any(row["execution_status"] == "success" for row in evidence),
        "intent": assessment,
        "evidence": evidence,
        "final_response": summary,
        "blocked_tools": blocked,
        "results": results,
    }


def _summarize(evidence: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    seen: dict[str, Any] = {}
    conflicts: list[str] = []
    for row in evidence:
        result = row.get("result") if isinstance(row.get("result"), dict) else {}
        if row["execution_status"] == "success":
            for key in ("total", "amount", "paid", "unpaid"):
                if key not in result:
                    continue
                if key in seen and seen[key] != result[key]:
                    conflicts.append(key)
                seen.setdefault(key, result[key])
    for row in evidence:
        result = row.get("result") if isinstance(row.get("result"), dict) else {}
        if row["execution_status"] != "success":
            lines.append(f"{row['tool_name']} 未成功：{row.get('error') or row['execution_status']}")
            continue
        kept = {
            key: result.get(key)
            for key in ("total", "paid", "unpaid", "amount", "customer_total", "new_customers", "average_amount", "count", "low_stock")
            if key in result
        }
        lines.append(f"{row['tool_name']}: {kept or result}")
    if conflicts:
        lines.append("数据冲突：" + "、".join(sorted(set(conflicts))) + "，未自行选择其中一个结果。")
    return "\n".join(lines) if lines else "未执行工具。"
