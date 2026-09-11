import pytest

from app.application.chat_tool_intent import looks_like_business_db_write


@pytest.mark.parametrize(
    "text", ["新增客户 蓝天科技，联系人张三，电话13800000001", "请帮我添加客户星光贸易"]
)
def test_named_customer_creation_is_explicit_write(text):
    assert looks_like_business_db_write(text)


@pytest.mark.parametrize(
    "text",
    ["新增客户", "不要新增客户蓝天科技", "添加客户甲的产品", "给客户甲添加订单", "查询客户甲"],
)
def test_incomplete_or_other_customer_requests_do_not_use_named_create(text):
    assert not looks_like_business_db_write(text)
