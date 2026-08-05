#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档数字宣称校验（P2-3：文档与实测一致）。

背景：本仓库多处文档（docs/**、workspace 规则、CHANGELOG）手工维护覆盖率/指标数字，
曾出现与实测快照不一致（如 CI_SSOT 宣称 fail_under=90/分支=85，实际 SSOT 为 88/81），
误导决策。本脚本建立"文档数字必须源于可复现快照"的校验：

真值（SSOT）来源
----------------
* 后端行 floor  = ``pyproject.toml [tool.coverage.report] fail_under``（唯一 SSOT）
* 分支 floor / 前端 floor   = ``metrics/coverage_ratchet_baseline.json``
* 最近实测 last_measured    = 同一 baseline 文件
* 对外口径 target           = ``metrics/coverage-dual-summary.json``

校验内容
--------
1. 快照自洽：baseline 的 backend_lines_floor 必须与 pyproject fail_under 一致；
   vitest.config.js thresholds 必须与 baseline frontend_floors 一致。
2. 文档宣称：扫描给定文档中"覆盖率数字 + 覆盖率关键词"的出现，凡被当作"当前/宣称"
   值的数字，必须匹配 SSOT 中任一真值（floor / last_measured / target），否则列为失实。

退出码：0 通过；1 存在失实宣称或 SSOT 不自洽；2 用法错。

用法::

    python scripts/dev/verify_doc_claims.py [文档...]   # 默认扫描 docs 与规则清单
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = FHD_ROOT / "pyproject.toml"
VITEST_CONFIG = FHD_ROOT / "frontend" / "vitest.config.js"
BASELINE = FHD_ROOT / "metrics" / "coverage_ratchet_baseline.json"
DUAL_SUMMARY = FHD_ROOT / "metrics" / "coverage-dual-summary.json"

# workspace 规则（根仓 .trae/rules）与 FHD 文档
DEFAULT_DOCS = [
    FHD_ROOT / "docs" / "CI_SSOT.md",
    FHD_ROOT / "docs" / "reports" / "COVERAGE_RAMP.md",
    FHD_ROOT / "reports" / "COVERAGE_RAMP.md",
    FHD_ROOT / "CHANGELOG.md",
    Path("/Users/a4243342/Desktop/XCMAX/.trae/rules/cicd-e2e-prompt.md"),
]

FE_KEYS = ("lines", "branches", "functions", "statements")

# 数字匹配：xxx% 或 bare 数字
PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
FAIL_UNDER_RE = re.compile(r"fail_under\s*=\s*(\d+(?:\.\d+)?)")
THRESH_RE = re.compile(r"thresholds:\s*\{(.*?)\}", re.S)
KEEP_KEY_RE = re.compile(r"({key}:\s*)\d+")

# 覆盖率上下文关键词（中文 + 英文）
CONTEXT_RE = re.compile(
    r"(覆盖率|行覆盖|分支覆盖|line|branch|function|statement|fail_under|floor|门禁|threshold)",
    re.IGNORECASE,
)


def load_json(p: Path) -> dict:
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def read_fail_under() -> float:
    m = FAIL_UNDER_RE.search(PYPROJECT.read_text(encoding="utf-8"))
    return float(m.group(1)) if m else 0.0


def read_vitest_thresholds() -> dict[str, float]:
    m = THRESH_RE.search(VITEST_CONFIG.read_text(encoding="utf-8"))
    if not m:
        return {}
    out: dict[str, float] = {}
    for key in FE_KEYS:
        km = re.search(rf"{key}:\s*(\d+(?:\.\d+)?)", m.group(1))
        if km:
            out[key] = float(km.group(1))
    return out


def approx(a: float, b: float, tol: float = 0.05) -> bool:
    return abs(a - b) <= tol


def collect_ssot_values() -> dict[str, float]:
    """把所有 SSOT 真值（floor / last_measured / target / thresholds）扁平收集。"""
    vals: dict[str, float] = {}
    base = load_json(BASELINE)
    dual = load_json(DUAL_SUMMARY)

    vals["pyproject_fail_under"] = read_fail_under()
    vals["vitest_threshold_lines"] = read_vitest_thresholds().get("lines", 0.0)
    vals["vitest_threshold_branches"] = read_vitest_thresholds().get("branches", 0.0)

    for k, v in base.get("frontend_floors", {}).items():
        vals[f"baseline_frontend_{k}"] = float(v or 0)
    for k, v in base.get("last_measured", {}).items():
        vals[f"last_measured_{k}"] = float(v or 0)
    vals["baseline_backend_lines_floor"] = float(base.get("backend_lines_floor", 0) or 0)
    vals["baseline_backend_branch_floor"] = float(base.get("backend_branch_floor", 0) or 0)

    for k, v in dual.get("targets", {}).items():
        vals[f"target_{k}"] = float(v or 0)
    for k, v in dual.get("ratchet_floors", {}).items():
        if isinstance(v, (int, float)):
            vals[f"ratchet_{k}"] = float(v)
    return vals


def check_snapshot_self_consistency(ssot: dict[str, float]) -> list[str]:
    """校验快照内部自洽：pyproject fail_under 与 baseline 行 floor 一致；vitest 与 baseline 前端 floor 一致。"""
    problems: list[str] = []
    py = ssot.get("pyproject_fail_under", 0.0)
    bl = ssot.get("baseline_backend_lines_floor", 0.0)
    if py and bl and not approx(py, bl, 1.0):
        problems.append(
            f"【SSOT 不自洽】pyproject fail_under={py:g} 与 baseline backend_lines_floor={bl:g} 不一致"
        )
    for key in FE_KEYS:
        vt = read_vitest_thresholds().get(key)
        bl_value = ssot.get(f"baseline_frontend_{key}")
        if vt is not None and bl_value and not approx(vt, bl_value, 1.0):
            problems.append(
                f"【SSOT 不自洽】vitest threshold {key}={vt:g} 与 baseline frontend_{key}={bl_value:g} 不一致"
            )
    return problems


# 历史 / 目标 / 阶段上下文提示词：命中则把行内数字视作非"当前 floor"宣称，豁免
HISTORICAL_HINTS = (
    "历史", "退役", "retired", "已退役", "曾", "旧", "误报", "撤回", "过渡",
    "目标", "target", "roadmap", "Phase", "阶段", "M1", "M2", "M3", "M4",
    "~", "约", "待", "计划", "means", "已诞生", "收录", "封顶", "卡", "上限",
)


def scan_docs(docs: list[Path], ssot: dict[str, float]) -> list[str]:
    """扫描文档，把"当前 floor/门禁"宣称的覆盖率数字与 SSOT 真值比对，列出失实宣称。

    仅把当前 floor 值（后端行/分支 + 前端各项 floor + last_measured）作为允许集合；
    目标值（target_*）与 vitest/pyproject 的 floor 由其余字段覆盖。命中历史/目标/阶段
    提示词的行视为非当前宣称，豁免。
    """
    allowed = set(round(v, 2) for k, v in ssot.items() if not k.startswith("target_"))
    issues: list[str] = []
    for doc in docs:
        if not doc.is_file():
            continue
        text = doc.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()
        for n, line in enumerate(lines, 1):
            if not CONTEXT_RE.search(line):
                continue
            hist = any(h in line for h in HISTORICAL_HINTS)
            for m in PCT_RE.finditer(line):
                num = float(m.group(1))
                if round(num, 2) in allowed:
                    continue
                if hist:
                    continue
                snippet = line.strip()[:90]
                issues.append(
                    f"{doc.relative_to(FHD_ROOT.parent) if str(doc).startswith(str(FHD_ROOT.parent)) else doc}:{n} "
                    f"疑似失实的当前覆盖率宣称 {num}%（不在 SSOT 当前 floor/实测集合） | {snippet}"
                )
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("docs", nargs="*", type=Path, help="要扫描的文档；缺省用内置清单")
    args = parser.parse_args(argv)

    ssot = collect_ssot_values()
    problems = check_snapshot_self_consistency(ssot)
    docs = args.docs if args.docs else DEFAULT_DOCS
    issues = scan_docs(docs, ssot)

    print("== SSOT 真值（%）==")
    for k in sorted(ssot):
        print(f"  {k} = {ssot[k]:g}")

    print("\n== SSOT 自洽性 ==")
    if problems:
        for p in problems:
            print("  FAIL " + p)
    else:
        print("  OK 快照自洽")

    print("\n== 文档宣称比对 ==")
    if issues:
        for i in issues:
            print("  MISMATCH " + i)
        print(f"\n共 {len(issues)} 处疑似失实宣称。")
        return 1
    print("  OK 未发现失实宣称")
    return 0


if __name__ == "__main__":
    sys.exit(main())