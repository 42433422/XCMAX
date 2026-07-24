#!/usr/bin/env python3
"""送货单 ETL 生产就绪验收：跑门禁测试并输出结论。

用法：
  cd FHD && .venv/bin/python scripts/dev/assert_shipment_etl_production_ready.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    cmd = [
        str(ROOT / ".venv" / "bin" / "python"),
        "-m",
        "pytest",
        "tests/test_application/test_shipment_excel_etl_production_ready.py",
        "tests/test_application/test_shipment_excel_etl_app_service.py",
        "-q",
        "--tb=line",
    ]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    ok = proc.returncode == 0
    report = {
        "success": ok,
        "verdict": "PRODUCTION_READY_FOR_CONTROLLED_ROLLOUT" if ok else "NOT_READY",
        "pytest_returncode": proc.returncode,
        "stdout_tail": "\n".join((proc.stdout or "").splitlines()[-20:]),
        "stderr_tail": "\n".join((proc.stderr or "").splitlines()[-20:]),
        "gates": [
            "path_sandbox",
            "auth_on_write_routes",
            "tenant_fingerprint_unique",
            "idempotent_immediate_persist",
            "ledger_confirm_required",
            "dry_run",
            "compensate_on_failure",
            "external_order_meta",
            "batch_disabled_by_default",
            "production_rbac_default_on_prod_env",
        ],
        "notes": [
            "客户/产品导入与发货单写入仍非同一 DB 事务；发货单失败会补偿撤销本批发货单。",
            "生产/预发默认要求登录 + shipment.create；桌面开发可设 FHD_SHIPMENT_ETL_REQUIRE_RBAC=0。",
            "批量入库默认关闭，需 FHD_SHIPMENT_ETL_ALLOW_BATCH=1。",
            "上线前请执行 alembic upgrade 到 2026_07_24_shipment_etl_fingerprints。",
        ],
    }
    out = ROOT / "tests" / "fixtures" / "shipment_etl" / "production_ready_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
