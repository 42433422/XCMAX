#!/usr/bin/env python3
# mypy: disable-error-code="index"
"""多类型表单：测试能否分离「版式/模版」与「业务数据」。

用法::

    cd FHD && .venv/bin/python scripts/dev/test_form_template_data_separation.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.utils.operational_errors import BOUNDARY_ERRORS

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "network_forms"


def _score(decomp: dict, etl: dict, analyzed: dict) -> dict:
    dec = (decomp or {}).get("decomposition") or {}
    headers = dec.get("editable_entries") or []
    samples = dec.get("sample_rows") or []
    notes = (etl or {}).get("notes") if isinstance(etl, dict) else []
    first = notes[0] if isinstance(notes, list) and notes else {}
    items = first.get("items") or []
    fields = (analyzed or {}).get("fields") or []

    has_layout = bool(headers) or bool(fields) or bool(dec.get("header_row"))
    has_data = bool(samples) or bool(items)
    separated = has_layout and has_data and (len(headers) >= 2 or len(fields) >= 2)

    # 质量分级：A=表头像列名且有明细；B=能拆但表头可能是抬头行；C=仅一侧
    header_names = [str(h.get("name") or "") for h in headers]
    metaish = sum(
        1
        for n in header_names
        if n.lower().rstrip(":") in {"to", "from", "invoice no", "do no", "单据编号", "客户名称"}
        or n.endswith(":")
    )
    quality = "C"
    if separated and metaish >= 2:
        quality = "B"
    elif separated:
        quality = "A"
    elif has_layout or has_data:
        quality = "C"
    else:
        quality = "F"

    return {
        "separated": separated,
        "quality": quality,
        "has_layout": has_layout,
        "has_data": has_data,
        "headers": header_names[:10],
        "header_row": dec.get("header_row"),
        "sample_rows": len(samples),
        "etl_unit": first.get("unit_name"),
        "etl_items": first.get("item_count") or len(items),
        "etl_kind": first.get("source_kind"),
        "layout_fp": ((first.get("assist") or {}).get("layout_fingerprint")),
        "analyze_ok": bool((analyzed or {}).get("success")),
        "analyze_fields": len(fields),
    }


def main() -> int:
    from app.application.excel_template_http_app_service import _decompose_template
    from app.application.shipment_excel_etl_app_service import preview_shipment_excel_etl
    from app.legacy.routes.document_templates_compat import run_archive_template_analyze

    files = sorted(FIXTURE_DIR.glob("*.xlsx"))
    if not files:
        print("no fixtures in", FIXTURE_DIR)
        return 1

    cases = []
    for path in files:
        decomp, _ = _decompose_template(str(path), sample_rows=3)
        try:
            etl = preview_shipment_excel_etl(str(path))
        except BOUNDARY_ERRORS as exc:  # noqa: BLE001
            etl = {"success": False, "message": str(exc), "notes": []}
        try:
            analyzed, _code = run_archive_template_analyze(
                file_body=path.read_bytes(),
                filename=path.name,
                template_name=path.stem,
            )
        except BOUNDARY_ERRORS as exc:  # noqa: BLE001
            analyzed = {"success": False, "message": str(exc)}
        scored = _score(decomp, etl, analyzed)
        cases.append({"file": path.name, **scored})

    by_q = {"A": 0, "B": 0, "C": 0, "F": 0}
    for c in cases:
        by_q[c["quality"]] = by_q.get(c["quality"], 0) + 1
    report = {
        "summary": {
            "total": len(cases),
            "separated": sum(1 for c in cases if c["separated"]),
            "quality": by_q,
        },
        "cases": cases,
    }
    out = FIXTURE_DIR / "separation_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"VERDICT separated={report['summary']['separated']}/{len(cases)} quality={by_q}")
    return 0 if report["summary"]["separated"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
