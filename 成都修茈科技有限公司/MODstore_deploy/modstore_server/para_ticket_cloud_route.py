"""工单 AI 处理优先走云端执行器（如 Grok Bot，Para 超级员工 ``grok_bot``）。"""

from __future__ import annotations

import os
from typing import Any, Dict

CUSTOMER_TICKET_EVENT = "ops.intake.customer_ticket"


def customer_ticket_cloud_route(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """仅当配置了 ``MODSTORE_PARA_TICKET_DEVICE_ID``、输入是客服工单事件且调用方没有显式
    指定 device_id 时返回云端执行器路由；其余派发（自维护、进化等）与原回退顺序完全不变。
    """
    device_id = (os.environ.get("MODSTORE_PARA_TICKET_DEVICE_ID") or "").strip()
    if not device_id or str(input_data.get("device_id") or "").strip():
        return {}
    if str(input_data.get("event_type") or "").strip() != CUSTOMER_TICKET_EVENT:
        return {}
    return {
        "device_id": device_id,
        "tool_name": (
            os.environ.get("MODSTORE_PARA_TICKET_TOOL") or "grok_bot"
        ).strip(),
        "dispatch_line": (
            os.environ.get("MODSTORE_PARA_TICKET_EXECUTOR") or "grok-bot-cloud"
        ).strip(),
    }
