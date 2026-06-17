# -*- coding: utf-8 -*-
"""输出指定 SKU 的 package_stage_ids（JSON 数组），供 PowerShell stage 脚本调用。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"host profile not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid host profile JSON: {path}: {exc}") from exc


def main() -> None:
    sku = (sys.argv[1] if len(sys.argv) > 1 else "enterprise").strip().lower()
    if sku not in {"personal", "enterprise"}:
        raise SystemExit(f"invalid SKU: {sku}")
    profile = _load_json(ROOT / "config" / "host_profiles" / f"{sku}.json")
    raw = profile.get("package_stage_ids") or profile.get("sku_bundled_mod_ids") or []
    ids = [str(item).strip() for item in raw if str(item).strip()]
    print(json.dumps(ids, ensure_ascii=False))


if __name__ == "__main__":
    main()
