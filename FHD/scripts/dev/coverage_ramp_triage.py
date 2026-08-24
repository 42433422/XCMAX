#!/usr/bin/env python3
"""coverage_ramp stub 分诊：逐 stub 独立测量覆盖率，与行为基线做集合差，输出三桶分流。

每个 stub 文件单独跑一次 pytest + coverage(json)，计算其相对行为套件
（coverage-behavior.json）的**独有覆盖行/分支**（stub 覆盖 − 行为已覆盖），据此分桶：

* ``delete``  ：独有行=0 且独有分支=0 → 覆盖已被行为套件兜底，可直接删除
* ``convert`` ：独有行>=15 或 独有分支>=8 → 高价值，转正为 test_<module>_behavior.py
* ``smoke``   ：其余碎价值 → 合并进 test_import_smoke.py
* ``needs_review``：独立运行失败且无覆盖产物 → 人工判读

产物 ``metrics/coverage_ramp_triage.json`` 含每文件明细 + 全量并集自检值
（union_unique_lines 应 ≈ 全量口径与行为口径的覆盖差 4,937，±10% 容忍）。

用法::

    python scripts/dev/coverage_ramp_triage.py              # 全量 72 个，4 worker
    python scripts/dev/coverage_ramp_triage.py --workers 8 --timeout 900
    python scripts/dev/coverage_ramp_triage.py --only tests/test_coverage_ramp_routes.py
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
BEHAVIOR_JSON = FHD_ROOT / "coverage-behavior.json"
OUT_JSON = FHD_ROOT / "metrics" / "coverage_ramp_triage.json"
STUB_PREFIX = "test_coverage_ramp_"

CONVERT_LINE_THRESHOLD = 15
CONVERT_BRANCH_THRESHOLD = 8


def list_stubs() -> list[Path]:
    """与 count_coverage_ramp_stubs.py / conftest 打标口径严格一致。"""
    return sorted(
        p
        for p in (FHD_ROOT / "tests").rglob(f"{STUB_PREFIX}*.py")
        if "__pycache__" not in p.parts and p.name.startswith(STUB_PREFIX)
    )


def load_behavior_covered() -> dict[str, dict[str, set[int]]]:
    """行为基线：file -> {lines: set, branches: set}。"""
    data = json.loads(BEHAVIOR_JSON.read_text(encoding="utf-8"))
    covered: dict[str, dict[str, set[int]]] = {}
    for fname, fdata in data.get("files", {}).items():
        covered[fname] = {
            "lines": set(fdata.get("executed_lines", [])),
            "branches": {tuple(b) for b in fdata.get("executed_branches", [])},
        }
    return covered


def measure_stub(stub: Path, timeout: int) -> dict:
    """独立跑一个 stub，返回其覆盖明细（相对行为基线的差集在 analyze 阶段算）。"""
    rel = stub.relative_to(FHD_ROOT).as_posix()
    with tempfile.TemporaryDirectory(prefix="ramp_triage_") as td:
        cov_json = Path(td) / "cov.json"
        # COVERAGE_FILE 隔离：并行 worker 共享 cwd，默认 .coverage 数据文件会互相覆盖
        env = dict(
            os.environ,
            XCAGI_SKIP_LEGACY_COMPAT_ROUTES="1",
            COVERAGE_FILE=str(Path(td) / ".coverage"),
        )
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            rel,
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
            "--cov",
            "--cov-branch",
            f"--cov-report=json:{cov_json}",
            "--cov-fail-under=0",
        ]
        try:
            proc = subprocess.run(
                cmd,
                cwd=FHD_ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {"file": rel, "status": "timeout", "rc": None, "files": {}}
        if not cov_json.is_file():
            tail = (proc.stdout + proc.stderr)[-500:]
            return {
                "file": rel,
                "status": "no_coverage",
                "rc": proc.returncode,
                "files": {},
                "tail": tail,
            }
        data = json.loads(cov_json.read_text(encoding="utf-8"))
        files = {}
        for fname, fdata in data.get("files", {}).items():
            files[fname] = {
                "lines": set(fdata.get("executed_lines", [])),
                "branches": {tuple(b) for b in fdata.get("executed_branches", [])},
            }
        return {"file": rel, "status": "ok", "rc": proc.returncode, "files": files}


def analyze(measured: list[dict], behavior: dict[str, dict[str, set[int]]]) -> list[dict]:
    """计算独有覆盖并分桶。"""
    results = []
    for m in measured:
        if m["status"] != "ok":
            results.append(
                {
                    **{k: v for k, v in m.items() if k != "files"},
                    "bucket": "needs_review",
                    "unique_lines": 0,
                    "unique_branches": 0,
                }
            )
            continue
        u_lines = 0
        u_branches = 0
        touched: dict[str, int] = {}
        for fname, cov in m["files"].items():
            base = behavior.get(fname, {"lines": set(), "branches": set()})
            dl = cov["lines"] - base["lines"]
            db = cov["branches"] - base["branches"]
            u_lines += len(dl)
            u_branches += len(db)
            if dl:
                touched[fname] = len(dl)
        top = sorted(touched.items(), key=lambda kv: -kv[1])[:5]
        if u_lines == 0 and u_branches == 0:
            bucket = "delete"
        elif u_lines >= CONVERT_LINE_THRESHOLD or u_branches >= CONVERT_BRANCH_THRESHOLD:
            bucket = "convert"
        else:
            bucket = "smoke"
        results.append(
            {
                "file": m["file"],
                "status": m["status"],
                "rc": m["rc"],
                "unique_lines": u_lines,
                "unique_branches": u_branches,
                "bucket": bucket,
                "top_unique_modules": top,
            }
        )
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=600, help="单 stub pytest 超时秒数")
    ap.add_argument("--only", type=Path, nargs="*", default=None, help="只测指定文件（调试）")
    ap.add_argument("--out", type=Path, default=OUT_JSON)
    args = ap.parse_args(argv)

    if not BEHAVIOR_JSON.is_file():
        print(
            f"ERROR: 缺行为基线 {BEHAVIOR_JSON}，先跑行为套件生成（见 retirement plan）",
            file=sys.stderr,
        )
        return 2
    behavior = load_behavior_covered()
    stubs = [FHD_ROOT / p for p in args.only] if args.only else list_stubs()
    print(f"[triage] {len(stubs)} 个 stub，workers={args.workers}")

    measured: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(measure_stub, s, args.timeout): s for s in stubs}
        for done, fut in enumerate(as_completed(futs), 1):
            measured.append(fut.result())
            if done % 10 == 0 or done == len(stubs):
                print(f"[triage] {done}/{len(stubs)}")

    results = analyze(measured, behavior)
    results.sort(key=lambda r: -r["unique_lines"])

    union_lines = 0
    beh_all: dict[str, set[int]] = {f: v["lines"] for f, v in behavior.items()}
    stub_union: dict[str, set[int]] = {}
    for m in measured:
        if m["status"] != "ok":
            continue
        for fname, cov in m["files"].items():
            stub_union.setdefault(fname, set()).update(cov["lines"])
    for fname, lines in stub_union.items():
        union_lines += len(lines - beh_all.get(fname, set()))

    buckets: dict[str, list[str]] = {}
    for r in results:
        buckets.setdefault(r["bucket"], []).append(r["file"])

    payload = {
        "_note": "coverage_ramp 分诊结果。union_unique_lines 自检应≈全量-行为覆盖差(4937,±10%)。",
        "behavior_baseline": "coverage-behavior.json",
        "union_unique_lines": union_lines,
        "buckets": {k: len(v) for k, v in sorted(buckets.items())},
        "files": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[triage] 分桶: {json.dumps(payload['buckets'], ensure_ascii=False)}")
    print(f"[triage] union_unique_lines={union_lines}（自检期望 ≈4937 ±10%）")
    print(f"[triage] 已写入 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
