# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.workflow.planner")


def _first_onboarding_quoted_slot(text: str, prefixes: tuple[str, ...]) -> str | None:
    """Walk forward once, preserving the original first nonempty quoted match."""
    cursor = 0
    length = len(text)
    while cursor < length:
        prefix = next((value for value in prefixes if text.startswith(value, cursor)), None)
        if prefix is None:
            cursor += 1
            continue
        cursor += len(prefix)
        while cursor < length and text[cursor].isspace():
            cursor += 1
        if cursor == length or text[cursor] not in ("「", "“", '"', "'"):
            continue
        cursor += 1
        start = cursor
        # Any of these closing quotes ended the old match, including mixed styles.
        while cursor < length and text[cursor] not in ("」", "”", '"', "'"):
            cursor += 1
        if cursor == length:
            # No later candidate can close either; never restart over this suffix.
            return None
        if cursor > start:
            return text[start:cursor].strip()
        cursor += 1
    return None


def _onboarding_first_order_slots(message: str) -> tuple[str, str] | None:
    """Extract the two seeded records from the deterministic onboarding prompt."""
    text = str(message or "")
    if "新手第一单" not in text or "演示出货单" not in text:
        return None
    customer = _first_onboarding_quoted_slot(text, ("查询客户",))
    product = _first_onboarding_quoted_slot(text, ("查询商品", "查询产品"))
    return (customer, product) if customer and product else None


class _LLMWorkflowPlannerPart02Mixin:
    def _fallback_plan(
        self, plan_id: str, message: str, tool_registry: dict[str, _facade().Any]
    ) -> _facade().PlanGraph:
        from .no_operation import no_operation_plan

        no_operation = no_operation_plan(plan_id, message)
        if no_operation is not None:
            return no_operation
        from app.application.normal_chat_dispatch import route_normal_mode_message

        lower = (message or "").lower()
        nodes: list[_facade().WorkflowNode] = []
        todo = ["理解用户目标", "执行可用工具", "输出执行结果"]
        intent = "generic_workflow"
        first_order_slots = _onboarding_first_order_slots(message)
        if first_order_slots and "business_db" in tool_registry:
            customer, product = first_order_slots
            intent = "onboarding_first_order"
            todo = ["查询演示客户", "查询演示商品", "确认后创建演示出货单"]
            nodes.extend(
                [
                    _facade().WorkflowNode(
                        node_id="find_onboarding_customer",
                        tool_id="business_db",
                        action="read",
                        params={"entity": "customers", "keyword": customer},
                        risk="low",
                        description=f"查询客户 {customer}",
                        idempotent=True,
                    ),
                    _facade().WorkflowNode(
                        node_id="find_onboarding_product",
                        tool_id="business_db",
                        action="read",
                        params={"entity": "products", "keyword": product},
                        risk="low",
                        description=f"查询商品 {product}",
                        idempotent=True,
                        depends_on=["find_onboarding_customer"],
                    ),
                    _facade().WorkflowNode(
                        node_id="create_onboarding_first_order",
                        tool_id="business_db",
                        action="write",
                        params={
                            "entity": "shipment_records",
                            "operation": "create",
                            "payload": {
                                "unit_name": customer,
                                "products": [
                                    {
                                        "product_name": product,
                                        "name": product,
                                        "quantity_tins": 1,
                                    }
                                ],
                            },
                        },
                        risk="medium",
                        description=f"为 {customer} 创建首张演示出货单",
                        idempotent=False,
                        depends_on=["find_onboarding_product"],
                    ),
                ]
            )
        if (
            not nodes
            and any(k in message for k in ("员工", "employee", "调用", "交给"))
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
        if not nodes and "inventory" in tool_registry:
            from .inventory_stock_in_planning import (
                inventory_stock_in_nodes,
                inventory_stock_out_nodes,
            )

            stock_in_nodes = inventory_stock_in_nodes(message)
            if stock_in_nodes:
                intent = "inventory_stock_in"
                todo = ["核对入库产品与仓库", "确认后执行库存入库", "返回入库结果"]
                nodes.extend(stock_in_nodes)
            else:
                stock_out_nodes = inventory_stock_out_nodes(message)
                if stock_out_nodes:
                    intent = "inventory_stock_out"
                    todo = ["核对出库产品与仓库", "确认后执行库存出库", "返回出库结果"]
                    nodes.extend(stock_out_nodes)
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
        if (
            not nodes
            and "sales" in tool_registry
            and "confirm_from_result" in tool_registry["sales"].get("actions", {})
        ):
            from .sales_order_planning import sales_order_nodes

            order_nodes = sales_order_nodes(message)
            if order_nodes:
                intent = "sales_order"
                nodes.extend(order_nodes)
        if not nodes and "reports" in tool_registry:
            from .sales_report_planning import monthly_sales_export_nodes

            export_nodes = monthly_sales_export_nodes(message)
            if export_nodes:
                intent = "sales_report_export"
                nodes.extend(export_nodes)
        if not nodes and "reports" in tool_registry and "customers" in tool_registry:
            from .customer_export_planning import customer_export_nodes

            customer_export = customer_export_nodes(message)
            if customer_export:
                intent = "customer_export"
                todo = ["查询客户列表", "导出为 Excel", "返回下载结果"]
                nodes.extend(customer_export)
        if not nodes and ("reports" in tool_registry or "inventory" in tool_registry):
            from .inventory_query_planning import inventory_route

            if (inventory := inventory_route(message, tool_registry)) is not None:
                intent, todo, inventory_node = inventory
                nodes.append(inventory_node)
        if not nodes and "reports" in tool_registry:
            from .dashboard_planning import dashboard_query_node

            dashboard_node = dashboard_query_node(message)
            if dashboard_node is not None:
                intent = "dashboard_query"
                nodes.append(dashboard_node)
        if not nodes and "reports" in tool_registry:
            from .sales_report_planning import monthly_sales_report_node

            report_node = monthly_sales_report_node(message)
            if report_node is not None:
                intent = "sales_report"
                nodes.append(report_node)
        if not nodes and "reports" in tool_registry:
            from .sales_report_planning import sales_report_query_node

            bare_report_node = sales_report_query_node(message)
            if bare_report_node is not None:
                intent = "sales_report"
                nodes.append(bare_report_node)
        if not nodes and "sales" in tool_registry:
            from .sales_quote_planning import explicit_sales_quote_node

            quote_node = explicit_sales_quote_node(message)
            if quote_node is not None:
                intent = "sales_quote"
                nodes.append(quote_node)
        if not nodes and "sales" in tool_registry:
            from .sales_order_query_planning import sales_order_query_node

            order_query_node = sales_order_query_node(message)
            if order_query_node is not None:
                intent = "sales_order_query"
                nodes.append(order_query_node)
        if not nodes and "finance" in tool_registry:
            from .finance_query import monthly_ledger_node

            ledger_node = monthly_ledger_node(message)
            if ledger_node is not None:
                intent = "finance_ledger_query"
                nodes.append(ledger_node)
        if not nodes and "finance" in tool_registry:
            from .finance_creation import direct_finance_create_node

            finance_node = direct_finance_create_node(message)
            if finance_node is not None:
                intent = "finance_create_transaction"
                nodes.append(finance_node)
        if not nodes:
            from .domain_query_planning import domain_query_nodes

            if domain_route := domain_query_nodes(message, tool_registry):
                intent, todo, domain_nodes = domain_route
                nodes.extend(domain_nodes)
        if not nodes and "products" in tool_registry:
            from .product_creation import direct_product_create_node

            product_node = direct_product_create_node(message)
            if product_node is not None:
                intent = "create_product"
                todo = ["核对产品信息", "确认后创建产品", "返回创建结果"]
                nodes.append(product_node)
        if not nodes and (
            ("添加" in message or "新增" in message or "create" in lower) and "产品" in message
        ):
            if "产品到" in message.replace(" ", ""):
                # 「新增产品到X」：先确保单位存在，再创建产品并绑定。
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
            else:
                intent = "create_product"
                todo = ["补齐产品信息", "确认后新增产品", "返回执行结果"]
                if "products" in tool_registry:
                    nodes.append(
                        _facade().WorkflowNode(
                            node_id="create_product",
                            tool_id="products",
                            action="create",
                            params={},
                            risk="medium",
                            description="创建产品",
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
        if not nodes and "shipment_orders" in tool_registry:
            from .shipment_planning import shipment_plan_nodes

            shipment_nodes = shipment_plan_nodes(message)
            if shipment_nodes:
                intent = "shipment_generate"
                todo = ["核对发货客户与产品明细", "确认后生成发货单", "返回发货单结果"]
                nodes.extend(shipment_nodes)
        if not nodes and route.get("intent") == "customers_query":
            customer_spec = tool_registry.get("customers", {})
            actions = customer_spec.get("actions", {}) if isinstance(customer_spec, dict) else {}
            query = actions.get("query", {}) if isinstance(actions, dict) else {}
            if (
                isinstance(query, dict)
                and query.get("risk") == "low"
                and query.get("idempotent") is True
            ):
                slots = route.get("slots") or {}
                keyword = slots.get("keyword") if isinstance(slots, dict) else None
                if isinstance(keyword, str):
                    intent = "customers_query"
                    nodes.append(
                        _facade().WorkflowNode(
                            node_id="query_customers",
                            tool_id="customers",
                            action="query",
                            params={"keyword": keyword, "page": 1, "per_page": 50},
                            risk="low",
                            idempotent=True,
                            description="查询客户",
                        )
                    )
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
