"""拒绝类请求不得进入写入执行计划，包括实机复现的只读限定语。"""

from __future__ import annotations

import pytest

from app.domain.conversation.services.chat_tool_intent import (
    is_negated_action_request,
    looks_like_business_db_write,
)

EXECUTION_INTENTS = {
    "shipment",
    "sales_write",
    "delete_entity",
    "label_print",
    "inventory_count",
    "business_db_write",
}

NEGATED_REQUESTS = (
    "只查询，不新增、修改或删除任何业务数据。请查产品编码 DEMO-001，列出产品名称、单价和当前库存，并说明查询是否成功。",
    "不删除产品 DEMO-001",
    "不修改客户资料",
    "不新增产品",
    "不要打印标签",
    "别打印标签",
    "不要删除客户张三",
    "别删除客户张三",
    "不用开单",
    "不要发货",
    "别导出报表",
    "不要新增产品",
    "禁止打印送货单",
    "不要给我打印",
    "不用帮我删除客户",
    "不想再开单了",
    "别再删除客户了",
    "别\t 帮我\u3000删除客户",
    "不允许修改客户资料",
    "确认：只从 xcagi.db.20261008_181715.bak 恢复当前本机副本的整个 xcagi.db。备份已只读核验，订单SO20261008165504在备份中原本就是数量2×单价12.50=总额25；不允许恢复后另行修改订单或其他业务。请仅提交 system_maintenance.restore_database，等待人工审批。恢复后只读核对客户、商品和该订单。",
)


@pytest.mark.parametrize("message", NEGATED_REQUESTS)
def test_negated_request_is_not_business_db_write(message: str) -> None:
    assert looks_like_business_db_write(message) is False


@pytest.mark.parametrize(
    "message",
    [
        "这个产品特别好用",
        "别的客户也买了",
        "客户别名为ABC",
        "分别查询两个客户",
        "识别一下这张发票",
        "保存好了吗",
        pytest.param("别" + "\t" * 100_000, id="whitespace-only-refusal"),
        pytest.param("别" + "\t" * 100_000 + "x", id="whitespace-without-action"),
    ],
)
def test_negation_detector_has_no_word_internal_false_positive(message: str) -> None:
    assert is_negated_action_request(message) is False


def test_business_db_write_still_true_for_affirmative_crud() -> None:
    assert looks_like_business_db_write("删除客户张三") is True
    assert looks_like_business_db_write("把新产品写入数据库") is True
