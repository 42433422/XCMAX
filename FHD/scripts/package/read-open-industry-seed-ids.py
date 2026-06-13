# -*- coding: utf-8 -*-
"""输出 onboarding_open 行业对应的 mod_id（JSON 数组），供 stage-industry-seeds.ps1 调用。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.mod_sdk.industry_seed import open_industry_seed_mod_ids  # noqa: E402


def main() -> None:
    ids = open_industry_seed_mod_ids()
    print(json.dumps(ids, ensure_ascii=False))


if __name__ == "__main__":
    main()
