"""产品导出 mixin：从超大仓储实现中拆出 export_to_excel，保持同一契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import inspect

from app.db.models import Product as ProductModel
from app.db.session import get_db
from app.utils.operational_errors import RECOVERABLE_ERRORS


class ProductExportMixin:
    """产品价格表导出能力（独立 mixin，供 SQLAlchemyProductRepository 混入）。"""

    def export_to_excel(
        self,
        unit_name: str | None = None,
        keyword: str | None = None,
        template_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            import os

            from openpyxl import Workbook

            from app.utils.excel.template_export_utils import fill_workbook_from_template

            with get_db() as db:
                inspector = inspect(db.bind)
                if "products" not in inspector.get_table_names():
                    return {
                        "success": False,
                        "message": "产品表不存在",
                        "file_path": None,
                        "filename": None,
                    }

                query = db.query(ProductModel)

                if unit_name:
                    query = query.filter(ProductModel.unit == unit_name)

                if keyword:
                    query = query.filter(
                        (ProductModel.name.like(f"%{keyword}%"))
                        | (ProductModel.description.like(f"%{keyword}%"))
                    )

                products = query.order_by(ProductModel.id.desc()).all()

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{unit_name or '产品'}_价格表_{timestamp}.xlsx"

                from app.utils.path_utils import get_data_dir

                export_dir = os.path.join(get_data_dir(), "exports")
                os.makedirs(export_dir, exist_ok=True)
                file_path = os.path.join(export_dir, filename)

                template_path = None
                if template_id:
                    try:
                        from app.application import get_template_app_service

                        templates = (get_template_app_service().get_templates() or {}).get(
                            "templates"
                        ) or []
                        target = next(
                            (t for t in templates if str(t.get("id")) == str(template_id)), None
                        )
                        if target:
                            candidate_path = str(
                                target.get("path") or target.get("file_path") or ""
                            ).strip()
                            if candidate_path and os.path.exists(candidate_path):
                                template_path = candidate_path
                    except RECOVERABLE_ERRORS:
                        template_path = None

                records = [
                    {
                        "product_code": product.model_number or "",
                        "product_name": product.name or "",
                        "price": product.price or 0.0,
                    }
                    for product in products
                ]

                if template_path:
                    header_alias = {
                        "product_code": ["产品编码", "型号", "产品型号"],
                        "product_name": ["产品名称", "品名"],
                        "price": ["价格", "单价"],
                    }
                    wb = fill_workbook_from_template(
                        template_path=template_path,
                        records=records,
                        field_alias_map=header_alias,
                        sheet_name="产品列表",
                        append_missing_field_columns=True,
                    )
                else:
                    wb = Workbook()
                    ws = wb.active
                    ws.title = "产品列表"

                    headers = ["产品编码", "产品名称", "价格"]
                    ws.append(headers)

                    for row in records:
                        ws.append(
                            [
                                row["product_code"],
                                row["product_name"],
                                row["price"],
                            ]
                        )

                wb.save(file_path)

                return {
                    "success": True,
                    "file_path": str(file_path),
                    "filename": filename,
                    "count": len(products),
                }

        except RECOVERABLE_ERRORS as e:
            return {
                "success": False,
                "message": f"导出失败：{str(e)}",
                "file_path": None,
                "filename": None,
            }
