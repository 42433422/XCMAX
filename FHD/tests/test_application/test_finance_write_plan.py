import pytest

from app.application.workflow.finance_write_plan import finance_transaction_node


@pytest.mark.parametrize(
    "message, kind, amount",
    [
        ("记一笔收入 5000 元，来自星光贸易", "revenue", 5000),
        ("记录一笔支出12.35元，付给乙公司", "expense", 12.35),
    ],
)
def test_explicit_transactions_preserve_amount_and_require_approval(message, kind, amount):
    node = finance_transaction_node(message, {"finance": {}})
    assert node and node.params["amount"] == amount and node.params["transaction_type"] == kind
    assert node.risk == "medium" and node.idempotent is False


@pytest.mark.parametrize(
    "message", ["不要记一笔收入5000元", "查询收入5000元", "记一笔收入0元", "记一笔收入-5元"]
)
def test_negated_queries_and_invalid_amounts_do_not_create_transactions(message):
    assert finance_transaction_node(message, {"finance": {}}) is None
