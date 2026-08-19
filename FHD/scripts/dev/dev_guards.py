#!/usr/bin/env python3
"""开发守卫统一入口：把分散的规范性守卫/棘轮/校验脚本串行聚合为单一命令。

被 SSOT 域 ``dev-guards`` 引用（见 ``config/ssot.yaml``），纳入 ``ssot_cli gate``
统一调度与 ``ssot-drift-gate`` 硬门禁。仅聚合**纯静态守卫**（零第三方依赖、
不依赖动态覆盖率数据），命令参数与 ``fhd-ci-cd.yml`` ``backend-test`` 完全一致，
避免口径漂移。

依赖覆盖率实测的守卫（``guard_coverage_floor.py`` / ``coverage_ratchet.py``）保留在
``backend-test`` 内运行，不纳入本聚合。

用法::

    python scripts/dev/dev_guards.py             # 串行运行全部守卫
    python scripts/dev/dev_guards.py check       # 显式 check（与默认一致）
    python scripts/dev/dev_guards.py --json      # 以 JSON 输出每个守卫的判定

退出码: 0=全部 blocking 守卫通过 1=存在 blocking 守卫失败 2=用法错。
（advisory 漂移项仅报告，不阻断。）
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]

EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2

# (名称, argv, blocking) —— argv[0] 会被替换为当前解释器；命令参数与 fhd-ci-cd.yml backend-test 一致。
# blocking=False 的守卫当前存在既有漂移（仓库现状，非本聚合引入），以 advisory 方式报告但不阻断 gate；
# 待对应漂移修复后改为 blocking=True。其余为当前全绿、硬阻断守卫。
GUARDS: list[tuple[str, list[str], bool]] = [
    ("layer-ratchet", ["python", "scripts/dev/check_layer_ratchet.py"], True),
    ("type-debt", ["python", "scripts/dev/count_type_debt.py",
                    "--max-type-ignore", "69", "--max-ts-nocheck", "0", "--max-any", "99999"], True),
    ("raw-sql", ["python", "scripts/dev/count_raw_sql.py"], True),
    ("big-files", ["python", "scripts/dev/count_big_files.py"], False),
    ("coverage-ramp-stubs", ["python", "scripts/dev/count_coverage_ramp_stubs.py", "--check"], True),
    ("test-bloat", ["python", "scripts/dev/test_bloat_report.py", "--check"], True),
    ("requirements-lock", ["python", "scripts/dev/check_requirements_lock.py"], True),
    ("mods-inline-ui", ["python", "scripts/dev/guard_mods_inline_ui.py"], True),
    ("utils-boundary", ["python", "scripts/dev/guard_utils_boundary.py"], True),
    ("mod-import-boundaries", ["python", "scripts/dev/check_mod_import_boundaries.py"], True),
    ("arch-fitness", ["python", "scripts/arch_fitness.py"], True),
]


def _run_one(name: str, argv: list[str], *, silent: bool = False) -> tuple[str, int]:
    """运行单个守卫，返回 (name, exit_code)。argv[0]=='python' 替换为当前解释器。
    silent=True 时抑制子进程 stdout/stderr（用于 --json 场景避免污染）。"""
    cmd = [sys.executable] + argv[1:] if argv[0] == "python" else argv
    try:
        if silent:
            code = subprocess.call(
                cmd, cwd=str(FHD_ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        else:
            code = subprocess.call(cmd, cwd=str(FHD_ROOT))
    except OSError as exc:
        print(f"::error::dev-guards: {name} 无法运行: {exc}", file=sys.stderr)
        return name, EXIT_USAGE
    return name, code


def run_all(*, verbose: bool = True) -> tuple[int, list[dict]]:
    """串行运行全部守卫，返回 (整体退出码, 逐项结果)。仅 blocking 守卫失败才整体失败。"""
    results: list[dict] = []
    worst = EXIT_OK
    blocking_fail = 0
    for name, argv, blocking in GUARDS:
        _, code = _run_one(name, argv, silent=not verbose)
        status = "ok" if code == 0 else "fail"
        if verbose:
            tag = "BLOCK" if blocking else "advisory"
            print(f"[dev-guards] {name:<22} {'OK' if code == 0 else 'FAIL'} ({tag})")
        results.append(
            {"name": name, "status": status, "exit": code, "blocking": blocking}
        )
        if code != 0 and blocking:
            blocking_fail += 1
            worst = EXIT_FAIL
    if verbose:
        final = "ALL PASS" if worst == 0 else "BLOCKING FAILURES PRESENT"
        print(
            f"[dev-guards] {final}（blocking "
            f"{sum(1 for r in results if r['blocking'] and r['status']=='ok')}/"
            f"{sum(1 for r in results if r['blocking'])}；advisory 漂移 "
            f"{sum(1 for r in results if not r['blocking'] and r['status']=='fail')} 项）"
        )
    return worst, results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=["check"], default="check",
                        help="check（默认）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出每个守卫的判定")
    args = parser.parse_args(argv)

    worst, results = run_all(verbose=not args.json)
    if args.json:
        print(json.dumps({"ok": worst == 0, "guards": results}, ensure_ascii=False, indent=2))
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
