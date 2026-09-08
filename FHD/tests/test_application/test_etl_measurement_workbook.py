import pytest
from openpyxl import Workbook

from app.application.etl.parsers import parse_file
from app.application.etl.service_preview_helpers import suggest_mappings
from app.application.etl.targets.customer_products import CustomerProductsAdapter


@pytest.mark.parametrize("unit_header", ["计量单位", "数量单位", "库存单位"])
def test_workbook_preserves_customer_and_measurement_as_separate_columns(tmp_path, unit_header):
    path = tmp_path / "customer-products.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["客户名称", "产品型号", "产品名称", unit_header, "价格"])
    sheet.append(["测试客户", "P100", "测试产品", "桶", 20])
    workbook.save(path)
    workbook.close()
    dataset = parse_file(path, target_type="customer_products")
    mappings = suggest_mappings(dataset, CustomerProductsAdapter())
    by_target = {mapping["target"]: mapping["source"] for mapping in mappings}
    assert "customer_name" in by_target
    assert "measurement_unit" in by_target
    assert by_target["customer_name"] != by_target["measurement_unit"]
    assert len(dataset.rows) == 1
    row = dataset.rows[0].values
    assert row[by_target["customer_name"]] == "测试客户"
    assert row[by_target["measurement_unit"]] == "桶"
