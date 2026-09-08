from app.application.etl.product_unit_migration import classify_product_units


def test_classification_keeps_tenants_and_ambiguous_units_separate():
    customers = [
        {"id": 1, "tenant_id": 1, "unit_name": "公司A"},
        {"id": 2, "tenant_id": 2, "unit_name": "公司A"},
        {"id": 3, "tenant_id": 1, "unit_name": "公司B"},
        {"id": 4, "tenant_id": 1, "unit_name": "公司B"},
        {"id": 5, "tenant_id": 1, "unit_name": "桶"},
    ]
    units = ["公司A", "公司B", "桶", "个", "未知", "公司A"]
    rows = [{"id": i, "tenant_id": 1 if i < 5 else None, "unit": u} for i, u in enumerate(units)]
    result = classify_product_units(rows, customers)
    assert [r["classification"] for r in result] == [
        "customer_link_requires_measurement",
        "ambiguous_customer",
        "ambiguous_measure_or_customer",
        "measurement_unit",
        "unresolved_unit",
        "missing_tenant",
    ]
    assert result[0]["candidate_customer_ids"] == [1]
    assert result[-1]["candidate_customer_ids"] == []
    assert rows[0]["unit"] == "公司A"
