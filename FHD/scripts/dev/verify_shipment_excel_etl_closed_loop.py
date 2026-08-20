#!/usr/bin/env python3
"""生成送货单/出货流水测试模板，并跑 ETL 闭环自检。

用法：
  cd FHD && .venv/bin/python scripts/dev/verify_shipment_excel_etl_closed_loop.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from app.application.shipment_excel_etl_app_service import (
        batch_execute_shipment_excel_etl,
        batch_preview_shipment_excel_etl,
        execute_shipment_excel_etl,
        parse_delivery_notes,
        regenerate_delivery_notes_from_file,
        write_delivery_note_workbook,
        write_ledger_workbook,
    )

    out_root = ROOT / "tests" / "fixtures" / "shipment_etl"
    out_root.mkdir(parents=True, exist_ok=True)

    delivery_path = out_root / "闭环测试_送货单模板.xlsx"
    ledger_path = out_root / "闭环流水客户.xlsx"
    regen_path = out_root / "闭环测试_反推再出单.xlsx"
    report_path = out_root / "closed_loop_report.json"

    delivery_notes = [
        {
            "unit_name": "闭环测试客户甲",
            "contact_person": "王工",
            "order_date": "2026年07月24日",
            "order_number": "LOOP-1001",
            "sheet": "送货甲",
            "items": [
                {
                    "model_number": "RX-LOOP",
                    "product_name": "PU哑光清漆",
                    "quantity_tins": 2,
                    "tin_spec": 25,
                    "quantity_kg": 50,
                    "unit_price": 18,
                    "amount": 900,
                },
                {
                    "model_number": "GS621",
                    "product_name": "PE白底漆",
                    "quantity_tins": 1,
                    "tin_spec": 28,
                    "quantity_kg": 28,
                    "unit_price": 8.5,
                    "amount": 238,
                },
            ],
        },
        {
            "unit_name": "闭环测试客户乙",
            "contact_person": "李总",
            "order_date": "2026年07月24日",
            "order_number": "LOOP-1002",
            "sheet": "送货乙",
            "items": [
                {
                    "model_number": "6821A",
                    "product_name": "白底",
                    "quantity_tins": 3,
                    "tin_spec": 20,
                    "quantity_kg": 60,
                    "unit_price": 12,
                    "amount": 720,
                }
            ],
        },
    ]

    steps: list[dict] = []

    w1 = write_delivery_note_workbook(delivery_notes, delivery_path)
    steps.append({"step": "generate_delivery_template", **w1})
    w2 = write_ledger_workbook([], ledger_path, unit_name="闭环流水客户")
    steps.append({"step": "generate_ledger_template", **w2})

    parsed = parse_delivery_notes(delivery_path, include_ledger=False)
    steps.append(
        {
            "step": "parse_delivery",
            "success": parsed.get("success"),
            "note_count": parsed.get("note_count"),
            "units": [n.get("unit_name") for n in (parsed.get("notes") or [])],
        }
    )

    ledger_parsed = parse_delivery_notes(
        ledger_path, include_ledger=True, unit_name_hint="闭环流水客户"
    )
    steps.append(
        {
            "step": "parse_ledger",
            "success": ledger_parsed.get("success"),
            "note_count": ledger_parsed.get("note_count"),
            "orders": [n.get("order_number") for n in (ledger_parsed.get("notes") or [])],
        }
    )

    regen = regenerate_delivery_notes_from_file(delivery_path, regen_path, include_ledger=False)
    steps.append(
        {
            "step": "regenerate_roundtrip",
            "success": regen.get("success"),
            "fingerprint_match": regen.get("fingerprint_match"),
            "output": str(regen_path),
        }
    )

    # 用临时指纹库 + fake shipment，避免污染真实库
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        batch_dir = td_path / "batch"
        batch_dir.mkdir()
        (batch_dir / delivery_path.name).write_bytes(delivery_path.read_bytes())
        (batch_dir / ledger_path.name).write_bytes(ledger_path.read_bytes())

        import app.application.shipment_excel_etl_fingerprint_store as fp_store

        fp_store._legacy_db_path = lambda: td_path / "fps.sqlite3"  # type: ignore
        fp_store._db_path = lambda: td_path / "fps.sqlite3"  # type: ignore
        os.environ["FHD_SHIPMENT_ETL_FINGERPRINT_BACKEND"] = "legacy"

        class _FakeShipmentSvc:
            def __init__(self):
                self.created = []

            def create_shipment(self, unit_name, items_data, contact_person="", **kwargs):
                sid = len(self.created) + 1
                self.created.append(
                    {
                        "id": sid,
                        "unit_name": unit_name,
                        "items": items_data,
                        "contact": contact_person,
                        **kwargs,
                    }
                )
                return {"success": True, "shipment": {"id": sid}}

        fake = _FakeShipmentSvc()
        import app.bootstrap as bootstrap

        bootstrap.get_shipment_app_service = lambda: fake  # type: ignore

        import app.services.tools_workflow_registered as tw

        tw._execute_excel_import_records = lambda records: {  # type: ignore
            "success": True,
            "imported": len(records),
        }

        os.environ["WORKSPACE_ROOT"] = str(td_path)
        os.environ["FHD_SHIPMENT_ETL_ALLOW_BATCH"] = "1"
        os.environ["FHD_SHIPMENT_ETL_ALLOW_TMP"] = "1"

        preview = batch_preview_shipment_excel_etl(batch_dir, workspace_root=td_path)
        # 默认不入库流水；仅送货单
        first = batch_execute_shipment_excel_etl(
            batch_dir,
            idempotent=True,
            include_ledger=False,
            workspace_root=td_path,
        )
        second = batch_execute_shipment_excel_etl(
            batch_dir,
            idempotent=True,
            include_ledger=False,
            workspace_root=td_path,
        )
        dry = execute_shipment_excel_etl(
            delivery_path,
            dry_run=True,
            workspace_root=ROOT,
        )
        single = execute_shipment_excel_etl(
            delivery_path,
            idempotent=True,
            workspace_root=ROOT,
        )

        steps.append(
            {
                "step": "batch_preview",
                "success": preview.get("success"),
                "file_count": preview.get("file_count"),
                "note_count": preview.get("note_count"),
            }
        )
        steps.append(
            {
                "step": "batch_execute_first",
                "success": first.get("success"),
                "shipment_created": first.get("shipment_created"),
                "shipment_skipped": first.get("shipment_skipped"),
                "fake_created": len(fake.created),
            }
        )
        steps.append(
            {
                "step": "batch_execute_second_idempotent",
                "success": second.get("success"),
                "shipment_created": second.get("shipment_created"),
                "shipment_skipped": second.get("shipment_skipped"),
                "fake_created": len(fake.created),
            }
        )
        steps.append(
            {
                "step": "dry_run",
                "success": dry.get("success"),
                "dry_run": dry.get("dry_run"),
                "would_create": dry.get("would_create"),
            }
        )
        steps.append(
            {
                "step": "single_execute_after_batch",
                "success": single.get("success"),
                "shipment_created": single.get("shipment_created"),
                "shipment_skipped": single.get("shipment_skipped"),
            }
        )

    ok = all(
        [
            w1.get("success"),
            w2.get("success"),
            parsed.get("note_count", 0) >= 2,
            ledger_parsed.get("note_count", 0) >= 2,
            regen.get("fingerprint_match"),
            preview.get("note_count", 0) >= 2,
            first.get("shipment_created", 0) >= 2,
            second.get("shipment_created", 0) == 0,
            second.get("shipment_skipped", 0) >= 2,
            dry.get("dry_run") is True,
        ]
    )
    report = {
        "success": bool(ok),
        "fixtures_dir": str(out_root),
        "steps": steps,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    # 不向 stdout 打印绝对路径/fixtures，避免 CI CodeQL clear-text-logging
    print(json.dumps({"success": bool(ok), "report": str(report_path.name)}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
