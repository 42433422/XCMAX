"""Customer import preview and execution use case."""

from __future__ import annotations

import json

from app.utils.operational_errors import RECOVERABLE_ERRORS


def _import_customers_preview_or_execute(df, columns, confirm, row_count):
    records = []
    for _, row in df.iterrows():
        record = {}
        for col in columns:
            col_l = col.lower()
            val = str(row.get(col, "")).strip()
            if "名称" in col or "name" in col_l or "客户" in col:
                record["customer_name"] = val
            elif "联系人" in col or "contact" in col_l or "person" in col_l:
                record["contact_person"] = val
            elif "电话" in col or "phone" in col_l or "mobile" in col_l:
                record["contact_phone"] = val
            elif "地址" in col or "address" in col_l:
                record["contact_address"] = val

        if record.get("customer_name"):
            records.append(record)

    if not confirm:
        return json.dumps(
            {
                "success": True,
                "preview": True,
                "import_type": "customers",
                "row_count": len(records),
                "sample_data": records[:5],
                "message": (
                    f"检测到 {len(records)} 条客户记录。"
                    f"当前为预览模式，传 confirm=true 或去掉 preview_only 可直接导入。"
                ),
            },
            ensure_ascii=False,
        )

    try:
        from app.bootstrap import get_customer_app_service

        customer_service = get_customer_app_service()
        imported = 0
        failed = 0

        for record in records:
            result = customer_service.create(record)
            if result.get("success"):
                imported += 1
            else:
                failed += 1

        return json.dumps(
            {
                "success": True,
                "preview": False,
                "imported": imported,
                "failed": failed,
                "message": f"成功导入 {imported} 条客户，失败 {failed} 条",
            },
            ensure_ascii=False,
        )

    except RECOVERABLE_ERRORS as e:
        return json.dumps({"success": False, "error": f"导入失败: {str(e)}"}, ensure_ascii=False)


__all__ = ["_import_customers_preview_or_execute"]
