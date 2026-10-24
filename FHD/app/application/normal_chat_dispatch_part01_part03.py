# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.normal_chat_dispatch")


def build_customers_query_response_dict(
    route_result: dict[str, _facade().Any], *, request: _facade().Any | None = None
) -> dict[str, _facade().Any] | None:
    """客户查询：确定性调用 customers.query（ERP list），按 Agent 工具结果作答。

    无 LLM 时也可直接 tool-call 读库；禁止把用户原话当 keyword，空结果用中性「暂无/不匹配」文案。
    """
    if route_result.get("intent") != "customers_query":
        return None
    slots = route_result.get("slots") or {}
    keyword = str(slots.get("keyword") or "").strip()
    customer_id = None
    if "id" in slots:
        raw_id = str(slots["id"]).strip()
        if not _facade().re.fullmatch(r"[1-9]\d*", raw_id):
            return {"success": False, "response": "请提供一个有效的客户 ID（正整数）。", "data": {}}
        customer_id = int(raw_id)
    tool_params: dict[str, _facade().Any] = (
        {"id": customer_id} if customer_id is not None else {"page": 1, "per_page": 50}
    )
    if keyword:
        tool_params["keyword"] = keyword
    try:
        from starlette.responses import JSONResponse

        from app.infrastructure.tenant_scope import tenant_scope
        from app.mod_sdk.erp_customers_facade import customers_get
        from app.mod_sdk.erp_customers_facade import customers_list as customers_list_via_service
        from app.mod_sdk.erp_domain_dispatch import try_invoke_erp_domain_handler

        with tenant_scope(_facade()._request_tenant_id(request)):
            result = try_invoke_erp_domain_handler(
                "customers",
                "get" if customer_id is not None else "list",
                request=request,
                **(
                    {"customer_id": customer_id}
                    if customer_id is not None
                    else {"page": 1, "per_page": 50, "keyword": keyword or None}
                ),
            )
            if result is None:
                result = (
                    customers_get(request, customer_id)
                    if customer_id is not None
                    else customers_list_via_service(
                        request, page=1, per_page=50, keyword=keyword or None
                    )
                )
        if isinstance(result, JSONResponse):
            result = _facade().json.loads(result.body)
        if customer_id is not None and isinstance(result, dict) and result.get("success"):
            record = result.get("data")
            if not isinstance(record, dict) or record.get("id") != customer_id:
                result = {"success": False, "message": "客户查询工具未返回指定 ID 的记录。"}
            else:
                result = {**result, "data": [record], "total": 1}
        if isinstance(result, dict) and result.get("success") is False:
            msg = str(result.get("message") or result.get("response") or "客户查询工具执行失败")
            tool_record = {
                "tool_id": "customers",
                "action": "query",
                "params": tool_params,
                "output": result if isinstance(result, dict) else {"success": False},
                "tool_call_id": "tc-customers-query",
            }
            return {
                "success": False,
                "response": msg,
                "data": {"intent": "customers_query", "legacy_tool_records": [tool_record]},
                "legacy_tool_records": [tool_record],
                "agent_tool_dispatch": True,
                "normal_slot_dispatch": True,
            }
        customers = result.get("data", []) if isinstance(result, dict) else []
        if not isinstance(customers, list):
            customers = []
        total = (
            int(result.get("total") or len(customers))
            if isinstance(result, dict)
            else len(customers)
        )
        if not customers:
            msg = f"没有查到与「{keyword}」匹配的客户。" if keyword else "当前客户库暂无数据。"
        elif customer_id is not None:
            record = customers[0]
            msg = (
                f"客户 ID {customer_id}：{record.get('customer_name', '')}\n"
                f"联系人：{record.get('contact_person') or '未填写'}\n"
                f"电话：{record.get('contact_phone') or '未填写'}\n"
                f"地址：{record.get('contact_address') or '未填写'}"
            )
        else:
            lines = [
                f"- {c.get('customer_name', '')} {c.get('contact_person', '')}".rstrip()
                for c in customers[:10]
            ]
            msg = f"当前共有 {total} 位客户：\n" + "\n".join(lines)
            if total > 10:
                msg += f"\n…其余 {total - 10} 位请到「客户管理」查看"
        tool_output = {
            "success": True,
            "data": customers[:20],
            "total": total,
            "page": 1,
            "per_page": 50,
        }
        tool_record = {
            "tool_id": "customers",
            "action": "query",
            "params": tool_params,
            "output": tool_output,
            "tool_call_id": "tc-customers-query",
        }
        return {
            "success": True,
            "response": msg,
            "data": {
                "intent": "customers_query",
                "customers": customers[:20],
                "legacy_tool_records": [tool_record],
            },
            "legacy_tool_records": [tool_record],
            "agent_tool_dispatch": True,
            "normal_slot_dispatch": True,
        }
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.warning("customers.query 工具失败: %s", e)
        return {
            "success": False,
            "response": "客户查询工具暂时不可用，请稍后重试。",
            "data": {},
            "agent_tool_dispatch": True,
            "normal_slot_dispatch": True,
        }
