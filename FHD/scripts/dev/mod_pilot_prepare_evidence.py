#!/usr/bin/env python3
"""Mod 试点前置：仅创建商家/管理员账号 + FHD JIT（禁止伪造支付入账）。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
SETUP = FHD_ROOT / "scripts" / "dev" / "mod_pilot_setup_merchant.py"


def main() -> int:
    return subprocess.call([sys.executable, str(SETUP)])


if __name__ == "__main__":
    raise SystemExit(main())
