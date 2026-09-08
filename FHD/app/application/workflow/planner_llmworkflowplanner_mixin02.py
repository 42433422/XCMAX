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


_RAW_SQL_RE = _facade().re.compile(
    r"\b(delete|drop|truncate|insert|update|alter)\b[^。；;]{0,60}\b(from|into|table|database)\b",
    _facade().re.I,
)

_PRODUCT_QUANTIFIERS = ("一个", "一款", "一种", "这个", "那个", "某个")


def _looks_like_raw_sql_request(message: str) -> bool:
    """Detect "在数据库里执行 DELETE FROM customers" style raw-SQL requests.

    Raw SQL must never enter a write plan; the planner refuses it outright and
    the user is pointed at the controlled business tools instead.
    """
    value = str(message or "")
    if not value:
        return False
    return bool(_RAW_SQL_RE.search(value))


def _domain_business_plan(
    message: str, route: dict[str, _facade().Any], tool_registry: dict[str, _facade().Any]
) -> tuple[str, list[str], list[_facade().WorkflowNode]] | None:
    """Route recognized business-domain requests to their own tools.

    Without this layer the terminal fallback sends *everything* (customer
    lists, quotes, ledgers, dashboards) to ``products.query`` — the cross-domain
    misrouting this method exists to fix. Returns ``(intent, todo, nodes)`` or
    ``None`` when no domain rule matches.
    """
    re_mod = _facade().re
    text = str(message or "")
    route_intent = str(route.get("intent") or "")
    wf = _facade().WorkflowNode

    # 1) Sales: quoting / ordering must not fall into the customer or product
    #    query path just because a customer name appears in the sentence.
    if "sales" in tool_registry and (
        route_intent == "sales_query"
        or any(k in text for k in ("报价", "报个价", "询价", "下订单", "下单"))
    ):
        seg = re_mod.search(r"[给为](?:客户)?([^，,。；\s]+?)(?:下订单|下单|报)", text)
        customer = seg.group(1) if seg else ""
        if customer.startswith("客户"):
            customer = customer[len("客户") :]
        customer = customer.split("的")[0].strip("，,。； ")
        model_m = re_mod.search(r"(?:产品|商品)\s*[:：]?\s*([A-Za-z0-9._-]+)", text)
        qty_m = re_mod.search(r"数量\s*[:：]?\s*(\d+(?:\.\d+)?)", text)
        items = [
            {
                "product_name": model_m.group(1) if model_m else "",
                "model_number": (model_m.group(1) if model_m else "").upper(),
                "quantity": float(qty_m.group(1)) if qty_m else 1,
            }
        ]
        return (
            "sales_quote",
            ["识别客户与产品明细", "生成销售报价单", "返回报价结果"],
            [
                wf(
                    node_id="sales_quote",
                    tool_id="sales",
                    action="quote",
                    params={"customer_name": customer, "items": items},
                    risk="medium",
                    description=f"为 {customer or '客户'} 报价",
                    idempotent=True,
                )
            ],
        )

    # 2) Finance: bookkeeping entries and ledger queries.
    if "finance" in tool_registry:
        if any(k in text for k in ("记一笔", "记一笔收入", "记一笔支出")):
            amount_m = re_mod.search(r"(\d+(?:\.\d+)?)\s*(?:元|块)", text)
            txn_type = "expense" if "支出" in text else "income"
            party_m = re_mod.search(r"(?:来自|付给|给)\s*([^\s，,。；]+)", text)
            params: dict[str, _facade().Any] = {
                "transaction_type": txn_type,
                "amount": float(amount_m.group(1)) if amount_m else 0.0,
                "description": text,
            }
            if party_m:
                params["counterparty_name"] = party_m.group(1)
            return (
                "finance_transaction",
                ["识别收支类型与金额", "创建财务凭证", "返回记账结果"],
                [
                    wf(
                        node_id="create_finance_transaction",
                        tool_id="finance",
                        action="create_transaction",
                        params=params,
                        risk="high",
                        description="记一笔财务收支",
                        idempotent=False,
                    )
                ],
            )
        if route_intent == "finance_query" or any(
            k in text for k in ("账本", "总账", "对账", "流水")
        ):
            return (
                "finance_ledger",
                ["确定账本查询范围", "查询总账", "返回账本结果"],
                [
                    wf(
                        node_id="query_finance_ledger",
                        tool_id="finance",
                        action="ledger_query",
                        params={},
                        risk="low",
                        description="查询财务账本",
                        idempotent=True,
                    )
                ],
            )

    # 3) Reports: dashboards, summaries and exports.
    if "reports" in tool_registry and (
        route_intent == "reports_query"
        or any(k in text for k in ("报表", "汇总", "看板", "统计"))
        or route_intent == "inventory_alert"
    ):
        if "看板" in text:
            return (
                "reports_dashboard",
                ["打开运营看板", "返回看板数据"],
                [
                    wf(
                        node_id="reports_dashboard",
                        tool_id="reports",
                        action="dashboard",
                        params={},
                        risk="low",
                        description="查看运营看板",
                        idempotent=True,
                    )
                ],
            )
        if "导出" in text:
            report_type = "inventory" if "库存" in text else (
                "purchase" if "采购" in text else "sales"
            )
            return (
                "reports_export",
                ["确定报表类型", "导出报表文件", "返回下载信息"],
                [
                    wf(
                        node_id="reports_export",
                        tool_id="reports",
                        action="export",
                        params={
                            "report_type": report_type,
                            "data": [],
                            "filename": f"{report_type}_report",
                        },
                        risk="low",
                        description="导出业务报表",
                        idempotent=True,
                    )
                ],
            )
        if "库存" in text:
            return (
                "reports_inventory",
                ["汇总库存数据", "返回库存报表"],
                [
                    wf(
                        node_id="reports_inventory_summary",
                        tool_id="reports",
                        action="inventory_summary",
                        params={"group_by": "product"},
                        risk="low",
                        description="库存汇总",
                        idempotent=True,
                    )
                ],
            )
        return (
            "reports_sales",
            ["确定统计口径", "汇总销售数据", "返回销售报表"],
            [
                wf(
                    node_id="reports_sales_summary",
                    tool_id="reports",
                    action="sales_summary",
                    params={"group_by": "product"},
                    risk="low",
                    description="销售汇总",
                    idempotent=True,
                )
            ],
        )

    # 4) Inventory queries (no registered inventory.query action; the report
    #    summary is the read surface for "查一下 A100 的库存" style asks).
    if route_intent == "inventory_alert" and "reports" in tool_registry:
        return _domain_business_plan(text, {"intent": "reports_query"}, tool_registry)

    # 5) Customer queries must hit the customer tool, not the product library.
    if route_intent == "customers_query" and "customers" in tool_registry:
        keyword = _facade()._extract_business_db_read_keyword(text, "customers")
        return (
            "customers_query",
            ["识别查询关键词", "查询客户", "返回客户列表"],
            [
                wf(
                    node_id="query_customers",
                    tool_id="customers",
                    action="query",
                    params={"keyword": keyword},
                    risk="low",
                    description="查询客户",
                    idempotent=True,
                )
            ],
        )

    # 6) Shipment documents: full slots generate, missing slots ask first.
    if route_intent == "shipment" and "shipment_orders" in tool_registry:
        unit_m = re_mod.search(
            r"(?:打印|生成|开|打)\s*(?:一下)?\s*([^\s，,。；的]{2,}?)\s*的?\s*(?:发货单|送货单|出货单)",
            text,
        )
        unit_name = (unit_m.group(1) if unit_m else "").strip()
        model_m = re_mod.search(r"(?:编号|型号|model)\s*[:：]?\s*([A-Za-z0-9._-]+)", text, re_mod.I)
        spec_m = re_mod.search(r"规格\s*[:：]?\s*(\d+(?:\.\d+)?)", text)
        qty_m = re_mod.search(r"(\d+(?:\.\d+)?)\s*桶", text)
        if unit_name and (model_m or spec_m or qty_m):
            product: dict[str, _facade().Any] = {"name": model_m.group(1) if model_m else ""}
            if model_m:
                product["model_number"] = model_m.group(1).upper()
            if spec_m:
                product["specification"] = float(spec_m.group(1))
                product["tin_spec"] = float(spec_m.group(1))
            if qty_m:
                product["quantity_tins"] = int(float(qty_m.group(1)))
            return (
                "shipment_generate",
                ["解析客户与产品明细", "生成发货单文档", "返回单据结果"],
                [
                    wf(
                        node_id="generate_shipment",
                        tool_id="shipment_orders",
                        action="generate",
                        params={"unit_name": unit_name, "products": [product]},
                        risk="medium",
                        description=f"为 {unit_name} 生成发货单",
                        idempotent=False,
                    )
                ],
            )
        return (
            "shipment_clarify",
            ["确认客户与产品明细", "反问缺失信息"],
            [
                _facade().build_clarify_node(
                    "请告诉我要给哪个客户开发货单，以及产品型号（编号）、规格和数量。",
                    ambient={"target_node_id": ""},
                )
            ],
        )

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
