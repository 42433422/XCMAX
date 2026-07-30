"""从知识库构造 universal Excel ETL profile。"""

from __future__ import annotations

import os
from typing import Any

from app.application.excel_etl_kb import get_excel_etl_kb
from app.application.shipment_etl_profile import ShipmentEtlProfile, parse_profile_dict


def build_universal_profile_from_kb() -> ShipmentEtlProfile:
    """从知识库同义词构造通用 profile（非送货单专用模板）。"""
    kb = get_excel_etl_kb()
    syn = kb.synonyms()
    write = kb.write_layout("universal_table")

    def _contains(field: str, *, exclude: list[str] | None = None) -> list[dict[str, Any]]:
        tokens = list(syn.get(field) or [])
        if not tokens:
            return []
        rule: dict[str, Any] = {"contains_any": tokens}
        if exclude:
            rule["exclude_any"] = exclude
        return [rule]

    columns: dict[str, list[dict[str, Any]]] = {}
    columns["model_number"] = _contains("model_number", exclude=["订单", "单号", "order"])
    columns["product_name"] = _contains("product_name")
    # 件数 vs 公斤：先匹配带 kg 的列，件数用更严规则避免吞掉 数量KG
    qty_kg_tokens = list(syn.get("quantity_kg") or ["数量kg", "数量/kg", "公斤"])
    columns["quantity_kg"] = [
        {"contains_all_groups": [["数量", "qty"], ["kg", "公斤", "KG"]]},
        {"contains_any": qty_kg_tokens},
    ]
    columns["quantity_tins"] = [
        {"contains_all_groups": [["数量", "qty"], ["件", "桶", "箱", "pcs"]]},
        {
            "exact": ["数量", "数量/", "qty", "qty/"],
            "only_if_missing": ["quantity_tins", "quantity_kg"],
        },
        {
            "contains_any": list(syn.get("quantity_tins") or ["数量"]),
            "exclude_any": ["kg", "公斤", "金额", "单价"],
            "only_if_missing": ["quantity_tins"],
        },
    ]
    columns["tin_spec"] = _contains("tin_spec")
    columns["unit_price"] = _contains("unit_price")
    columns["amount"] = _contains("amount")
    columns["order_number"] = _contains("order_number", exclude=["型号", "model"])
    columns["order_date"] = _contains("order_date")
    columns["remark"] = _contains("remark")

    header_tokens: list[str] = []
    for key in ("model_number", "product_name", "quantity_tins", "unit_price", "amount"):
        header_tokens.extend(syn.get(key) or [])

    data = {
        "id": "universal",
        "kind": "universal_document",
        "label": "通用单据（知识库）",
        "target": str(os.environ.get("FHD_EXCEL_ETL_DEFAULT_TARGET") or "preview_only").strip()
        or "preview_only",
        "detect": {
            "primary": {
                "title_patterns": [],
                "title_weight": 0,
                "buyer_token": (kb.meta_labels().get("unit_name") or ["客户"])[0],
                "buyer_weight": 15,
                "header_hit_tokens": header_tokens[:24],
                "header_hit_weight": 8,
                "header_hit_cap": 6,
                "bonus_tokens": [{"token": t, "weight": 4} for t in (syn.get("amount") or [])[:3]],
                "min_score": 32,
                "probe_rows": 12,
            },
            "ledger": {
                "sheet_name_pattern": r"ledger|流水|明细|出货|sheet",
                "content_tokens": ["ledger", "流水", "明细"],
                "sheet_weight": 20,
                "hit_tokens": list(
                    dict.fromkeys(
                        (syn.get("order_date") or ["日期"])
                        + (syn.get("order_number") or ["单号"])
                        + (syn.get("model_number") or ["型号"])
                        + (syn.get("product_name") or ["名称"])
                        + (syn.get("quantity_tins") or ["数量"])
                        + (syn.get("unit_price") or ["单价"])
                        + (syn.get("amount") or ["金额"])
                    )
                )[:14],
                "hit_weight": 10,
                "hit_cap": 6,
                # 通用表头本身也会抬高 delivery 分；勿因同分压制 ledger
                "suppress_if_delivery_score_gte": 999,
                "probe_rows": 10,
            },
        },
        "header_detect": {
            "primary": {
                "max_scan_rows": 20,
                "require_groups": [
                    list(syn.get("model_number") or ["型号", "sku"]),
                    list(syn.get("product_name") or ["名称", "品名"]),
                    list(syn.get("quantity_tins") or ["数量", "qty"]),
                ],
            },
            "ledger": {
                "max_scan_rows": 16,
                "require_groups": [
                    list(syn.get("order_number") or ["单号", "订单号"]),
                    list(syn.get("product_name") or ["名称", "品名"]),
                    list(syn.get("quantity_tins") or ["数量", "qty"]),
                ],
                "and_any_groups": [
                    list(syn.get("model_number") or ["型号", "sku"]),
                    list(syn.get("tin_spec") or ["规格"]),
                ],
            },
        },
        "columns": columns,
        "write": write,
    }
    return parse_profile_dict(data, source="<knowledge_base:universal>")
