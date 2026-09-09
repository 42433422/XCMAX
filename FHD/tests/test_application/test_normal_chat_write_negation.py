import pytest

from app.application.normal_chat_dispatch import (
    build_clarify_response_dict,
    route_normal_mode_message,
)


@pytest.mark.parametrize(
    "message",
    [
        "不要打印标签",
        "别开单",
        "暂不发货",
        "请先不要删除客户",
        "不用入库",
        "取消打印发货单",
        "不要打印标签，然后给客户开单",
    ],
)
def test_denied_actions_require_clarification(message):
    result = route_normal_mode_message(message)
    assert result["intent"] == "clarify"
    assert result["reason"] == "negated_action"
    response = build_clarify_response_dict(result)
    assert response is not None
    assert response["data"]["action"] == "followup"
    assert "已暂停执行" in response["response"]


@pytest.mark.parametrize("message", ["打印标签", "打印9803标签"])
def test_labels_are_not_shipment_generation(message):
    assert route_normal_mode_message(message)["intent"] == "label_print"


@pytest.mark.parametrize("message", ["打印发货单", "生成七彩乐园送货单"])
def test_affirmative_shipment_remains_available(message):
    assert route_normal_mode_message(message)["intent"] == "shipment"
