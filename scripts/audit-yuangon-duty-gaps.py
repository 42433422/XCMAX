#!/usr/bin/env python3
"""输出 yuangon 编制 vs YAML 对齐及工作流 Mod 清单（不扫描全仓）。"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_BUILD = ROOT / "scripts" / "build-xcmax-tree-data.py"
_OUT = ROOT / ".cache" / "xcmax" / "xcmax-yuangon-duty-gaps.json"


def _load_build_module():
    spec = importlib.util.spec_from_file_location("build_xcmax_tree_data", _BUILD)
    if not spec or not spec.loader:
        raise RuntimeError("cannot load build-xcmax-tree-data.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    mod = _load_build_module()
    report = mod.audit_yuangon_duty_gaps()
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nWrote {_OUT}", file=sys.stderr)
    return 0 if report.get("yaml_aligned") else 1


if __name__ == "__main__":
    raise SystemExit(main())
