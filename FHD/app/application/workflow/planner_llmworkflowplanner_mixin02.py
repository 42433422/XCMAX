# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.workflow.planner")


class _LLMWorkflowPlannerPart02Mixin:
    def _fallback_plan(
        self, plan_id: str, message: str, tool_registry: dict[str, _facade().Any]
    ) -> _facade().PlanGraph:
        from app.application.normal_chat_dispatch import route_normal_mode_message

        lower = (message or "").lower()
        nodes: list[_facade().WorkflowNode] = []
        todo = ["理解用户目标", "执行可用工具", "输出执行结果"]
        intent = "generic_workflow"
        if (
            any(k in message for k in ("员工", "employee", "调用", "交给"))
            and "employee" in tool_registry
        ):
            intent = "employee_dispatch"
            todo = ["识别目标员工", "调用本机员工运行时", "返回员工执行结果"]
            employee_id = ""
            try:
                from app.mod_sdk.employee_tool_registry import build_employee_tools_status

                status = build_employee_tools_status()
                for item in status.get("employee_pack_tools") or []:
                    if not isinstance(item, dict):
                        continue
                    pid = str(item.get("pack_id") or "").strip()
                    if pid and pid in message:
                        employee_id = pid
                        break
            except (ImportError, RuntimeError):
                employee_id = ""
            if employee_id:
                nodes.append(
                    _facade().WorkflowNode(
                        node_id="run_employee",
                        tool_id="employee",
                        action="execute",
                        params={"employee_id": employee_id, "task": message},
                        risk="medium",
                        description=f"调用员工 {employee_id}",
                        idempotent=False,
                    )
                )
            else:
                nodes.append(
                    _facade().WorkflowNode(
                        node_id="list_employees",
                        tool_id="employee",
                        action="list",
                        params={},
                        risk="low",
                        description="列出可调用员工",
                        idempotent=True,
                    )
                )
        if (
            not nodes
            and _facade()._looks_like_business_db_write(message, lower)
            and ("business_db" in tool_registry)
        ):
            node = _facade()._extract_business_db_write_node(message)
            if node is not None:
                intent = "business_db_write"
                todo = ["识别业务实体与写入字段", "通过受控业务服务写入数据库", "返回写入结果"]
                nodes.append(node)
        route = route_normal_mode_message(message)
        if (
            not nodes
            and "sales" in tool_registry
            and (str(route.get("intent") or "") == "sales_write")
            and (str(route.get("action") or "") == "execute_closed_loop")
            and isinstance(route.get("payload"), dict)
            and bool(route.get("payload"))
        ):
            intent = "sales_write"
            todo = ["解析销售到收款闭环写载荷", "高风险审批后执行销售闭环", "返回执行结果"]
            nodes.append(
                _facade().WorkflowNode(
                    node_id="sales_execute_closed_loop",
                    tool_id="sales",
                    action="execute_closed_loop",
                    params={"payload": route["payload"]},
                    risk="high",
                    idempotent=True,
                    description="执行销售到收款闭环",
                )
            )
        if not nodes and (
            any(k in lower for k in ("db", "database"))
            or any(k in message for k in ("数据库", "查数据库", "读数据库"))
        ):
            if "business_db" in tool_registry:
                intent = "business_db_read"
                entity = _facade()._infer_business_db_entity(message)
                keyword = _facade()._extract_business_db_read_keyword(message, entity)
                nodes.append(
                    _facade().WorkflowNode(
                        node_id="read_business_db",
                        tool_id="business_db",
                        action="read",
                        params={"entity": entity, "keyword": keyword},
                        risk="low",
                        description="读取受控业务数据库",
                        idempotent=True,
                    )
                )
        if not nodes and (
            ("添加" in message or "新增" in message or "create" in lower) and "产品" in message
        ):
            intent = "add_product_to_unit"
            todo = [
                "意图分析：识别产品新增任务",
                "全局检查单位是否存在",
                "单位不存在则先创建",
                "新增产品并绑定单位",
                "返回执行明细",
            ]
            if "customers" in tool_registry:
                nodes.append(
                    _facade().WorkflowNode(
                        node_id="check_or_create_unit",
                        tool_id="customers",
                        action="ensure_exists",
                        params={},
                        risk="medium",
                        description="确保客户存在",
                    )
                )
            if "products" in tool_registry:
                nodes.append(
                    _facade().WorkflowNode(
                        node_id="create_product",
                        tool_id="products",
                        action="create",
                        params={},
                        risk="medium",
                        description="创建产品",
                        depends_on=["check_or_create_unit"] if nodes else [],
                    )
                )
        if not nodes and any(k in message for k in ("删除", "移除", "删掉", "delete", "del")):
            entity = _facade()._infer_business_db_entity(message)
            keyword = _facade()._extract_business_db_read_keyword(message, entity)
            intent = "business_db_read"
            todo = ["识别要删除的目标", "查询确认目标信息"]
            nodes.append(
                _facade().WorkflowNode(
                    node_id="query_for_delete",
                    tool_id="business_db",
                    action="read",
                    params={"entity": entity, "keyword": keyword},
                    risk="low",
                    description=f"查询要删除的{entity}",
                    idempotent=True,
                )
            )
        if (
            not nodes
            and any(k in message for k in ("库存", "stock", "Stock"))
            and any(k in message for k in ("采购", "购买", "补充", "备货", "进货"))
        ):
            intent = "inventory_purchase"
            todo = ["检查库存", "按 low_stock 决定是否采购", "输出采购建议"]
            purchase_node = _facade().WorkflowNode(
                node_id="purchase_advice",
                tool_id="purchase",
                action="advice",
                params={},
                risk="low",
                description="采购建议",
                idempotent=True,
                depends_on=["check_stock"],
            )
            nodes.append(
                _facade().WorkflowNode(
                    node_id="check_stock",
                    tool_id="inventory",
                    action="check_stock",
                    params={},
                    risk="low",
                    description="检查库存",
                    idempotent=True,
                    branches=[
                        _facade().Branch(
                            target="purchase_advice", condition={"key": "low_stock", "equals": True}
                        )
                    ],
                )
            )
            nodes.append(purchase_node)
        if not nodes:
            if "products" in tool_registry:
                nodes.append(
                    _facade().WorkflowNode(
                        node_id="query_products",
                        tool_id="products",
                        action="query",
                        params={"keyword": message},
                        risk="low",
                        description="查询相关产品",
                        idempotent=True,
                    )
                )
            elif "customers" in tool_registry:
                nodes.append(
                    _facade().WorkflowNode(
                        node_id="query_customers",
                        tool_id="customers",
                        action="query",
                        params={"keyword": message},
                        risk="low",
                        description="查询相关客户",
                        idempotent=True,
                    )
                )
        risk = "low"
        if any(node.risk == "high" for node in nodes):
            risk = "high"
        elif any(node.risk == "medium" for node in nodes):
            risk = "medium"
        plan = _facade().PlanGraph(
            plan_id=plan_id,
            intent=intent,
            todo_steps=todo,
            nodes=nodes,
            risk_level=_facade().normalize_workflow_risk(risk),
            metadata={"planner": "fallback", "message": message},
        )
        return self._apply_clarify_rules(
            self._apply_conditional_edge_rules(plan, message, tool_registry), tool_registry
        )
