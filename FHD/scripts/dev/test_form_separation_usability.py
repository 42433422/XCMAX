#!/usr/bin/env python3
"""拆得开还不够：验证「抽出的数据 + 版式」能否真正用来建单/打单。

链路：
1. ETL preview → notes（数据）
2. decompose → headers（版式列）
3. 把 notes 提升为 shipment target 后 execute（假仓储）
4. 用抽出的 unit/items + 源文件路径 generate_shipment_document

用法::

    cd FHD && .venv/bin/python scripts/dev/test_form_separation_usability.py
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FORMS = ROOT / "tests" / "fixtures" / "network_forms"
CLOSED = ROOT / "tests" / "fixtures" / "shipment_etl" / "闭环测试_送货单模板.xlsx"


def _item_usable(item: dict) -> bool:
    name = str(item.get("product_name") or item.get("name") or "").strip()
    model = str(item.get("model_number") or item.get("model") or "").strip()
    qty = item.get("quantity_tins") or item.get("quantity") or item.get("qty")
    try:
        qty_n = float(qty)
    except (TypeError, ValueError):
        qty_n = 0
    if not ((name or model) and qty_n > 0):
        return False
    # 明显非商品语义
    junk = {"february", "march", "april", "may", "june", "july", "january", "my title"}
    if name.lower() in junk or model.lower() in junk:
        return False
    if qty_n >= 1900 and qty_n <= 2100 and name.lower() in {
        "my title",
        "another title",
        "the best image ever",
    }:
        return False
    return True


def _items_semantically_sane(items: list[dict]) -> bool:
    if not items:
        return False
    months = {
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    }
    names = [str(i.get("product_name") or i.get("name") or "").strip().lower() for i in items]
    if sum(1 for n in names if n in months) >= 2:
        return False
    # 年份当数量 + 标题当品名 → 档案表误入
    yearish = 0
    for i in items:
        try:
            q = float(i.get("quantity_tins") or i.get("quantity") or 0)
        except (TypeError, ValueError):
            q = 0
        if 1990 <= q <= 2035:
            yearish += 1
    if yearish >= 2:
        return False
    return True


def _unit_usable(unit: str, file_stem: str) -> bool:
    u = str(unit or "").strip()
    if not u:
        return False
    # 退化为文件名 / 纯单号，业务可用性较差
    if u == file_stem or u.startswith("net_") or u.startswith("form_"):
        return False
    if re.fullmatch(r"[A-Z0-9\-_/]+", u) and len(u) < 24:
        # 像 DKJ-PO-2026-0007 这类更像单号
        return False
    return True


def _promote(notes: list[dict]) -> list[dict]:
    out = []
    for n in notes:
        nn = dict(n)
        nn["profile_target"] = "shipment"
        out.append(nn)
    return out


def _eval_one(path: Path) -> dict:
    from app.application.excel_template_http_app_service import _decompose_template
    from app.application.shipment_app_service import ShipmentApplicationService
    from app.application.shipment_excel_etl_app_service import (
        execute_shipment_excel_etl,
        preview_shipment_excel_etl,
    )
    from app.application.shipment_template_resolve import clear_template_list_cache

    stem = path.stem
    preview = preview_shipment_excel_etl(str(path), workspace_root=path.parent)
    notes = list((preview or {}).get("notes") or []) if isinstance(preview, dict) else []
    decomp, _ = _decompose_template(str(path), sample_rows=3)
    headers = ((decomp or {}).get("decomposition") or {}).get("editable_entries") or []

    # 选「最好」的一张 note 做可用性判定
    best = None
    best_score = -1
    for n in notes:
        items = [i for i in (n.get("items") or []) if isinstance(i, dict) and _item_usable(i)]
        score = len(items) * 10 + (5 if _unit_usable(str(n.get("unit_name") or ""), stem) else 0)
        score += int(n.get("score") or 0)
        if score > best_score:
            best_score = score
            best = {**n, "_usable_items": items}

    data_ok = bool(best and best.get("_usable_items"))
    semantic_ok = bool(best and _items_semantically_sane(list(best.get("_usable_items") or [])))
    unit_ok = bool(best and _unit_usable(str(best.get("unit_name") or ""), stem))
    layout_ok = len(headers) >= 2 or bool(((decomp or {}).get("decomposition") or {}).get("header_row"))

    create_calls: list[dict] = []

    class _FakeShip:
        def create_shipment(self, unit_name, items_data, contact_person="", **kwargs):
            create_calls.append(
                {
                    "unit_name": unit_name,
                    "items_data": items_data,
                    "contact_person": contact_person,
                    **kwargs,
                }
            )
            return {"success": True, "shipment": {"id": 9000 + len(create_calls)}}

        def get_orders(self, limit: int = 10):
            return []

    exec_result: dict = {"success": False, "skipped": True}
    if notes:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            # 拷到沙箱再 execute
            sandbox = td_path / path.name
            sandbox.write_bytes(path.read_bytes())
            fp_db = td_path / "fp.sqlite3"
            with (
                patch("app.bootstrap.get_shipment_app_service", return_value=_FakeShip()),
                patch(
                    "app.services.tools_workflow_registered._execute_excel_import_records",
                    return_value={"success": True, "imported": 1},
                ),
                patch(
                    "app.application.shipment_excel_etl_fingerprint_store._legacy_db_path",
                    return_value=fp_db,
                ),
                patch(
                    "app.application.shipment_excel_etl_fingerprint_store._db_path",
                    return_value=fp_db,
                ),
            ):
                exec_result = execute_shipment_excel_etl(
                    sandbox,
                    notes=_promote(notes),
                    idempotent=False,
                    workspace_root=td_path,
                    import_products=True,
                    import_shipments=True,
                )

    create_ok = bool(exec_result.get("success")) and int(exec_result.get("shipment_created") or 0) > 0
    if create_ok and create_calls:
        # 建单内容也要可用
        call = create_calls[0]
        create_ok = _unit_usable(str(call.get("unit_name") or ""), stem) or bool(
            call.get("items_data")
        )
        # 若 unit 是文件名但 items 可用，仍算「半可用」
        items_ok = any(_item_usable(i) for i in (call.get("items_data") or []) if isinstance(i, dict))
        create_ok = bool(items_ok)

    # 打单：用抽出数据 + 源文件当模版
    gen_result: dict = {"success": False, "skipped": True}
    gen_ok = False
    if best and best.get("_usable_items"):
        doc = MagicMock()
        doc.generate.return_value = {
            "success": True,
            "doc_name": f"{best.get('unit_name')}_发货单.xlsx",
            "file_path": f"/tmp/{best.get('unit_name')}_发货单.xlsx",
            "purchase_unit": best.get("unit_name"),
            "unit_id": 1,
            "parsed_products": best["_usable_items"],
        }
        svc = ShipmentApplicationService(repository=MagicMock(), document_generator=doc)
        clear_template_list_cache()
        store = MagicMock()
        store.resolve_template_file.return_value = str(path.resolve())
        store.list_templates.return_value = [
            {
                "id": "db:1",
                "db_id": 1,
                "name": path.stem,
                "path": str(path.resolve()),
                "template_type": "发货单",
                "is_active": 1,
                "source": "db",
            }
        ]
        store.get_default_for_type.return_value = store.list_templates.return_value[0]
        with (
            patch(
                "app.application.shipment_template_resolve._get_template_store",
                return_value=store,
            ),
            patch(
                "app.application.shipment_template_resolve.log_template_usage",
                return_value=None,
            ),
            patch(
                "app.application.shipment_template_resolve._log_template_usage",
                return_value=None,
            ),
        ):
            gen_result = svc.generate_shipment_document(
                unit_name=str(best.get("unit_name") or stem),
                products=list(best["_usable_items"]),
                template_id="db:1",
                order_number=str(best.get("order_number") or "") or None,
                intent="shipment_generate",
            )
        gen_ok = bool(gen_result.get("success")) and bool(
            (gen_result.get("template_resolution") or {}).get("path")
        )

    # 可用性分级
    # A: 客户名真 + 明细语义正常 + 能建单 + 能打单
    # B: 明细语义正常且能打单/建单，但客户名弱
    # D: 技术闭环能跑，但抽出内容业务语义不可信（误抽）
    # C: 只能拆，不能发货闭环
    # F: 连数据都不可用
    if data_ok and semantic_ok and unit_ok and create_ok and gen_ok:
        grade = "A"
    elif data_ok and semantic_ok and gen_ok:
        grade = "B"
    elif data_ok and gen_ok and not semantic_ok:
        grade = "D"
    elif data_ok or layout_ok:
        grade = "C"
    else:
        grade = "F"

    return {
        "file": path.name,
        "grade": grade,
        "preview_ok": bool((preview or {}).get("success")),
        "note_count": len(notes),
        "layout_cols": [h.get("name") for h in headers[:8]],
        "best_unit": (best or {}).get("unit_name"),
        "unit_ok": unit_ok,
        "semantic_ok": semantic_ok,
        "usable_items": len((best or {}).get("_usable_items") or []),
        "item_preview": [
            {
                "name": i.get("product_name") or i.get("name"),
                "model": i.get("model_number"),
                "qty": i.get("quantity_tins") or i.get("quantity"),
            }
            for i in ((best or {}).get("_usable_items") or [])[:3]
        ],
        "create_ok": create_ok,
        "shipment_created": exec_result.get("shipment_created"),
        "create_error": exec_result.get("error_code") or exec_result.get("message"),
        "generate_ok": gen_ok,
        "template_reason": ((gen_result.get("template_resolution") or {}).get("reason")),
        "usable": grade in {"A", "B"},
    }


def main() -> int:
    files = sorted(FORMS.glob("*.xlsx"))
    if CLOSED.is_file():
        files = [CLOSED, *files]

    rows = [_eval_one(p) for p in files]
    by = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
    for r in rows:
        by[r["grade"]] = by.get(r["grade"], 0) + 1

    report = {
        "summary": {
            "total": len(rows),
            "usable_ab": sum(1 for r in rows if r["usable"]),
            "tech_ok_but_bad_semantics": sum(1 for r in rows if r["grade"] == "D"),
            "grades": by,
        },
        "cases": rows,
    }
    out = FORMS / "usability_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"VERDICT usable(A/B)={report['summary']['usable_ab']}/{len(rows)} grades={by}")
    return 0 if report["summary"]["usable_ab"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
