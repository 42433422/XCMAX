#!/usr/bin/env python3
"""Find minimal test prefix that breaks test_materials (setup ERROR)."""
from __future__ import annotations

import sys

import pytest

TARGET = "tests/test_routes/test_materials.py::test_add_material_success"


class Collect:
    items: list = []

    def pytest_collection_modifyitems(self, config, items):
        Collect.items = list(items)


class MatResult:
    error = False

    def pytest_runtest_logreport(self, report):
        if report.nodeid != TARGET:
            return
        if report.when != "setup":
            return
        if report.failed:
            MatResult.error = True


def materials_ok(prefix_len: int) -> bool:
    MatResult.error = False
    nodeids = [it.nodeid for it in Collect.items[:prefix_len]] + [TARGET]
    pytest.main(nodeids + ["-q", "--tb=no"], plugins=[MatResult()])
    return not MatResult.error


def main() -> int:
    pytest.main(["tests/", "--collect-only", "-q"], plugins=[Collect()])
    idx = next(i for i, it in enumerate(Collect.items) if it.nodeid == TARGET)
    print(f"target index {idx} / {len(Collect.items)}", flush=True)

    lo, hi = 0, idx
    while lo < hi:
        mid = (lo + hi) // 2
        ok = materials_ok(mid)
        print(f"prefix {mid}: ok={ok}", flush=True)
        if ok:
            lo = mid + 1
        else:
            hi = mid

    print(f"minimal breaking prefix: {lo}", flush=True)
    if lo < len(Collect.items):
        print(f"first test after ok prefix: {Collect.items[lo].nodeid}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
