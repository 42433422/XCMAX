import pytest

from app.application.workflow.read_query_plan import customer_read_node


@pytest.mark.parametrize(
    "message, keyword",
    [
        ("查一下客户 星光贸易 的信息", "星光贸易"),
        ("查询客户蓝天科技的资料", "蓝天科技"),
        ("客户列表", ""),
        ("查看所有客户清单", ""),
        ("请搜索购买单位“明日商贸”", "明日商贸"),
    ],
)
def test_customer_reads_preserve_entity_and_keyword(message, keyword):
    node = customer_read_node(message, {"intent": "customers_query"}, {"customers": {}})
    assert node and node.tool_id == "customers" and node.action == "query"
    assert node.params == {"keyword": keyword}


@pytest.mark.parametrize(
    "message", ["新增客户甲", "查看客户甲的订单", "给客户甲报价", "查询客户的产品", "不要新建客户"]
)
def test_customer_mentions_do_not_replace_other_business_intents(message):
    assert customer_read_node(message, {"intent": "customers_query"}, {"customers": {}}) is None


@pytest.mark.parametrize("message", ["帮我新增一个产品", "请添加一款产品", "新增产品"])
def test_incomplete_catalog_creation_asks_without_creating_customer(message):
    from app.application.workflow.planner import LLMWorkflowPlanner
    from app.services.tools_execution.registry import get_workflow_tool_registry

    planner = LLMWorkflowPlanner.__new__(LLMWorkflowPlanner)
    plan = planner._fallback_plan("missing-product", message, get_workflow_tool_registry())
    assert [(node.tool_id, node.action) for node in plan.nodes] == [
        ("clarify", "ask"),
        ("products", "create"),
    ]
    assert plan.nodes[0].params["clarification"]["missing_fields"] == ["name_or_model"]
    assert plan.nodes[1].params == {}
