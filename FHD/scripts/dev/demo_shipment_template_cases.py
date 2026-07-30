#!/usr/bin/env python3
"""自造打单案例：演练模版解析 → generate 用例编排。

用法（在 FHD 根目录）::

    .venv/bin/python scripts/dev/demo_shipment_template_cases.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.application.shipment_app_service import ShipmentApplicationService
from app.application.shipment_template_resolve import (
    clear_template_list_cache,
    resolve_shipment_template,
)


FIXTURE = ROOT / "tests/fixtures/shipment_etl/闭环测试_送货单模板.xlsx"


class _DocGen:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "success": True,
            "doc_name": f"{kwargs.get('unit_name')}_发货单.xlsx",
            "file_path": f"/tmp/{kwargs.get('unit_name')}_发货单.xlsx",
            "purchase_unit": kwargs.get("unit_name"),
            "unit_id": 1,
            "order_number": kwargs.get("order_number") or "SO-DEMO-001",
            "parsed_products": kwargs.get("products") or [],
        }


def _catalog(workdir: Path) -> list[dict]:
    """合成生产级模版库：客户专属 / 通用发货单 / 数据表 / 失效 / PDF。"""
    files = {
        "星光贸易发货单.xlsx": FIXTURE if FIXTURE.is_file() else None,
        "通用发货单.xlsx": FIXTURE if FIXTURE.is_file() else None,
        "产品目录导入.xlsx": FIXTURE if FIXTURE.is_file() else None,
        "旧版发货单.xlsx": FIXTURE if FIXTURE.is_file() else None,
        "说明书.pdf": None,
    }
    rows: list[dict] = []
    for idx, (name, src) in enumerate(files.items(), start=1):
        dest = workdir / name
        if src and src.is_file():
            shutil.copy2(src, dest)
        elif name.endswith(".pdf"):
            dest.write_bytes(b"%PDF-1.4 demo")
        else:
            dest.write_bytes(b"PK\x03\x04demo-xlsx")
        rows.append(
            {
                "id": f"db:{idx}",
                "db_id": idx,
                "name": Path(name).stem,
                "filename": name,
                "path": str(dest),
                "template_type": (
                    "产品目录"
                    if "产品" in name
                    else ("发货单" if name.endswith(".xlsx") else "PDF")
                ),
                "business_scope": "products" if "产品" in name else "",
                "source": "db",
                "is_active": 0 if "旧版" in name else 1,
            }
        )
    return rows


def _run_resolve_cases(store: MagicMock) -> list[dict]:
    cases = [
        {
            "title": "显式 template_id",
            "kwargs": {"template_id": "db:1", "unit_name": "星光贸易"},
        },
        {
            "title": "用户偏好名称",
            "kwargs": {"preferred": "通用发货单", "unit_name": "任意客户"},
        },
        {
            "title": "客户名命中专属模版",
            "kwargs": {"unit_name": "星光贸易有限公司", "intent": "shipment_generate"},
        },
        {
            "title": "意图默认（无客户专属）",
            "kwargs": {"unit_name": "七彩乐园", "intent": "shipment_generate"},
        },
        {
            "title": "数据表降权后仍选发货单",
            "kwargs": {"unit_name": "陌生客户", "intent": "shipment_generate"},
        },
        {
            "title": "strict 下无效 id 失败",
            "kwargs": {"template_id": "db:999", "strict": True},
        },
    ]
    results = []
    for case in cases:
        clear_template_list_cache()
        out = resolve_shipment_template(**case["kwargs"])
        results.append(
            {
                "case": case["title"],
                "ok": out.get("ok"),
                "reason": out.get("reason"),
                "source": out.get("source"),
                "template_id": out.get("template_id"),
                "template_name": out.get("template_name"),
                "error_code": out.get("error_code"),
                "path_basename": Path(str(out.get("path") or "")).name or None,
                "score": out.get("score"),
            }
        )
    return results


def _run_generate_cases(store: MagicMock, catalog: list[dict]) -> list[dict]:
    doc = _DocGen()
    svc = ShipmentApplicationService(repository=MagicMock(), document_generator=doc)
    products = [
        {"product_name": "PE白底漆", "model_number": "5003", "quantity_tins": 3, "tin_spec": 20}
    ]
    scenarios = [
        {
            "title": "空模版 → 按客户解析",
            "kwargs": {
                "unit_name": "星光贸易",
                "products": products,
                "order_number": "SO-XG-001",
            },
        },
        {
            "title": "偏好模版",
            "kwargs": {
                "unit_name": "七彩乐园",
                "products": products,
                "preferred_template": "通用发货单",
                "order_number": "SO-QC-001",
            },
        },
        {
            "title": "显式 template_id",
            "kwargs": {
                "unit_name": "星光贸易",
                "products": products,
                "template_id": "db:1",
                "order_number": "SO-ID-001",
            },
        },
        {
            "title": "strict 且库空 → 失败",
            "kwargs": {
                "unit_name": "无模版客户",
                "products": products,
                "strict_template": True,
            },
            "empty_store": True,
        },
        {
            "title": "缺产品 + allow_products_from_db",
            "kwargs": {
                "unit_name": "星光贸易",
                "products": [],
                "allow_products_from_db": True,
                "order_number": "SO-DB-001",
            },
            "orders": [
                {
                    "customer_name": "星光贸易",
                    "products": [{"name": "5003", "qty": 2}],
                }
            ],
        },
    ]
    out_rows = []
    for sc in scenarios:
        clear_template_list_cache()
        if sc.get("empty_store"):
            store.list_templates.return_value = []
            store.resolve_template_file.return_value = None
            store.resolve_template_file.side_effect = None
            store.get_default_for_type.return_value = None
            store.get_default_for_type.side_effect = None
        else:
            store.list_templates.return_value = catalog

            def _default_for_type(ttype: str, _catalog=catalog):
                return next(
                    (
                        r
                        for r in _catalog
                        if r["template_type"] == ttype and r.get("is_active", 1)
                    ),
                    None,
                )

            store.get_default_for_type.side_effect = _default_for_type
            store.get_default_for_type.return_value = None

            def _resolve(tid: str, _catalog=catalog):
                for r in _catalog:
                    if r["id"] == tid or str(r["db_id"]) == tid.replace("db:", ""):
                        return r["path"]
                return None

            store.resolve_template_file.side_effect = _resolve

        before = len(doc.calls)
        patches = [
            patch(
                "app.application.shipment_template_resolve.log_template_usage",
                return_value=None,
            ),
            patch(
                "app.application.shipment_template_resolve._log_template_usage",
                return_value=None,
            ),
            patch("app.bootstrap.get_shipment_app_service", return_value=svc),
        ]
        if sc.get("orders") is not None:
            patches.append(patch.object(svc, "get_orders", return_value=sc["orders"]))

        from contextlib import ExitStack

        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            result = svc.generate_shipment_document(**sc["kwargs"])
        call = doc.calls[before] if len(doc.calls) > before else None
        out_rows.append(
            {
                "case": sc["title"],
                "success": result.get("success"),
                "error_code": result.get("error_code"),
                "message": result.get("message"),
                "doc_name": result.get("doc_name"),
                "products_source": result.get("products_source"),
                "template_resolution": result.get("template_resolution"),
                "generator_template": (
                    Path(str(call.get("template_name") or "")).name if call else None
                ),
            }
        )
    return out_rows


def main() -> int:
    if not FIXTURE.is_file():
        print(f"[warn] fixture missing: {FIXTURE} （将用占位 xlsx）")

    with tempfile.TemporaryDirectory(prefix="shipment-tpl-demo-") as tmp:
        workdir = Path(tmp)
        catalog = _catalog(workdir)
        store = MagicMock()
        store.list_templates.return_value = catalog
        store.get_default_for_type.side_effect = lambda t: next(
            (r for r in catalog if r["template_type"] == t and r.get("is_active", 1)),
            None,
        )

        def _resolve(tid: str):
            for r in catalog:
                if r["id"] == tid or str(r["db_id"]) == tid.replace("db:", ""):
                    return r["path"]
            return None

        store.resolve_template_file.side_effect = _resolve

        with patch(
            "app.application.shipment_template_resolve._get_template_store",
            return_value=store,
        ), patch(
            "app.application.shipment_template_resolve.log_template_usage",
            return_value=None,
        ), patch(
            "app.application.shipment_template_resolve._log_template_usage",
            return_value=None,
        ):
            resolve_rows = _run_resolve_cases(store)
            generate_rows = _run_generate_cases(store, catalog)

    report = {
        "fixture": str(FIXTURE),
        "fixture_exists": FIXTURE.is_file(),
        "resolve_cases": resolve_rows,
        "generate_cases": generate_rows,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))

    resolve_ok = sum(1 for r in resolve_rows if r["ok"] is True)
    resolve_fail_expected = sum(
        1 for r in resolve_rows if r["case"].startswith("strict") and r["ok"] is False
    )
    gen_ok = sum(1 for r in generate_rows if r["success"] is True)
    gen_fail_expected = sum(
        1 for r in generate_rows if r["case"].startswith("strict") and r["success"] is False
    )

    print("\n=== SUMMARY ===")
    print(f"resolve: {resolve_ok} ok + {resolve_fail_expected} expected-fail / {len(resolve_rows)}")
    print(f"generate: {gen_ok} ok + {gen_fail_expected} expected-fail / {len(generate_rows)}")

    # 断言关键路径
    assert resolve_rows[0]["ok"] and resolve_rows[0]["template_id"] == "db:1"
    assert resolve_rows[2]["ok"] and "星光" in str(resolve_rows[2]["template_name"])
    assert resolve_rows[5]["ok"] is False and resolve_rows[5]["error_code"]
    assert generate_rows[0]["success"] and generate_rows[0]["template_resolution"]
    assert generate_rows[3]["success"] is False
    assert generate_rows[4]["success"] and generate_rows[4]["products_source"] == "db_latest_shipment"
    print("ALL DEMO ASSERTIONS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
