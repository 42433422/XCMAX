#!/usr/bin/env python3
"""拉取公开网络单据并跑 ETL preview / 模版 analyze 冒烟。

用法::

    cd FHD && .venv/bin/python scripts/dev/fetch_and_test_network_docs.py
"""

from __future__ import annotations

import json
import ssl
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "network_docs"
FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

DOWNLOADS = [
    (
        "net_delivery_order.xlsx",
        "https://raw.githubusercontent.com/GoodbyeKittyy/Delivery-Order-and-Invoice-Automated-Compiler/main/Delivery%20Order.xlsx",
    ),
    (
        "net_sample_xlsx_50.xlsx",
        "https://filesamples.com/samples/document/xlsx/sample3.xlsx",
    ),
]


def _download(url: str, dest: Path) -> bool:
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers={"User-Agent": "XCMAX-network-doc-test/1.0"})
        with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
            dest.write_bytes(resp.read())
        return dest.is_file() and dest.stat().st_size > 100
    except Exception as exc:  # noqa: BLE001 — 演示脚本容错
        print(f"download fail {url}: {exc}")
        return False


def main() -> int:
    for name, url in DOWNLOADS:
        dest = FIXTURE_DIR / name
        if dest.is_file() and dest.stat().st_size > 100:
            print(f"keep cached {name}")
            continue
        ok = _download(url, dest)
        print(f"{'ok' if ok else 'FAIL'} {name}")

    from app.application.shipment_excel_etl_app_service import preview_shipment_excel_etl
    from app.legacy.routes.document_templates_compat import run_archive_template_analyze

    rows = []
    for path in sorted(FIXTURE_DIR.glob("net_*.xlsx")):
        etl = preview_shipment_excel_etl(str(path))
        analyzed, code = run_archive_template_analyze(
            file_body=path.read_bytes(),
            filename=path.name,
            template_name=path.stem,
            template_scope="",
        )
        notes = etl.get("notes") if isinstance(etl, dict) else []
        first = notes[0] if isinstance(notes, list) and notes else {}
        rows.append(
            {
                "file": path.name,
                "bytes": path.stat().st_size,
                "etl_success": bool((etl or {}).get("success")),
                "etl_message": (etl or {}).get("message"),
                "etl_unit": (first or {}).get("unit_name"),
                "etl_items": (first or {}).get("item_count"),
                "analyze_code": code,
                "analyze_success": bool((analyzed or {}).get("success")),
                "analyze_type": (analyzed or {}).get("template_type"),
                "analyze_message": (analyzed or {}).get("message"),
            }
        )

    print(json.dumps({"cases": rows}, ensure_ascii=False, indent=2))
    ok_etl = sum(1 for r in rows if r["etl_success"])
    ok_an = sum(1 for r in rows if r["analyze_success"])
    print(f"SUMMARY etl_ok={ok_etl}/{len(rows)} analyze_ok={ok_an}/{len(rows)}")
    return 0 if rows and ok_etl > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
