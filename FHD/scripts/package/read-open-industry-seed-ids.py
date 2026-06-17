# -*- coding: utf-8 -*-
"""输出 onboarding_open 行业对应的 mod_id（JSON 数组），供 stage-industry-seeds.ps1 调用。"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_baseline() -> dict:
    path = ROOT / "config" / "industry_baseline.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"industry baseline not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid industry baseline JSON: {path}: {exc}") from exc


def main() -> None:
    doc = _load_baseline()
    packages = doc.get("industry_packages")
    if not isinstance(packages, dict):
        packages = {}
    seen: set[str] = set()
    ids: list[str] = []
    for raw_industry in doc.get("onboarding_open_industry_ids") or []:
        industry_id = str(raw_industry or "").strip()
        row = packages.get(industry_id)
        if not isinstance(row, dict):
            continue
        mod_id = str(row.get("mod_id") or "").strip()
        if mod_id and mod_id not in seen:
            seen.add(mod_id)
            ids.append(mod_id)
    print(json.dumps(ids, ensure_ascii=False))


if __name__ == "__main__":
    main()
