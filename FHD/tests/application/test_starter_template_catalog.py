from app.application.starter_template_catalog import STARTER_TEMPLATES, merge_starter_templates


def test_starter_catalog_has_business_initialization_coverage() -> None:
    assert len(STARTER_TEMPLATES) >= 10
    names = {row["name"] for row in STARTER_TEMPLATES}
    assert {"客户资料初始化表", "产品资料初始化表", "销售订单标准表", "库存盘点表"} <= names


def test_merge_starter_templates_is_filtered_and_idempotent() -> None:
    first = merge_starter_templates([], "word")
    assert first
    assert all(row["category"] == "word" for row in first)
    second = merge_starter_templates(first, "word")
    assert [row["id"] for row in second] == [row["id"] for row in first]
    assert all(row["starter"] and row["read_only"] for row in second)
