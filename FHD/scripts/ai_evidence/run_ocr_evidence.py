#!/usr/bin/env python3
"""OCR 单据结构化 evidence — 样例文本 + 审单决策。"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs" / "evidence"


def main() -> int:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from app.services.ocr_service import OCRService
    from app.application.shipment_audit_app_service import ShipmentAuditAppService
    from app.infrastructure.persistence.shipment_audit_repository import ShipmentAuditRepository
    from app.db import engine
    from app.db.init_db import init_ai_business_evidence_tables

    init_ai_business_evidence_tables(engine)
    sample_text = """
    购货单位：深圳市Evidence测试公司
    联系人：李四
    联系电话：13800138000
    订单编号：ORD202606050001
    ABC001 七彩涂料 10 100.00 1000.00
    合计：1000.00
    """
    svc = OCRService()
    t0 = time.perf_counter()
    structured = svc.extract_structured_data(sample_text)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    audit = ShipmentAuditAppService(repository=ShipmentAuditRepository()).audit_from_ocr(
        structured=structured,
        ocr_confidence=0.88,
        parse_ok=bool(structured.get("purchase_unit")),
    )

    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "text_preview": sample_text.strip()[:200],
        "structured_fields": structured,
        "confidence": 0.88,
        "latency_ms": latency_ms,
        "audit": audit,
    }
    out_dir = EVIDENCE / "ocr-shipment-audit"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"ocr-shipment-audit-{datetime.now(timezone.utc).strftime('%Y%m%d')}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"evidence: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
