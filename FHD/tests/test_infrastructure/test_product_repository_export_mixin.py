from contextlib import nullcontext
from unittest.mock import Mock

import pytest

from app.infrastructure.repositories import product_repository_export_mixin as module
from app.infrastructure.repositories.product_repository_export_mixin import ProductExportMixin


@pytest.mark.parametrize("failure, message", [(False, "产品表不存在"), (True, "导出失败")])
def test_export_schema_failure(monkeypatch, failure, message):
    inspector = Mock()
    inspector.get_table_names.return_value = []
    if failure:
        inspector.get_table_names.side_effect = RuntimeError("db down")
    monkeypatch.setattr(module, "get_db", lambda: nullcontext(Mock()))
    monkeypatch.setattr(module, "inspect", lambda bind: inspector)
    result = ProductExportMixin().export_to_excel()
    assert result["success"] is False
    assert message in result["message"]


def test_export_matches_tenant_and_model_filter(monkeypatch, tmp_path):
    from openpyxl import load_workbook
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db.models import Product
    from app.infrastructure.repositories import product_repository_export_mixin as module
    from app.infrastructure.tenant_scope import tenant_scope

    engine = create_engine("sqlite://")
    from app.db.models.product import UomCategory, UomUnit

    for model in (UomCategory, UomUnit, Product):
        model.__table__.create(engine)
    with Session(engine) as db:
        db.add_all(
            [
                Product(tenant_id=1, model_number="DEMO-001", name="可见商品", price=99),
                Product(tenant_id=2, model_number="DEMO-001", name="其他租户", price=88),
                Product(tenant_id=1, model_number="OTHER", name="非匹配商品", price=77),
            ]
        )
        db.commit()
        monkeypatch.setattr(module, "get_db", lambda: nullcontext(db))
        monkeypatch.setattr("app.utils.path_io.path_utils.get_data_dir", lambda: str(tmp_path))
        with tenant_scope(1):
            result = ProductExportMixin().export_to_excel(keyword="DEMO-001")
        assert result["success"] and result["count"] == 1
        workbook = load_workbook(result["file_path"], read_only=True)
        assert list(workbook.active.values) == [
            ("产品编码", "产品名称", "价格"),
            ("DEMO-001", "可见商品", 99),
        ]
        workbook.close()
    engine.dispose()
