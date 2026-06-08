#!/usr/bin/env python3
"""发货单审单 evidence — 写入样例事件并输出 JSON。"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
METRICS = ROOT / "metrics"


def main() -> int:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from app.db import engine
    from app.db.init_db import init_ai_business_evidence_tables
    from app.application.shipment_audit_app_service import ShipmentAuditAppService
    from app.infrastructure.persistence.shipment_audit_repository import ShipmentAuditRepository

    init_ai_business_evidence_tables(engine)
    svc = ShipmentAuditAppService(repository=ShipmentAuditRepository())

    samples = [
        svc.run_manual_audit(
            unit_name="Evidence单位A",
            items=[{"product_name": "产品1", "quantity_kg": 10, "amount": 100}],
            shipment_id=9001,
        ),
        svc.run_manual_audit(unit_name="", items=[], shipment_id=9002),
        svc.audit_from_ocr_text(
            "购货单位：Evidence单位B\nABC001 产品B 5 10.00 50.00",
            ocr_confidence=0.92,
            shipment_id=9003,
        ),
    ]

    counts = ShipmentAuditRepository().count_by_decision()
    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "samples": samples,
        "counts": counts,
    }
    METRICS.mkdir(parents=True, exist_ok=True)
    out = METRICS / f"shipment-audit-evidence-{datetime.now(timezone.utc).strftime('%Y%m%d')}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"evidence: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
