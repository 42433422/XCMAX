#!/usr/bin/env python3
"""从 metrics/ 自动生成「对外声称 vs 实测」对照文档（零三方依赖）。

数据源（均在 FHD/metrics/，字段名以真实 JSON 为准）：
  - coverage-dual-summary.json：committed_head.* / ratchet_floors.* / targets.* / _retired.values
  - coverage-history.jsonl：最后一行为最新趋势
  - sla-snapshot.json：/api/health 健康探针
  - dora-20260613.json：DORA 指标
  - pyproject.toml：fail_under 正则交叉校验后端行 floor
  - VERSION.md『各端交付等级』表 vs docs/guides/MOBILE_ANDROID.md 实际状态
  - frontend/e2e/*.spec.ts：E2E spec 数

输出 FHD/docs/CLAIMED_VS_ACTUAL.md。

用法：
  python scripts/dev/gen_claimed_vs_actual.py            # 写文件
  python scripts/dev/gen_claimed_vs_actual.py --check    # 重新生成并比对（忽略「生成于」时间戳行），不一致 exit 1
"""
from __future__ import annotations

import argparse
import datetime
import glob
import json
import re
import sys
from pathlib import Path

# 脚本在 FHD/scripts/dev/ 下 → parents[3] = XCMAX/（仓根）
REPO_ROOT = Path(__file__).resolve().parents[3]
FHD_ROOT = REPO_ROOT / "FHD"

METRICS_DIR = FHD_ROOT / "metrics"
OUTPUT_DOC = FHD_ROOT / "docs" / "CLAIMED_VS_ACTUAL.md"

GEN_LINE_PREFIX = "> 自动生成，请勿手改"

# 状态图标
ST_GREEN = "🟢"
ST_YELLOW = "🟡"
ST_RED = "🔴"
ST_RETIRED = "⛔"


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _read_jsonl_last(path: Path) -> dict:
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError:
        return {}
    if not lines:
        return {}
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        return {}


def _fail_under_from_pyproject() -> int | None:
    pyproject = FHD_ROOT / "pyproject.toml"
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return None
    # 取真正的赋值行（行首可有空白），而非注释里的说明
    m = re.search(r"(?m)^\s*fail_under\s*=\s*(\d+)", text)
    if m:
        return int(m.group(1))
    return None


def _status_for(actual: float, floor: float | None, target: float | None) -> str:
    """actual>=target 🟢 / floor<=actual<target 🟡 / actual<floor 🔴。"""
    if target is not None and actual >= target:
        return ST_GREEN
    if floor is not None and actual >= floor:
        return ST_YELLOW
    return ST_RED


def _fmt_pct(v) -> str:
    if v is None:
        return "n/a"
    return f"{v}%"


def _android_levels() -> tuple[str, str, str]:
    """返回 (VERSION.md 声称等级, MOBILE_ANDROID.md 实测等级, 状态)。"""
    claimed = "未知"
    version_md = FHD_ROOT / "VERSION.md"
    try:
        for line in version_md.read_text(encoding="utf-8").splitlines():
            if "Android" in line and "|" in line and ("签约级" in line or "实验骨架" in line):
                if "签约级" in line:
                    claimed = "签约级"
                elif "实验骨架" in line:
                    claimed = "实验骨架"
                break
    except OSError:
        pass

    actual = "未知"
    mobile_md = FHD_ROOT / "docs" / "guides" / "MOBILE_ANDROID.md"
    try:
        text = mobile_md.read_text(encoding="utf-8")
        if re.search(r"实验骨架", text):
            actual = "实验骨架·非签约级"
        elif re.search(r"签约级", text):
            actual = "签约级"
    except OSError:
        pass

    # 声称（去掉星号后）与实测核心词一致 → 🟢，否则 🔴
    claimed_core = claimed.replace("*", "")
    actual_core = "实验骨架" if "实验骨架" in actual else ("签约级" if "签约级" in actual else actual)
    status = ST_GREEN if claimed_core == actual_core else ST_RED
    return claimed, actual, status


def build_rows() -> tuple[list[list[str]], list[list[str]]]:
    """返回 (主表行, 退役口径行)。每行为 [维度, 声称, 实测, 数据源, 状态]。"""
    dual = _read_json(METRICS_DIR / "coverage-dual-summary.json")
    head = dual.get("committed_head", {})
    floors = dual.get("ratchet_floors", {})
    targets = dual.get("targets", {})
    retired = dual.get("_retired", {})

    hist = _read_jsonl_last(METRICS_DIR / "coverage-history.jsonl")
    sla = _read_json(METRICS_DIR / "sla-snapshot.json")
    dora = _read_json(METRICS_DIR / "dora-20260613.json")
    fail_under = _fail_under_from_pyproject()

    rows: list[list[str]] = []

    # --- 覆盖率：后端行 ---
    be_line = head.get("backend_line_pct")
    be_line_floor = floors.get("backend_line")
    be_line_target = targets.get("backend_line_pct")
    if be_line is not None:
        rows.append([
            "后端行覆盖率",
            f"≥{_fmt_pct(be_line_target)}（目标）",
            _fmt_pct(be_line),
            "coverage-dual-summary.json#committed_head.backend_line_pct",
            _status_for(be_line, be_line_floor, be_line_target),
        ])

    # --- 后端分支 ---
    be_branch = head.get("backend_branch_pct")
    if be_branch is not None:
        rows.append([
            "后端分支覆盖率",
            f"≥{_fmt_pct(targets.get('backend_branch_pct'))}（目标）",
            _fmt_pct(be_branch),
            "coverage-dual-summary.json#committed_head.backend_branch_pct",
            _status_for(be_branch, floors.get("backend_branch"), targets.get("backend_branch_pct")),
        ])

    # --- 前端行 ---
    fe_line = head.get("frontend_line_pct")
    if fe_line is not None:
        rows.append([
            "前端行覆盖率",
            f"≥{_fmt_pct(targets.get('frontend_line_pct'))}（目标）",
            _fmt_pct(fe_line),
            "coverage-dual-summary.json#committed_head.frontend_line_pct",
            _status_for(fe_line, floors.get("frontend_lines"), targets.get("frontend_line_pct")),
        ])

    # --- 前端分支 ---
    fe_branch = head.get("frontend_branch_pct")
    if fe_branch is not None:
        rows.append([
            "前端分支覆盖率",
            f"≥{_fmt_pct(targets.get('frontend_branch_pct'))}（目标）",
            _fmt_pct(fe_branch),
            "coverage-dual-summary.json#committed_head.frontend_branch_pct",
            _status_for(fe_branch, floors.get("frontend_branches"), targets.get("frontend_branch_pct")),
        ])

    # --- 前端函数 ---
    fe_func = head.get("frontend_function_pct")
    if fe_func is not None:
        fe_func_floor = floors.get("frontend_functions")
        # 无独立 target，复用 floor 作为达标线
        status = ST_GREEN if (fe_func_floor is not None and fe_func >= fe_func_floor) else ST_RED
        rows.append([
            "前端函数覆盖率",
            f"≥{_fmt_pct(fe_func_floor)}（floor）",
            _fmt_pct(fe_func),
            "coverage-dual-summary.json#committed_head.frontend_function_pct",
            status,
        ])

    # --- pyproject fail_under 交叉校验后端行 floor ---
    be_line_floor_val = floors.get("backend_line")
    if fail_under is not None and be_line_floor_val is not None:
        consistent = fail_under == be_line_floor_val
        rows.append([
            "后端行 floor（fail_under 交叉校验）",
            f"棘轮 floor={be_line_floor_val}",
            f"pyproject fail_under={fail_under}",
            "pyproject.toml fail_under vs coverage-dual-summary.json#ratchet_floors.backend_line",
            ST_GREEN if consistent else ST_RED,
        ])

    # --- 覆盖率最新趋势（history 最后一行） ---
    if hist:
        hist_be = hist.get("backend_lines")
        hist_date = hist.get("date", "?")
        if hist_be is not None:
            rows.append([
                f"覆盖率趋势（最新 {hist_date}）",
                "趋势上行",
                f"后端行 {hist_be}% / 前端行 {hist.get('frontend_lines')}%",
                "coverage-history.jsonl（最后一行）",
                _status_for(hist_be, be_line_floor_val, None) if be_line_floor_val else ST_GREEN,
            ])

    # --- 健康探针 SLA ---
    probe = sla.get("probe", {}).get("probe_result", {}).get("health", {})
    if probe:
        within = probe.get("within_budget")
        elapsed = probe.get("elapsed_ms")
        budget = probe.get("budget_ms")
        rows.append([
            "健康探针 /api/health",
            f"P50 < {budget}ms 预算",
            f"{elapsed}ms（status {probe.get('status_code')}）",
            "sla-snapshot.json#probe.probe_result.health",
            ST_GREEN if within else ST_RED,
        ])

    # --- DORA ---
    if dora:
        ev = dora.get("event_count", 0)
        rows.append([
            "DORA 部署频率",
            "持续交付",
            f"窗口 {dora.get('window_days')}d / 事件 {ev} / 频率 {dora.get('deployment_frequency_per_day')}/d",
            "dora-20260613.json",
            ST_GREEN if ev and ev > 0 else ST_YELLOW,
        ])

    # --- E2E spec 数 ---
    e2e_specs = sorted(glob.glob(str(FHD_ROOT / "frontend" / "e2e" / "*.spec.ts")))
    e2e_count = len(e2e_specs)
    rows.append([
        "前端 E2E spec 数",
        "有 E2E 套件",
        f"{e2e_count} 个 spec",
        "frontend/e2e/*.spec.ts",
        ST_GREEN if e2e_count > 0 else ST_RED,
    ])

    # --- Android 端等级 ---
    a_claimed, a_actual, a_status = _android_levels()
    rows.append([
        "Android 端交付等级",
        a_claimed,
        a_actual,
        "VERSION.md『各端交付等级』vs docs/guides/MOBILE_ANDROID.md",
        a_status,
    ])

    # --- 退役口径黑名单 ---
    retired_rows: list[list[str]] = []
    for key, reason in (retired.get("values", {}) or {}).items():
        retired_rows.append([
            f"退役口径 `{key}`",
            "（曾对外引用）",
            "已退役，禁止再引用",
            "coverage-dual-summary.json#_retired.values",
            f"{ST_RETIRED} {reason}",
        ])

    return rows, retired_rows


def _md_table(header: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(header) + " |"]
    out.append("|" + "|".join(["---"] * len(header)) + "|")
    for r in rows:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


def render_doc() -> str:
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows, retired_rows = build_rows()

    parts: list[str] = []
    parts.append("# 对外声称 vs 实测（CLAIMED_VS_ACTUAL）")
    parts.append("")
    parts.append(f"{GEN_LINE_PREFIX}；源 `FHD/scripts/dev/gen_claimed_vs_actual.py`；生成于 {now}")
    parts.append("")
    parts.append(
        "> 本文为「对外声称 vs 实测」对照的**单一事实来源（SSOT）**，"
        "由 `scripts/dev/gen_claimed_vs_actual.py` 从 `metrics/` 自动汇编。"
        "覆盖率唯一数字 SSOT 见 [`metrics/coverage-dual-summary.json`](../metrics/coverage-dual-summary.json)。"
    )
    parts.append("")
    parts.append("## 声称 vs 实测对照表")
    parts.append("")
    parts.append(_md_table(["维度", "声称", "实测", "数据源", "状态"], rows))
    parts.append("")
    parts.append("**状态图例**：🟢 实测 ≥ 目标 · 🟡 floor ≤ 实测 < 目标 · 🔴 实测 < floor 或 声称≠实测 · ⛔ 已退役口径")
    parts.append("")
    parts.append("## 已退役口径（黑名单，禁止对外引用）")
    parts.append("")
    if retired_rows:
        parts.append(_md_table(["维度", "声称", "实测", "数据源", "状态"], retired_rows))
    else:
        parts.append("_（无）_")
    parts.append("")
    return "\n".join(parts) + "\n"


def _strip_gen_line(text: str) -> str:
    """移除「生成于」时间戳所在行，供 --check 比对（忽略时间戳）。"""
    return "\n".join(
        ln for ln in text.splitlines() if not ln.startswith(GEN_LINE_PREFIX)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="重新生成并与现有文件比对（忽略生成时间戳行），不一致 exit 1（CI 门禁）",
    )
    args = parser.parse_args()

    new_content = render_doc()

    if args.check:
        if not OUTPUT_DOC.exists():
            print(f"[FAIL] {OUTPUT_DOC} 不存在，请先运行生成")
            return 1
        existing = OUTPUT_DOC.read_text(encoding="utf-8")
        if _strip_gen_line(existing) == _strip_gen_line(new_content):
            print(f"[OK] {OUTPUT_DOC} 与 metrics 一致")
            return 0
        print(f"[FAIL] {OUTPUT_DOC} 已过期，与 metrics 不一致；请运行 gen_claimed_vs_actual.py 重新生成")
        return 1

    OUTPUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_DOC.write_text(new_content, encoding="utf-8")
    print(f"[OK] 已生成 {OUTPUT_DOC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
