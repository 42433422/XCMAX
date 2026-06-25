"""小C 会议纪要意图分流：命中、autoAction、不误命中。"""

from __future__ import annotations

import pytest

import app.mod_sdk  # noqa: F401  # 预热 app.services 包，规避隔离运行时已知的循环导入
from app.application.normal_chat_dispatch import (
    build_meeting_minutes_response_dict,
    route_normal_mode_message,
)


@pytest.mark.parametrize(
    "msg",
    [
        "帮我整理会议纪要",
        "把会议记录整理一下",
        "生成会议总结",
        "整理会议",
        "会议要点",
    ],
)
def test_meeting_intent_hit(msg):
    assert route_normal_mode_message(msg)["intent"] == "meeting_minutes"


def test_autoaction_shape():
    rr = route_normal_mode_message("整理会议纪要")
    out = build_meeting_minutes_response_dict(rr)
    assert out is not None
    assert out["success"] is True
    assert out["autoAction"]["type"] == "show_meeting_minutes_float"
    assert out["autoAction"]["feature"] == "meeting_minutes"
    assert out["data"]["intent"] == "meeting_minutes"


def test_builder_returns_none_for_other_intent():
    assert build_meeting_minutes_response_dict({"intent": "product_query"}) is None


@pytest.mark.parametrize(
    "msg",
    [
        "查一下A001的库存",  # inventory / product
        "帮我查询客户信息",  # customers
        "开个发货单",  # shipment
    ],
)
def test_non_meeting_not_misrouted(msg):
    assert route_normal_mode_message(msg)["intent"] != "meeting_minutes"
