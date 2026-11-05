"""Preview mapped imports, then acquire business writers only after confirmation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, cast

import pandas as pd

from app.application.tools.workflow_tools.contracts import ImportServices, Payload
from app.application.tools.workflow_tools.excel_analysis import frame_records
from app.application.tools.workflow_tools.import_mapping import ProductRows
from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def write_succeeded(result: Any) -> bool:
    return (
        isinstance(result, dict)
        and result.get("success") is True
        and not (
            result.get("outcome") == "unknown"
            or result.get("reconciliation_required")
            or result.get("outcome_unknown")
            or result.get("requires_reconciliation")
        )
    )


def batch_counts(result: Any, total: int) -> tuple[int, int]:
    if not isinstance(result, dict):
        raise ValueError("missing batch receipt")
    sources = [result]
    if isinstance(result.get("data"), dict):
        sources.append(result["data"])

    def count(*names: str) -> int:
        values = [source[name] for source in sources for name in names if name in source]
        if not values:
            return 0
        if any(type(value) is not int or value < 0 or value != values[0] for value in values):
            raise ValueError("ambiguous batch count")
        return cast(int, values[0])

    imported, failed = count("success_count", "imported"), count("failed_count", "failed")
    if imported + failed > total:
        raise ValueError("batch counts exceed input")
    return imported, failed


def import_receipt(
    imported: int,
    failed: int,
    entity: str,
    *,
    total: int,
    success: bool,
    unknown: bool = False,
    other_writes: bool = False,
) -> Payload:
    success = success and not failed and not unknown
    reconcile = not success and bool(unknown or imported or other_writes)
    return {
        "success": bool(success),
        "preview": False,
        "imported": imported,
        "failed": failed,
        "pending": max(0, total - imported - failed),
        "outcome": "unknown" if unknown else "success" if success else "failed",
        "outcome_unknown": unknown,
        "reconciliation_required": reconcile,
        "requires_reconciliation": reconcile,
        "retryable": not reconcile,
        "safe_to_retry": not reconcile,
        "message": ("导入完成。" if success else "导入已停止。")
        + f"已确认导入 {imported} 条{entity}，失败 {failed} 条。"
        + ("部分写入结果待核对，请勿直接重试。" if reconcile else ""),
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
                + "当前为预览模式，审核并明确确认后传 confirm=true 执行导入。",
            }
            if read_meta:
                preview["read_options"] = read_meta
            return preview
        imported = failed = 0
        write_in_flight = created_customer = False
        success = False
        try:
            target_unit = detected_unit or unit_name
            if target_unit and not self.services.find_customer(target_unit):
                customer = self.services.customer()
                write_in_flight = True
                result = customer.create(
                    {
                        "customer_name": target_unit,
                        "contact_person": None,
                        "contact_phone": None,
                        "contact_address": None,
                    }
                )
                if not write_succeeded(result):
                    return import_receipt(
                        0, 0, "产品", total=len(records), success=False, unknown=True
                    )
                write_in_flight = False
                created_customer = True
            products = self.services.products()
            for record in records:
                record["unit"] = target_unit or "件"
            write_in_flight = True
            result = products.batch_add_products(records)
            imported, failed = batch_counts(result, len(records))
            success = write_succeeded(result) and failed == 0 and imported == len(records)
            write_in_flight = not success
        except BOUNDARY_ERRORS:
            logger.exception("产品导入执行失败")
            success = False
        receipt = import_receipt(
            imported,
            failed,
            "产品",
            total=len(records),
            success=success,
            unknown=write_in_flight,
            other_writes=created_customer,
        )
        receipt["skipped_clause_like_rows"] = skipped
        return receipt

    def customers(self, records: list[Payload], confirm: bool) -> Payload:
        if not confirm:
            return {
                "success": True,
                "preview": True,
                "import_type": "customers",
                "row_count": len(records),
                "sample_data": records[:5],
                "message": f"检测到 {len(records)} 条客户记录。当前为预览模式，审核并明确确认后传 confirm=true 执行导入。",
            }
        imported = failed = 0
        write_in_flight = False
        success = False
        try:
            customer = self.services.customer()
            for record in records:
                write_in_flight = True
                if not write_succeeded(customer.create(record)):
                    failed += 1
                    break
                write_in_flight = False
                imported += 1
            success = imported == len(records)
        except BOUNDARY_ERRORS:
            logger.exception("客户导入执行失败")
            failed += int(write_in_flight)
        return import_receipt(
            imported, failed, "客户", total=len(records), success=success, unknown=write_in_flight
        )

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
        imported = failed = 0
        write_in_flight = False
        success = False
        try:
            shipment = self.services.shipment()
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
                    write_in_flight = True
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
                    if not write_succeeded(result):
                        failed += 1
                        break
                    write_in_flight = False
                    imported += 1
                except RECOVERABLE_ERRORS:
                    failed += 1
                    if write_in_flight:
                        break
            success = imported == len(df)
        except BOUNDARY_ERRORS:
            logger.exception("出货记录导入执行失败")
            failed += int(write_in_flight)
            success = False
        return import_receipt(
            imported, failed, "出货记录", total=len(df), success=success, unknown=write_in_flight
        )
