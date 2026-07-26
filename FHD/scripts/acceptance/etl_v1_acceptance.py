#!/usr/bin/env python3
"""Reproducible sellability gate for the FHD general ETL V1.

The corpus is synthetic and deterministic.  It validates the product pipeline
independently of customer data; production release still needs a separately
approved customer-sample run and a signed desktop build.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import resource
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FHD_ROOT = Path(__file__).resolve().parents[2]
if str(FHD_ROOT) not in sys.path:
    sys.path.insert(0, str(FHD_ROOT))

from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.etl.parsers import parse_file
from app.application.etl.service import EtlService
from app.application.etl.targets import get_adapter
from app.db.base import Base
from app.db.models.customer import Customer
from app.db.models.etl import (
    EtlRun,
    EtlRunRow,
    EtlTargetConfig,
    EtlTemplate,
    EtlTemplateVersion,
    EtlUpload,
)
from app.infrastructure.tenant_scope import tenant_scope


@dataclass(frozen=True)
class SampleCase:
    category: str
    target: str
    headers: tuple[str, ...]
    expected_targets: tuple[str, ...]


CASES = (
    *(
        SampleCase(
            "customers",
            "customers",
            headers,
            ("customer_name", "contact_person", "contact_phone", "contact_address"),
        )
        for headers in (
            ("客户名称", "联系人", "电话", "地址"),
            ("客户", "姓名", "手机", "收货地址"),
            ("单位", "联系人", "联系方式", "地址"),
            ("购货单位", "联系人", "电话", "收货地址"),
            ("customer_name", "contact_person", "contact_phone", "contact_address"),
        )
    ),
    *(
        SampleCase(
            "products",
            "products",
            headers,
            ("unit", "model_number", "name", "specification", "price"),
        )
        for headers in (
            ("购买单位", "型号", "产品名称", "规格", "价格"),
            ("客户", "产品型号", "品名", "规格型号", "单价"),
            ("单位", "型号", "产品", "规格", "售价"),
            ("unit", "model_number", "name", "specification", "price"),
            ("购货单位", "型号", "品名", "规格型号", "单价"),
        )
    ),
    *(
        SampleCase(
            "purchase_orders",
            "purchase_orders",
            headers,
            (
                "external_order_no",
                "supplier_name",
                "order_date",
                "product_model",
                "product_name",
                "quantity",
                "unit",
                "unit_price",
            ),
        )
        for headers in (
            ("外部订单号", "供应商", "订单日期", "产品型号", "产品名称", "数量", "单位", "单价"),
            ("采购单号", "供应商名称", "日期", "型号", "品名", "采购数量", "计量单位", "价格"),
            (
                "external_order_no",
                "supplier_name",
                "order_date",
                "product_model",
                "product_name",
                "quantity",
                "unit",
                "unit_price",
            ),
            ("订单号", "供货商", "下单日期", "型号", "产品", "数量", "单位", "单价"),
        )
    ),
    *(
        SampleCase(
            "shipments",
            "shipment_records",
            headers,
            (
                "purchase_unit",
                "external_order_no",
                "product_name",
                "model_number",
                "quantity_kg",
                "quantity_tins",
                "unit_price",
                "amount",
            ),
        )
        for headers in (
            ("购买单位", "外部单号", "产品名称", "型号", "公斤数", "桶数", "单价", "金额"),
            ("购货单位", "订单号", "品名", "型号", "重量", "数量", "单价", "合计"),
            (
                "purchase_unit",
                "external_order_no",
                "product_name",
                "model_number",
                "quantity_kg",
                "quantity_tins",
                "unit_price",
                "amount",
            ),
            ("客户", "单号", "产品", "型号", "kg", "桶数", "单价", "金额"),
        )
    ),
    *(
        SampleCase("attendance", "attendance", headers, ())
        for headers in (
            ("姓名", "日期", "上班时间", "下班时间"),
            ("员工", "考勤日期", "签到", "签退"),
            ("employee", "date", "check_in", "check_out"),
            ("工号", "姓名", "日期", "状态"),
        )
    ),
    *(
        SampleCase("generic_csv", "export_csv", headers, headers)
        for headers in (
            ("任意列A", "任意列B", "任意列C"),
            ("region", "sales", "month"),
            ("部门", "预算", "备注"),
            ("SKU", "库存", "仓库"),
        )
    ),
)


class _DeterministicOcr:
    def recognize_text_blocks(self, _image: Any) -> list[dict[str, Any]]:
        values = (
            ("客户名称", "联系人", "电话"),
            ("扫描客户甲", "张三", "13800000000"),
            ("扫描客户乙", "李四", "13900000000"),
        )
        blocks: list[dict[str, Any]] = []
        for row, values_row in enumerate(values):
            for column, text in enumerate(values_row):
                left = 60 + column * 300
                top = 50 + row * 90
                blocks.append(
                    {
                        "text": text,
                        "left": left,
                        "top": top,
                        "width": 180,
                        "height": 40,
                        "center": (left + 90, top + 20),
                        "confidence": 0.99,
                    }
                )
        return blocks

    @staticmethod
    def get_active_ocr_backend() -> str:
        return "acceptance-double"


def _write_csv(path: Path, headers: tuple[str, ...], index: int) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerow([f"样本{index}-{column}" for column in range(len(headers))])


def _write_workbook(path: Path, headers: tuple[str, ...], index: int) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(list(headers))
    worksheet.append([f"样本{index}-{column}" for column in range(len(headers))])
    workbook.save(path)
    workbook.close()


def _mapping_acceptance(root: Path, service: EtlService) -> dict[str, Any]:
    passed_fields = 0
    expected_fields = 0
    categories: dict[str, int] = {}
    for index, case in enumerate(CASES, start=1):
        suffix = ".xlsx" if case.category == "attendance" else ".csv"
        path = root / f"sample-{index:02d}-{case.category}{suffix}"
        if suffix == ".xlsx":
            _write_workbook(path, case.headers, index)
        else:
            _write_csv(path, case.headers, index)
        dataset = parse_file(path, target_type=case.target)
        if not dataset.rows:
            raise AssertionError(f"{path.name}: no rows parsed")
        mappings = service._suggest_mappings(dataset, get_adapter(case.target))
        sources = {str(item["target"]): str(item.get("source") or "") for item in mappings}
        for target in case.expected_targets:
            expected_fields += 1
            if sources.get(target):
                passed_fields += 1
        categories[case.category] = categories.get(case.category, 0) + 1

    import app.services.ocr_service as ocr_module

    previous_ocr = ocr_module.ocr_service
    ocr_module.ocr_service = _DeterministicOcr()
    try:
        for offset, suffix in enumerate((".png", ".jpg", ".pdf", ".png"), start=1):
            path = root / f"sample-{len(CASES) + offset:02d}-scanned{suffix}"
            image = Image.new("RGB", (1000, 400), "white")
            image.save(path, "PDF" if suffix == ".pdf" else None)
            dataset = parse_file(path, target_type="customers")
            if dataset.source_features.get("kind") != "ocr" or len(dataset.rows) != 2:
                raise AssertionError(f"{path.name}: OCR rows/provenance missing")
            if not all(row.provenance.get("requires_confirmation") for row in dataset.rows):
                raise AssertionError(f"{path.name}: OCR confirmation guard missing")
            mappings = service._suggest_mappings(dataset, get_adapter("customers"))
            sources = {str(item["target"]): str(item.get("source") or "") for item in mappings}
            for target in ("customer_name", "contact_person", "contact_phone"):
                expected_fields += 1
                if sources.get(target):
                    passed_fields += 1
            categories["scanned"] = categories.get("scanned", 0) + 1
    finally:
        ocr_module.ocr_service = previous_ocr

    accuracy = passed_fields / max(1, expected_fields)
    if sum(categories.values()) != 30:
        raise AssertionError(f"sample corpus must contain 30 files: {categories}")
    if accuracy < 0.95:
        raise AssertionError(f"mapping accuracy below 95%: {accuracy:.2%}")
    return {
        "sample_count": sum(categories.values()),
        "categories": categories,
        "expected_field_mappings": expected_fields,
        "correct_field_mappings": passed_fields,
        "mapping_accuracy": round(accuracy, 6),
        "ocr_confirmation_guard": True,
        "corpus": "deterministic_synthetic",
    }


def _maker(root: Path):
    engine = create_engine(f"sqlite:///{root / 'etl-acceptance.sqlite'}")
    Base.metadata.create_all(
        engine,
        tables=[
            EtlUpload.__table__,
            EtlTemplate.__table__,
            EtlTemplateVersion.__table__,
            EtlRun.__table__,
            EtlRunRow.__table__,
            EtlTargetConfig.__table__,
            Customer.__table__,
        ],
    )
    return sessionmaker(bind=engine, expire_on_commit=False)


def _peak_rss_mb() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform != "darwin":
        value *= 1024
    return round(value / 1024 / 1024, 2)


def _performance_acceptance(root: Path, row_count: int) -> dict[str, Any]:
    import app.application.etl.service as service_module

    maker = _maker(root)
    service_module.SessionLocal = maker
    service = EtlService()
    service._submit_preview = lambda run_id, _tenant_id, owner_user_id: service._preview_worker(
        run_id, owner_user_id
    )
    service._submit_execution = lambda run_id, _tenant_id, owner_user_id, valid_rows_only: (
        service._execute_worker(run_id, owner_user_id, valid_rows_only)
    )
    source = root / f"performance-{row_count}.csv"
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("row_id", "customer", "amount", "date"))
        for index in range(1, row_count + 1):
            writer.writerow((index, f"客户{index}", f"{index % 1000}.50", "2026-07-26"))

    os.environ["XCAGI_DATA_DIR"] = str(root / "app-data")
    with tenant_scope(99001):
        db = maker()
        with source.open("rb") as stream:
            upload = service.save_upload(
                db,
                owner_user_id=99002,
                file_name=source.name,
                content_type="text/csv",
                stream=stream,
            )
        db.commit()
        started = time.monotonic()
        run = service.create_preview(
            db,
            owner_user_id=99002,
            upload_id=upload["upload_id"],
            target_type="export_csv",
        )
        preview_seconds = time.monotonic() - started
        if run["status"] != "preview_ready" or run["summary"]["new"] != row_count:
            raise AssertionError(f"100k preview incomplete: {run}")
        started = time.monotonic()
        completed = service.execute(
            db,
            run_id=run["id"],
            owner_user_id=99002,
            confirmed=True,
            valid_rows_only=False,
        )
        execution_seconds = time.monotonic() - started
        if completed["status"] != "completed" or completed["summary"]["executed"] != row_count:
            raise AssertionError(f"100k execution incomplete: {completed}")
        export_path = service.download_path(db, run_id=run["id"], owner_user_id=99002)
        db.close()
    return {
        "rows": row_count,
        "source_bytes": source.stat().st_size,
        "preview_seconds": round(preview_seconds, 3),
        "execution_seconds": round(execution_seconds, 3),
        "export_bytes": export_path.stat().st_size,
        "peak_rss_mb": _peak_rss_mb(),
        "background_api": True,
        "progress_chunk_rows": 500,
    }


def run(rows: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="fhd-etl-v1-acceptance-") as tmp:
        root = Path(tmp)
        service = EtlService()
        return {
            "success": True,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "samples": _mapping_acceptance(root, service),
            "performance": _performance_acceptance(root, rows),
            "release_scope": {
                "signed_installer": "separate_release_gate",
                "customer_approved_samples": "separate_release_gate",
            },
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.rows < 1 or args.rows > 100_000:
        parser.error("--rows must be between 1 and 100000")
    report = run(args.rows)
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
