#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""覆盖率棘轮（ratchet）：行/分支（后端）+ lines/branches/functions/statements（前端），只升不降。

与 ``check_layer_ratchet.py`` / ``count_type_debt.py`` / ``count_raw_sql.py`` 同级，
守护"覆盖率真实性六条铁律"中的可复现与只升不降：

铁律6（分支独立统计）落地的关键工程取舍
----------------------------------------
``coverage.py`` 一旦开启 ``branch=true``，其 ``totals.percent_covered`` 会变成
"行+分支合并"指标，不再等于纯行覆盖率。为保持 ``pyproject.toml`` 的
``[tool.coverage.report] fail_under`` 仍是**行覆盖率** floor（与规格"35→90"一致），
本棘轮**不读** ``percent_covered``，而是从 ``coverage.json`` 的原始计数自行计算：

* 行覆盖率   = ``covered_lines / num_statements * 100``
* 分支覆盖率 = ``covered_branches / num_branches * 100``

行 floor 取自 ``pyproject.toml`` 的 ``fail_under``（SSOT）；分支 floor 与前端各项 floor
存于 ``metrics/coverage_ratchet_baseline.json``（只升不降）。

数据来源（由测试命令预先产出，棘轮不跑测试）
--------------------------------------------
* 后端：``coverage.json``（``pytest --cov --cov-branch --cov-report=json:coverage.json``）
* 前端：``frontend/coverage/coverage-summary.json``（vitest ``json-summary`` reporter）

由于开启 branch 后 coverage 自带 fail_under 会按合并指标拦截，标准测量命令应传
``--cov-fail-under=0`` 把门禁交给本棘轮（``--check``）。

退出码：回退/缺数据 ``1``（check）；用法错 ``2``；正常 ``0``。

用法::

    python scripts/dev/coverage_ratchet.py --check     # CI 门禁：回退即失败
    python scripts/dev/coverage_ratchet.py --bump      # 提升基线到当前值（只升）
    python scripts/dev/coverage_ratchet.py --history    # 查看趋势（--record 追加快照）
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = FHD_ROOT / "pyproject.toml"
VITEST_CONFIG = FHD_ROOT / "frontend" / "vitest.config.js"
BACKEND_JSON_DEFAULT = FHD_ROOT / "coverage.json"
FRONTEND_SUMMARY_DEFAULT = FHD_ROOT / "frontend" / "coverage" / "coverage-summary.json"
BASELINE = FHD_ROOT / "metrics" / "coverage_ratchet_baseline.json"
HISTORY = FHD_ROOT / "metrics" / "coverage-history.jsonl"

# 防止可复现性 ±0.5% 抖动造成假失败：bump 时把 floor 设为 floor(实测 - MARGIN)。
DEFAULT_MARGIN = 1.0

FE_KEYS = ("lines", "branches", "functions", "statements")

# pyproject.toml 中唯一的 fail_under 行（[tool.coverage.report] 下）。
FAIL_UNDER_RE = re.compile(r"(?m)^(fail_under\s*=\s*)(\d+(?:\.\d+)?)")


# --------------------------------------------------------------------------- #
# 解析覆盖率产物
# --------------------------------------------------------------------------- #
def read_backend(json_path: Path) -> dict | None:
    """从 coverage.json 计算纯行覆盖率与分支覆盖率（忽略合并的 percent_covered）。"""
    if not json_path.is_file():
        return None
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    t = data.get("totals", {})
    num_st = int(t.get("num_statements", 0) or 0)
    cov_ln = int(t.get("covered_lines", 0) or 0)
    num_br = int(t.get("num_branches", 0) or 0)
    cov_br = int(t.get("covered_branches", 0) or 0)
    line_pct = round(cov_ln / num_st * 100.0, 2) if num_st else 0.0
    branch_pct = round(cov_br / num_br * 100.0, 2) if num_br else None
    return {
        "line_pct": line_pct,
        "branch_pct": branch_pct,
        "num_statements": num_st,
        "covered_lines": cov_ln,
        "missing_lines": int(t.get("missing_lines", num_st - cov_ln) or 0),
        "num_branches": num_br,
        "covered_branches": cov_br,
    }


def read_frontend(path: Path) -> dict | None:
    """从 vitest coverage-summary.json 读取 total 的各项 pct。"""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    total = data.get("total", {})
    out: dict[str, float] = {}
    for key in FE_KEYS:
        out[key] = round(float((total.get(key, {}) or {}).get("pct", 0.0) or 0.0), 2)
    return out


# --------------------------------------------------------------------------- #
# pyproject fail_under（行 floor SSOT）读写
# --------------------------------------------------------------------------- #
def read_fail_under(p: Path) -> float:
    m = FAIL_UNDER_RE.search(p.read_text(encoding="utf-8"))
    return float(m.group(2)) if m else 0.0


def write_fail_under(p: Path, value: int) -> None:
    text = p.read_text(encoding="utf-8")
    new = FAIL_UNDER_RE.sub(rf"\g<1>{value}", text, count=1)
    p.write_text(new, encoding="utf-8")


# --------------------------------------------------------------------------- #
# 基线（分支 floor + 前端 floor）只升不降
# --------------------------------------------------------------------------- #
def load_baseline() -> dict:
    if BASELINE.is_file():
        try:
            return json.loads(BASELINE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def save_baseline(d: dict) -> None:
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "_note": "覆盖率棘轮基线（只升不降）。行 floor 见 pyproject.toml fail_under；"
        "此处存分支 floor 与前端各项 floor。由 coverage_ratchet.py --bump 维护。",
        **{k: v for k, v in d.items() if not k.startswith("_")},
    }
    BASELINE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _floor(value: float, margin: float) -> int:
    return max(0, math.floor(value - margin))


# --------------------------------------------------------------------------- #
# vitest thresholds 同步（只升不降，在 thresholds {...} 块内替换数字）
# --------------------------------------------------------------------------- #
def sync_vitest_thresholds(floors: dict[str, int]) -> bool:
    if not VITEST_CONFIG.is_file():
        return False
    text = VITEST_CONFIG.read_text(encoding="utf-8")
    m = re.search(r"thresholds:\s*\{(.*?)\}", text, re.S)
    if not m:
        return False
    block = m.group(1)
    new_block = block
    for key in FE_KEYS:
        if key in floors:
            new_block = re.sub(rf"({key}:\s*)\d+", rf"\g<1>{floors[key]}", new_block, count=1)
    if new_block == block:
        return False
    VITEST_CONFIG.write_text(text[: m.start(1)] + new_block + text[m.end(1) :], encoding="utf-8")
    return True


# --------------------------------------------------------------------------- #
# 历史
# --------------------------------------------------------------------------- #
def _git_short_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(FHD_ROOT), text=True
        ).strip()
    except (subprocess.SubprocessError, OSError):
        return None


def append_history(be: dict | None, fe: dict | None, note: str = "") -> None:
    rec = {
        "date": date.today().isoformat(),
        "ts": datetime.now(UTC).isoformat(),
        "backend_lines": be["line_pct"] if be else None,
        "backend_branches": be["branch_pct"] if be else None,
        "backend_statements": be["num_statements"] if be else None,
        "frontend_lines": fe["lines"] if fe else None,
        "frontend_branches": fe["branches"] if fe else None,
        "frontend_functions": fe["functions"] if fe else None,
        "frontend_statements": fe["statements"] if fe else None,
        "commit": _git_short_sha(),
        "note": note,
    }
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- #
# 命令
# --------------------------------------------------------------------------- #
def cmd_check(args: argparse.Namespace) -> int:
    be = read_backend(args.coverage_json)
    fe = read_frontend(args.frontend_summary)
    base = load_baseline()
    line_floor = read_fail_under(PYPROJECT)
    branch_floor = base.get("backend_branch_floor")
    fe_floors = base.get("frontend_floors", {})

    failed = False
    eps = 1e-9

    if be is None:
        if args.require_backend:
            print(f"ERROR: 缺后端 coverage.json：{args.coverage_json}", file=sys.stderr)
            return 1
        print(f"[cov-ratchet] 跳过后端（无 {args.coverage_json}）")
    else:
        bp = "n/a" if be["branch_pct"] is None else f"{be['branch_pct']}%"
        print(
            f"[cov-ratchet] backend line={be['line_pct']}% (floor {line_floor}%) "
            f"branch={bp} (floor {branch_floor})"
        )
        if be["line_pct"] + eps < line_floor:
            print(
                f"FAIL: 后端行覆盖率 {be['line_pct']}% < floor {line_floor}%（回退）",
                file=sys.stderr,
            )
            failed = True
        if (
            branch_floor is not None
            and be["branch_pct"] is not None
            and be["branch_pct"] + eps < float(branch_floor)
        ):
            print(
                f"FAIL: 后端分支覆盖率 {be['branch_pct']}% < floor {branch_floor}%（回退）",
                file=sys.stderr,
            )
            failed = True

    if fe is None:
        if args.require_frontend:
            print(f"ERROR: 缺前端 coverage-summary.json：{args.frontend_summary}", file=sys.stderr)
            return 1
        print(f"[cov-ratchet] 跳过前端（无 {args.frontend_summary}）")
    else:
        print(
            f"[cov-ratchet] frontend lines={fe['lines']}% branches={fe['branches']}% "
            f"functions={fe['functions']}% statements={fe['statements']}%"
        )
        for key in FE_KEYS:
            fl = fe_floors.get(key)
            if fl is not None and fe[key] + eps < float(fl):
                print(
                    f"FAIL: 前端 {key} {fe[key]}% < floor {fl}%（回退）",
                    file=sys.stderr,
                )
                failed = True

    if failed:
        print("[cov-ratchet] 覆盖率回退被阻断；请补测后再提交。", file=sys.stderr)
        return 1
    print("[cov-ratchet] OK — 覆盖率未回退")
    return 0


def cmd_bump(args: argparse.Namespace) -> int:
    be = read_backend(args.coverage_json)
    fe = read_frontend(args.frontend_summary)
    base = load_baseline()
    changed = False

    if be is not None:
        cur_line = read_fail_under(PYPROJECT)
        new_line = _floor(be["line_pct"], args.margin)
        if new_line > cur_line:
            write_fail_under(PYPROJECT, new_line)
            print(f"[cov-ratchet] backend 行 floor {cur_line:g} -> {new_line}")
            changed = True
        if be["branch_pct"] is not None:
            cur_b = float(base.get("backend_branch_floor", 0) or 0)
            new_b = _floor(be["branch_pct"], args.margin)
            if new_b > cur_b:
                base["backend_branch_floor"] = new_b
                print(f"[cov-ratchet] backend 分支 floor {cur_b:g} -> {new_b}")
                changed = True

    if fe is not None:
        ff = base.setdefault("frontend_floors", {})
        for key in FE_KEYS:
            cur = float(ff.get(key, 0) or 0)
            new = _floor(fe[key], args.margin)
            if new > cur:
                ff[key] = new
                print(f"[cov-ratchet] frontend {key} floor {cur:g} -> {new}")
                changed = True
        if not args.no_vitest and ff:
            if sync_vitest_thresholds({k: int(v) for k, v in ff.items()}):
                print("[cov-ratchet] vitest.config.js thresholds 已同步")

    if changed:
        save_baseline(base)
        append_history(be, fe, note="bump")
        print("[cov-ratchet] 基线已提升并记录历史。")
    else:
        print("[cov-ratchet] 无提升（未超过现有 floor），基线不变。")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    if args.record:
        be = read_backend(args.coverage_json)
        fe = read_frontend(args.frontend_summary)
        append_history(be, fe, note="record")
        print("[cov-ratchet] 已追加快照到 coverage-history.jsonl")
    if not HISTORY.is_file():
        print("(暂无历史)")
        return 0
    rows = HISTORY.read_text(encoding="utf-8").splitlines()
    for line in rows[-args.tail :]:
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        print(
            f"{r.get('date','')} be_line={r.get('backend_lines')}% "
            f"be_branch={r.get('backend_branches')}% fe_lines={r.get('frontend_lines')}% "
            f"fe_func={r.get('frontend_functions')}% {r.get('commit') or ''} {r.get('note','')}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="门禁：覆盖率回退则失败（退出码1）")
    mode.add_argument("--bump", action="store_true", help="把当前实测提升为新 floor（只升不降）")
    mode.add_argument("--history", action="store_true", help="打印趋势（配合 --record 追加快照）")
    parser.add_argument("--coverage-json", type=Path, default=BACKEND_JSON_DEFAULT, help="后端 coverage.json 路径")
    parser.add_argument(
        "--frontend-summary", type=Path, default=FRONTEND_SUMMARY_DEFAULT, help="前端 coverage-summary.json 路径"
    )
    parser.add_argument("--margin", type=float, default=DEFAULT_MARGIN, help="bump 安全余量（pt，默认1）")
    parser.add_argument("--no-vitest", action="store_true", help="bump 时不同步 vitest.config.js thresholds")
    parser.add_argument("--require-backend", action="store_true", help="check：缺后端数据即失败")
    parser.add_argument("--require-frontend", action="store_true", help="check：缺前端数据即失败")
    parser.add_argument("--record", action="store_true", help="history：先追加当前快照")
    parser.add_argument("--tail", type=int, default=15, help="history：打印最近 N 条")
    args = parser.parse_args(argv)

    if args.check:
        return cmd_check(args)
    if args.bump:
        return cmd_bump(args)
    if args.history:
        return cmd_history(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
