# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.customer_service_orchestrator")


def _chat_only_reply(
    text: str,
    *,
    intent: str,
    user: _facade().Optional[_facade().User] = None,
    db: _facade().Optional[_facade().Session] = None,
) -> str:
    if intent == "greeting" or _facade().is_greeting(text):
        name = ""
        try:
            from modstore_server.xiaoc_cs_ssot import resolve_user_identity

            if user is not None:
                ident = resolve_user_identity(user, db=db, source="market_cs")
                if ident.display_name and ident.display_name not in {
                    "用户",
                    "访客",
                    "匿名访客",
                }:
                    name = ident.display_name
        except RECOVERABLE_ERRORS:
            pass
        hello = f"{name}，" if name else ""
        return f"我是小C。{hello}你好！有什么可以帮你的？比如产品怎么买、会员权益，或订单/退款问题，直接说就行。"
    if intent == "refund":
        return "我是小C。可以帮你办退款。请发一下订单号和退款原因；材料齐后点击「提交工单」，我会正式登记处理。"
    if intent == "catalog_complaint":
        return "我是小C。投诉可以受理。请补充商品 ID、问题类型和具体说明；齐了之后点击「提交工单」即可。"
    if intent == "product_issue":
        summary = _facade()._summarize_user_issue(text)
        return f"我是小C。收到，这是功能/界面问题：「{summary}」。方便补充一下大概在哪个页面、能否复现吗？若是某个市场上架软件或你们账号定制的 Mod/员工，也可以一并说明。需要正式跟进修复时，点击「提交工单」即可。"
    if intent == "account_support":
        return "我是小C。账号/权益问题可以先说明现象（比如未到账、余额不对）；需要正式核查时，点击「提交工单」。"
    xiaoc = _facade()._xiaoc_general_reply(text, user=user, db=db, ticketed=False)
    if xiaoc:
        return xiaoc
    return "我是小C。已收到你的问题。你可以继续补充细节；若需要平台正式受理，点击「提交工单」即可。"
