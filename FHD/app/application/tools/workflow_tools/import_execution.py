"""Preview mapped imports, then acquire business writers only after confirmation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.application.tools.workflow_tools.contracts import ImportServices, Payload
from app.application.tools.workflow_tools.excel_analysis import frame_records
from app.application.tools.workflow_tools.import_mapping import ProductRows
from app.utils.operational_errors import RECOVERABLE_ERRORS


def import_receipt(imported: int, failed: int, entity: str) -> Payload:
    return {
        "success": True,
        "preview": False,
        "imported": imported,
        "failed": failed,
        "message": f"成功导入 {imported} 条{entity}，失败 {failed} 条",
    }


@dataclass(frozen=True)
class ImportExecutor:
    services: ImportServices

    def products(
        self, rows: ProductRows, unit_name: str, confirm: bool, read_meta: Payload | None
    ) -> Payload:
        records, detected_unit, skipped = rows.records, rows.unit, rows.skipped_clauses
        if not confirm:
            preview: Payload = {
                "success": True,
                "preview": True,
                "import_type": "products",
                "detected_unit": detected_unit,
                "field_mapping": rows.fields,
                "row_count": len(records),
                "skipped_clause_like_rows": skipped,
                "sample_data": records[:5],
                "message": f"检测到 {len(records)} 条产品记录，绑定客户: {detected_unit or unit_name or '未指定'}。"
                + (f" 已跳过疑似表尾条款行 {skipped} 条。" if skipped else "")
                + "当前为预览模式，传 confirm=true 或去掉 preview_only 可直接导入。",
            }
            if read_meta:
                preview["read_options"] = read_meta
            return preview
        try:
            target_unit = detected_unit or unit_name
            if target_unit and not self.services.find_customer(target_unit):
                self.services.customer().create(
                    {
                        "customer_name": target_unit,
                        "contact_person": None,
                        "contact_phone": None,
                        "contact_address": None,
                    }
                )
            products = self.services.products()
            for record in records:
                record["unit"] = target_unit or "件"
            result = products.batch_add_products(records)
            imported, failed = 0, 0
            if isinstance(result, dict):
                imported = int(result.get("success_count") or result.get("imported") or 0)
                failed = int(result.get("failed_count") or result.get("failed") or 0)
                if imported == 0 and failed == 0 and isinstance(result.get("data"), dict):
                    imported = int(result["data"].get("success_count") or 0)
                    failed = int(result["data"].get("failed_count") or 0)
            message = str(
                result.get("message")
                if isinstance(result, dict) and result.get("message")
                else f"成功导入 {imported} 条产品"
            )
            return {
                "success": True,
                "preview": False,
                "imported": imported,
                "failed": failed,
                "skipped_clause_like_rows": skipped,
                "message": message + (f"（另跳过疑似条款/表尾行 {skipped} 条）" if skipped else ""),
            }
        except RECOVERABLE_ERRORS:
            return {"success": False, "error": "产品导入失败，请检查文件后重试"}

    def customers(self, records: list[Payload], confirm: bool) -> Payload:
        if not confirm:
            return {
                "success": True,
                "preview": True,
                "import_type": "customers",
                "row_count": len(records),
                "sample_data": records[:5],
                "message": f"检测到 {len(records)} 条客户记录。当前为预览模式，传 confirm=true 或去掉 preview_only 可直接导入。",
            }
        try:
            customer = self.services.customer()
            imported, failed = 0, 0
            for record in records:
                if customer.create(record).get("success"):
                    imported += 1
                else:
                    failed += 1
            return import_receipt(imported, failed, "客户")
        except RECOVERABLE_ERRORS:
            return {"success": False, "error": "客户导入失败，请检查文件后重试"}

    def orders(
        self,
        df: pd.DataFrame,
        columns: list[str],
        mapping: dict[str, str],
        unit_name: str,
        confirm: bool,
        row_count: int,
    ) -> Payload:
        sample = frame_records(df, 5)
        if not confirm:
            return {
                "success": True,
                "preview": True,
                "import_type": "orders",
                "columns": columns,
                "column_mapping": mapping,
                "row_count": row_count,
                "sample_data": sample,
                "message": f"检测到 {row_count} 条出货记录，确认导入请设置 confirm=true。",
            }
        try:
            shipment = self.services.shipment()
            imported, failed = 0, 0
            for _, row in df.iterrows():
                try:

                    def value(field: str, default: object = "") -> Any:
                        column = next(
                            (column for column, mapped in mapping.items() if mapped == field), ""
                        )
                        return row.get(column, default)

                    effective_unit = unit_name or str(value("unit_name") or "").strip()
                    if not effective_unit:
                        failed += 1
                        continue
                    product_name = str(value("product_name") or "").strip()
                    model = str(value("model_number") or "").strip()
                    raw_quantity = value("quantity", 1)
                    quantity = max(1, int(float(raw_quantity))) if raw_quantity else 1
                    result = shipment.create_shipment(
                        unit_name=effective_unit,
                        items_data=[
                            {
                                "product_name": product_name or model,
                                "model_number": model,
                                "quantity": quantity,
                            }
                        ],
                    )
                    if result.get("success"):
                        imported += 1
                    else:
                        failed += 1
                except RECOVERABLE_ERRORS:
                    failed += 1
            return import_receipt(imported, failed, "出货记录")
        except RECOVERABLE_ERRORS:
            return {"success": False, "error": "订单导入失败，请检查文件后重试"}
