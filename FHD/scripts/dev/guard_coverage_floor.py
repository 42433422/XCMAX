#!/usr/bin/env python3
"""覆盖率 floor 下调守卫：任何 floor 降低必须附带 ADR，否则失败退出。

背景
----
覆盖率棘轮（``coverage_ratchet.py --bump``）本身只升不降，但 2026-07-25 与 2026-07-31
两次 floor 下调都是**人工直接编辑文件**绕过棘轮完成的（88/81 → 85/77 甚至未同步
pyproject ``fail_under``，造成口径分裂）。本守卫把"下调必须有决策记录"固化为门禁：

对比项（工作区 vs 基线引用，默认 ``HEAD``，PR CI 传 ``--base FETCH_HEAD``）
------------------------------------------------------------------------
* ``FHD/pyproject.toml`` 的 ``[tool.coverage.report] fail_under``（行 floor 铁律 SSOT）
* ``FHD/metrics/coverage_ratchet_baseline.json`` 的
  ``backend_lines_floor`` / ``backend_branch_floor`` / ``frontend_floors.*``

放行条件
--------
任何一项 floor 降低时，仅当本次改动（``git diff --name-only <base>`` + 未跟踪文件）中
包含 ``docs/adr/`` 目录下且文件名含 ``coverage`` 的 ADR 文件才放行（退出码 0），
否则退出码 1。floor 不变或升高总是放行。

非 git 环境（如打包产物、release tarball 内）或基线引用不可读时降级为警告，不失败。

关于 ``--peak-floor`` 未接入 CI 的说明
--------------------------------------
``coverage_ratchet.py --check`` 支持 ``--peak-floor``（低于历史峰值 0.5pt 即阻断），
但历史峰值 90.69% 与当前实测（88% 档）差距 > 0.5pt，直接启用会让 CI 立即全红。
因此峰值阻断暂不接入 CI：本守卫负责"防下调"（静态口径，不受实测抖动影响），
``--peak-floor`` 的启用条件是实测行覆盖率回升到距历史峰值 ≤0.5pt（即峰值口径
不再比 floor 口径更严格）之后，再于 ``ci-cd.yml`` 的 ratchet check 追加该参数。

退出码：下调无 ADR ``1``；用法/内部错误 ``2``；正常（含非 git 降级）``0``。

用法::

    python scripts/dev/guard_coverage_floor.py                    # 本地：工作区 vs HEAD
    python scripts/dev/guard_coverage_floor.py --base FETCH_HEAD  # PR CI：vs 目标分支
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = FHD_ROOT.parent

FAIL_UNDER_RE = re.compile(r"(?m)^(fail_under\s*=\s*)(\d+(?:\.\d+)?)")

# (label, getter) — baseline.json 中参与防下调对比的 floor 字段
BASELINE_SCALAR_KEYS = ("backend_lines_floor", "backend_branch_floor")
FRONTEND_FLOOR_KEYS = ("lines", "branches", "functions", "statements")


def _git(args: list[str]) -> str | None:
    """运行 git 命令，失败返回 None（调用方据此降级）。"""
    try:
        return subprocess.check_output(
            ["git", *args], cwd=str(REPO_ROOT), text=True, stderr=subprocess.DEVNULL
        )
    except (subprocess.SubprocessError, OSError):
        return None


def _rel_to_repo(p: Path) -> str:
    return p.relative_to(REPO_ROOT).as_posix()


def _read_ref_file(ref: str, rel: str) -> str | None:
    return _git(["show", f"{ref}:{rel}"])


def _fail_under_from(text: str) -> float | None:
    m = FAIL_UNDER_RE.search(text)
    return float(m.group(2)) if m else None


def _baseline_floors(data: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for key in BASELINE_SCALAR_KEYS:
        val = data.get(key)
        if isinstance(val, (int, float)):
            out[key] = float(val)
    fe = data.get("frontend_floors") or {}
    for key in FRONTEND_FLOOR_KEYS:
        val = fe.get(key)
        if isinstance(val, (int, float)):
            out[f"frontend_floors.{key}"] = float(val)
    return out


def _changed_paths(base: str) -> list[str]:
    """本次改动涉及的文件（相对 base 的已跟踪改动 + 未跟踪新文件）。"""
    paths: list[str] = []
    diff = _git(["diff", "--name-only", base])
    if diff:
        paths.extend(line.strip() for line in diff.splitlines() if line.strip())
    untracked = _git(["ls-files", "--others", "--exclude-standard"])
    if untracked:
        paths.extend(line.strip() for line in untracked.splitlines() if line.strip())
    return paths


def _has_coverage_adr(paths: list[str]) -> str | None:
    for p in paths:
        if "docs/adr/" in p and "coverage" in Path(p).name.lower():
            return p
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--base",
        default="HEAD",
        help="对比基线 git 引用（默认 HEAD；PR CI 先 fetch 目标分支再传 FETCH_HEAD）",
    )
    args = parser.parse_args(argv)
    base = args.base

    pyproject = FHD_ROOT / "pyproject.toml"
    baseline = FHD_ROOT / "metrics" / "coverage_ratchet_baseline.json"

    base_pyproject = _read_ref_file(base, _rel_to_repo(pyproject))
    base_baseline_raw = _read_ref_file(base, _rel_to_repo(baseline))
    if base_pyproject is None or base_baseline_raw is None:
        print(
            f"[guard-floor] WARNING: 非 git 环境或基线引用（{base}）缺少对比文件，降级为警告不阻断。",
            file=sys.stderr,
        )
        return 0

    lowered: list[str] = []

    # 1) pyproject fail_under（行 floor 铁律 SSOT）
    head_fu = _fail_under_from(base_pyproject)
    work_fu = _fail_under_from(pyproject.read_text(encoding="utf-8"))
    if head_fu is not None and work_fu is not None and work_fu < head_fu:
        lowered.append(f"pyproject fail_under: {head_fu:g} -> {work_fu:g}")

    # 2) baseline.json 各 floor
    try:
        head_floors = _baseline_floors(json.loads(base_baseline_raw))
        work_floors = _baseline_floors(json.loads(baseline.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[guard-floor] ERROR: baseline.json 解析失败：{exc}", file=sys.stderr)
        return 2
    for key, head_val in head_floors.items():
        work_val = work_floors.get(key)
        if work_val is not None and work_val < head_val:
            lowered.append(f"coverage_ratchet_baseline.json {key}: {head_val:g} -> {work_val:g}")

    if not lowered:
        print(f"[guard-floor] OK — 覆盖率 floor 未下调（vs {base}）")
        return 0

    adr = _has_coverage_adr(_changed_paths(base))
    if adr:
        print(f"[guard-floor] floor 下调已附带 ADR（{adr}），放行：")
        for item in lowered:
            print(f"  - {item}")
        return 0

    print("[guard-floor] FAIL: 检测到覆盖率 floor 下调且未附带 ADR：", file=sys.stderr)
    for item in lowered:
        print(f"  - {item}", file=sys.stderr)
    print(
        "[guard-floor] 下调覆盖率 floor 必须先在 docs/adr/ 新增文件名含 “coverage” 的 ADR 说明决策；"
        "否则请恢复 floor 并通过补测提升实测值。",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
