#!/usr/bin/env python3
"""将 FHD 本地 JSON 订单只读导出，供导入 MODstore PostgreSQL（需配合市场侧 import API）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    store = _REPO / "data" / "model_payment_orders.json"
    if not store.is_file():
        print("no local order store found", file=sys.stderr)
        return 0
    rows = json.loads(store.read_text(encoding="utf-8"))
    if not isinstance(rows, dict):
        print("unexpected format", file=sys.stderr)
        return 1
    out = _REPO / "data" / "exports" / "fhd_orders_for_modstore.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"exported {len(rows)} orders to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
