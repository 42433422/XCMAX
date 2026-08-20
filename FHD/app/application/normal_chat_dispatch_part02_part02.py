# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.normal_chat_dispatch")


def build_finance_query_response_dict(
    route_result: dict[str, _facade().Any],
) -> dict[str, _facade().Any] | None:
    """财务/凭证/收支流水查询。"""
    if route_result.get("intent") != "finance_query":
        return None
    try:
        from app.application.finance_app_service import FinanceAppService

        result = FinanceAppService().list_transactions(page=1, per_page=20)
        items = result.get("data") or []
        total = int(result.get("total") or len(items))
        if not items:
            msg = "当前没有财务收支记录。"
        else:
            lines = []
            for t in items[:10]:
                t_type = str(t.get("transaction_type") or "")
                direction = (
                    "收入" if "in" in str(t_type).lower() or "收款" in str(t_type) else "支出"
                )
                lines.append(
                    f"- {str(t.get('transaction_date') or '')[:10]} {direction} ￥{_facade().format_money(_facade().safe_float(t.get('amount')))} {t.get('counterparty_name', '')}"
                )
            msg = f"共 {total} 条收支记录：\n" + "\n".join(lines)
            if total > 10:
                msg += f"\n…其余 {total - 10} 条请到「财务」查看"
        return {
            "success": True,
            "response": msg,
            "data": {"intent": "finance_query", "transactions": items[:20], "total": total},
            "normal_slot_dispatch": True,
        }
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.warning("finance.query 工具失败: %s", e)
        return {
            "success": False,
            "response": "财务查询服务暂时不可用，请稍后重试。",
            "data": {},
            "normal_slot_dispatch": True,
        }


def build_knowledge_query_response_dict(
    route_result: dict[str, _facade().Any],
) -> dict[str, _facade().Any] | None:
    """知识库/帮助文档：引导直达资料库（无数据库读取）。"""
    if route_result.get("intent") != "knowledge_query":
        return None
    return {
        "success": True,
        "response": "你可以在「知识库」查看产品型号说明、操作手册与常见问题。模块入口：产品 → 型号详情；设置 → 帮助中心。",
        "data": {
            "intent": "knowledge_query",
            "autoAction": {"type": "open_knowledge", "feature": "knowledge"},
        },
        "normal_slot_dispatch": True,
    }


def build_sales_query_response_dict(
    route_result: dict[str, _facade().Any],
) -> dict[str, _facade().Any] | None:
    """销售订单/报价单查询：确定性调用 sales.query（Sales-to-Payment 闭环）。"""
    if route_result.get("intent") != "sales_query":
        return None
    keyword = str((route_result.get("slots") or {}).get("keyword") or "").strip()
    try:
        from app.application.sales_app_service import SalesAppService

        result = SalesAppService().query(keyword=keyword or None, page=1, per_page=20)
        if isinstance(result, dict) and result.get("success") is False:
            return {
                "success": False,
                "response": str(result.get("message") or "销售查询工具执行失败"),
                "data": {"intent": "sales_query"},
                "normal_slot_dispatch": True,
            }
        orders = result.get("data") or []
        total = int(result.get("total") or len(orders))
        if not orders:
            msg = (
                "当前没有销售订单。" if not keyword else f"没有查到与「{keyword}」匹配的销售订单。"
            )
        else:
            lines = []
            for o in orders[:10]:
                status = str(o.get("status") or "")
                lines.append(
                    f"- {o.get('order_no', '')} {o.get('customer_name', '')} ￥{_facade().format_money(_facade().safe_float(o.get('total_amount')))}（{status}）"
                )
            msg = f"共 {total} 条销售订单：\n" + "\n".join(lines)
            if total > 10:
                msg += f"\n…其余 {total - 10} 条请到「销售订单」查看"
        return {
            "success": True,
            "response": msg,
            "data": {"intent": "sales_query", "orders": orders[:20], "total": total},
            "normal_slot_dispatch": True,
        }
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.warning("sales.query 工具失败: %s", e)
        return {
            "success": False,
            "response": "销售查询服务暂时不可用，请稍后重试。",
            "data": {},
            "normal_slot_dispatch": True,
        }


def build_reports_query_response_dict(
    route_result: dict[str, _facade().Any], *, message: str = ""
) -> dict[str, _facade().Any] | None:
    """报表/汇总/看板查询：按关键词命中销售/库存/采购/经营看板报表。"""
    if route_result.get("intent") != "reports_query":
        return None
    text = str(message or "").strip()
    try:
        from app.services.report_service import ReportService

        svc = ReportService()
        if "库存" in text or "库存报表" in text:
            result = svc.get_inventory_report()
            label = "库存"
        elif "采购" in text or "采购报表" in text:
            result = svc.get_purchase_report()
            label = "采购"
        elif "看板" in text or "经营" in text or "数据" in text:
            result = svc.get_dashboard_summary()
            label = "经营看板"
        else:
            result = svc.get_sales_report(group_by="product")
            label = "销售"
        if isinstance(result, dict) and result.get("success") is False:
            return {
                "success": False,
                "response": str(result.get("message") or "报表工具执行失败"),
                "data": {"intent": "reports_query"},
                "normal_slot_dispatch": True,
            }
        rows = result.get("data") or []
        summary = result.get("summary") or {}
        if not rows:
            msg = f"当前{label}报表暂无数据。"
        else:
            lines = [f"- {r}" for r in [str(r) for r in rows[:5]]]
            msg = f"{label}报表共 {len(rows)} 条：\n" + "\n".join(lines)
            if summary:
                bits = [f"{k}={v}" for k, v in summary.items()][:4]
                msg += f"\n汇总：{'，'.join(bits)}"
        return {
            "success": True,
            "response": msg,
            "data": {
                "intent": "reports_query",
                "report_type": label,
                "rows": rows[:20],
                "summary": summary,
            },
            "normal_slot_dispatch": True,
        }
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.warning("reports.* 工具失败: %s", e)
        return {
            "success": False,
            "response": "报表服务暂时不可用，请稍后重试。",
            "data": {},
            "normal_slot_dispatch": True,
        }


def build_replenishment_suggest_response_dict(
    route_result: dict[str, _facade().Any],
) -> dict[str, _facade().Any] | None:
    """补货/采购建议：确定性调用 suggest_replenishment（吸收 Odoo 18 补货逻辑）。"""
    if route_result.get("intent") != "replenishment_suggest":
        return None
    try:
        from app.services.replenishment_service import suggest_replenishment

        result = suggest_replenishment()
        if isinstance(result, dict) and result.get("success") is False:
            return {
                "success": False,
                "response": str(result.get("message") or "补货建议工具执行失败"),
                "data": {"intent": "replenishment_suggest"},
                "normal_slot_dispatch": True,
            }
        suggestions = result.get("data") or []
        summary = result.get("summary") or {}
        if not suggestions:
            msg = "当前没有需要补货的物料，库存状态正常。"
        else:
            lines = [
                f"- {s.get('name', '')} 当前 {s.get('current_quantity', 0)} {s.get('unit', '')}，建议补 {s.get('suggest_quantity', 0)}"
                for s in suggestions[:10]
            ]
            msg = (
                f"发现 {len(suggestions)} 种物料需要补货：\n"
                + "\n".join(lines)
                + f"\n合计建议采购金额 ￥{_facade().format_money(_facade().safe_float(summary.get('total_suggest_amount')))}"
            )
        return {
            "success": True,
            "response": msg,
            "data": {
                "intent": "replenishment_suggest",
                "suggestions": suggestions[:20],
                "summary": summary,
            },
            "normal_slot_dispatch": True,
        }
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.warning("replenishment.suggest 工具失败: %s", e)
        return {
            "success": False,
            "response": "补货建议服务暂时不可用，请稍后重试。",
            "data": {},
            "normal_slot_dispatch": True,
        }
