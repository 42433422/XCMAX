"""Built-in demonstration plans for the host model-payment surface."""

from __future__ import annotations

from typing import Any

DEMO_PLANS: list[dict[str, Any]] = [
    {
        "id": "demo-starter",
        "title": "体验档",
        "description": "本地演示：未接商户时仅展示流程与界面，不产生真实扣款。",
        "amount_cents": 990,
        "currency": "CNY",
        "badge": "演示",
    },
    {
        "id": "demo-standard",
        "title": "标准档",
        "description": "适合个人高频使用；接入支付宝后可替换为真实套餐与金额。",
        "amount_cents": 4990,
        "currency": "CNY",
        "badge": None,
    },
    {
        "id": "demo-pro",
        "title": "专业档",
        "description": "更高配额与优先响应；上线前请在环境变量中配置支付参数。",
        "amount_cents": 19900,
        "currency": "CNY",
        "badge": "推荐",
    },
]

__all__ = ["DEMO_PLANS"]
