#!/usr/bin/env python3
"""从 metrics/ 自动生成「对外声称 vs 实测」对照文档（零三方依赖）。

数据源（均在 FHD/metrics/，字段名以真实 JSON 为准）：
  - coverage-dual-summary.json：committed_head.* / ratchet_floors.* / targets.* / _retired.values
  - coverage-history.jsonl：最后一行为最新趋势
  - sla-snapshot.json：/api/health 健康探针
  - dora-YYYYMMDD.json：最新 DORA 指标
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
import math
import re
import sys
from pathlib import Path

# 脚本在 FHD/scripts/dev/ 下 → parents[3] = XCMAX/（仓根）
REPO_ROOT = Path(__file__).resolve().parents[3]
FHD_ROOT = REPO_ROOT / "FHD"
sys.path.insert(0, str(FHD_ROOT))

from scripts.dev.benchmark_evidence import recorded_provenance

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
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
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
        payload = json.loads(lines[-1])
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        return {}


def _latest_dora_snapshot(metrics_dir: Path = METRICS_DIR) -> tuple[dict, Path | None]:
    candidates = sorted(
        path
        for path in metrics_dir.glob("dora-*.json")
        if re.fullmatch(r"dora-\d{8}\.json", path.name)
    )
    if not candidates:
        return {}, None
    latest = candidates[-1]
    return _read_json(latest), latest


def _snapshot_date(generated_at: str) -> str:
    """快照采集日（绝对日期）。

    刻意不输出「N 天内采集」这类相对量：该文档由 --check 与重生成结果逐字比对，
    任何随「当前时间」变化的文案都会让文档在无输入变更的情况下天天失效。
    """
    return generated_at[:10] if len(generated_at) >= 10 else "未知"


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
                if "实验骨架" in line:
                    claimed = "实验骨架"
                elif "签约级" in line:
                    claimed = "签约级"
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
    actual_core = (
        "实验骨架" if "实验骨架" in actual else ("签约级" if "签约级" in actual else actual)
    )
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
    dora, dora_path = _latest_dora_snapshot()
    fail_under = _fail_under_from_pyproject()

    rows: list[list[str]] = []

    provenance = recorded_provenance(head)
    rows.append(
        [
            "覆盖率证据范围",
            "当前版本需独立验证",
            f"采集 {provenance['captured_at'] or '未知'} / 来源 SHA {provenance['source_sha'] or '未知'}；"
            "仅该采样版本，本版未验证",
            "coverage-dual-summary.json#committed_head",
            ST_YELLOW,
        ]
    )
    for label, field, threshold, kind in (
        ("后端行", "backend_line_pct", targets.get("backend_line_pct"), "目标"),
        ("后端分支", "backend_branch_pct", targets.get("backend_branch_pct"), "目标"),
        ("前端行", "frontend_line_pct", targets.get("frontend_line_pct"), "目标"),
        ("前端分支", "frontend_branch_pct", targets.get("frontend_branch_pct"), "目标"),
        ("前端函数", "frontend_function_pct", floors.get("frontend_functions"), "floor"),
    ):
        if head.get(field) is not None:
            rows.append(
                [
                    f"{label}覆盖率（历史样本）",
                    f"≥{_fmt_pct(threshold)}（{kind}）",
                    _fmt_pct(head[field]),
                    f"coverage-dual-summary.json#committed_head.{field}",
                    ST_YELLOW,
                ]
            )

    benchmark = _read_json(METRICS_DIR / "benchmark_run_mode.json")
    provenance = recorded_provenance(benchmark)
    rows.append(
        [
            "真实模型任务验收",
            "当前版本需绑定 SHA 与原始任务凭据",
            f"本版未验证；历史状态 {benchmark.get('status', '未知')} / "
            f"模型实测标记 {benchmark.get('llm_verified', '未知')} / "
            f"采集 {provenance['captured_at'] or '未知'} / 来源 SHA {provenance['source_sha'] or '未知'}；"
            f"{benchmark.get('reason', '单独的模式标记不替代原始任务验收')}",
            "benchmark_run_mode.json",
            ST_YELLOW,
        ]
    )

    # --- pyproject fail_under 交叉校验后端行 floor ---
    be_line_floor_val = floors.get("backend_line")
    if fail_under is not None and be_line_floor_val is not None:
        consistent = fail_under == be_line_floor_val
        rows.append(
            [
                "后端行 floor（fail_under 交叉校验）",
                f"棘轮 floor={be_line_floor_val}",
                f"pyproject fail_under={fail_under}",
                "pyproject.toml fail_under vs coverage-dual-summary.json#ratchet_floors.backend_line",
                ST_GREEN if consistent else ST_RED,
            ]
        )

    # --- 覆盖率最新趋势（history 最后一行） ---
    if hist:
        hist_be = hist.get("backend_lines")
        hist_date = hist.get("date", "?")
        if hist_be is not None:
            rows.append(
                [
                    f"覆盖率趋势（历史 {hist_date}）",
                    "保留历史采样，不代表当前版本",
                    f"后端行 {hist_be}% / 前端行 {hist.get('frontend_lines')}%",
                    "coverage-history.jsonl（最后一行）",
                    ST_YELLOW,
                ]
            )

    # --- 健康探针 SLA ---
    probe = sla.get("probe", {}).get("probe_result", {}).get("health", {})
    if probe:
        within = probe.get("within_budget")
        elapsed = probe.get("elapsed_ms")
        budget = probe.get("budget_ms")
        rows.append(
            [
                "健康探针 /api/health",
                f"P50 < {budget}ms 预算",
                f"{elapsed}ms（status {probe.get('status_code')}）",
                "sla-snapshot.json#probe.probe_result.health",
                ST_GREEN if within else ST_RED,
            ]
        )

    # --- DORA ---
    if dora:
        ev = dora.get("event_count", 0)
        collected_on = _snapshot_date(dora.get("generated_at", ""))
        rows.append(
            [
                "DORA 部署频率",
                "持续交付",
                (
                    f"环境 {dora.get('environment', '未标注')} / "
                    f"窗口 {dora.get('window_days')}d / 事件 {ev} / "
                    f"频率 {dora.get('deployment_frequency_per_day')}/d / "
                    f"采集日 {collected_on}"
                ),
                dora_path.name if dora_path else "dora-YYYYMMDD.json",
                ST_GREEN if ev and ev > 0 else ST_YELLOW,
            ]
        )
        mttr = dora.get("mean_time_to_restore_hours")
        samples = dora.get("mean_time_to_restore_sample_count")
        valid_count = type(samples) is int and samples >= 0
        measured = (
            valid_count
            and samples > 0
            and type(mttr) in (int, float)
            and math.isfinite(mttr)
            and mttr >= 0
        )
        duration = f"{mttr:g} 小时" if measured else "未知"
        rows.append(
            [
                "DORA 平均恢复时长",
                "仅以明确恢复回执计量",
                f"{duration} / 有效恢复样本 {samples if valid_count else '未知'}",
                dora_path.name if dora_path else "dora-YYYYMMDD.json",
                ST_GREEN if measured else ST_YELLOW,
            ]
        )

    # --- E2E spec 数 ---
    e2e_specs = sorted(glob.glob(str(FHD_ROOT / "frontend" / "e2e" / "*.spec.ts")))
    e2e_count = len(e2e_specs)
    rows.append(
        [
            "前端 E2E spec 数",
            "有 E2E 套件",
            f"{e2e_count} 个 spec",
            "frontend/e2e/*.spec.ts",
            ST_GREEN if e2e_count > 0 else ST_RED,
        ]
    )

    # --- Android 端等级 ---
    a_claimed, a_actual, a_status = _android_levels()
    rows.append(
        [
            "Android 端交付等级",
            a_claimed,
            a_actual,
            "VERSION.md『各端交付等级』vs docs/guides/MOBILE_ANDROID.md",
            a_status,
        ]
    )

    # --- 退役口径黑名单 ---
    retired_rows: list[list[str]] = []
    for key, reason in (retired.get("values", {}) or {}).items():
        retired_rows.append(
            [
                f"退役口径 `{key}`",
                "（曾对外引用）",
                "已退役，禁止再引用",
                "coverage-dual-summary.json#_retired.values",
                f"{ST_RETIRED} {reason}",
            ]
        )

    return rows, retired_rows


def _md_table(header: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(header) + " |"]
    out.append("|" + "|".join(["---"] * len(header)) + "|")
    for r in rows:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


def render_doc() -> str:
    now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
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
        "生成时间只表示汇编时间；采样版本和日期取自原始凭据，不能作为当前 HEAD 的测试结果。"
    )
    parts.append("")
    parts.append("## 声称 vs 实测对照表")
    parts.append("")
    parts.append(_md_table(["维度", "声称", "实测", "数据源", "状态"], rows))
    parts.append("")
    parts.append(
        "**状态图例**：🟢 实测 ≥ 目标或证据已核验 · 🟡 floor ≤ 实测 < 目标或证据不足 · 🔴 实测 < floor 或 声称≠实测 · ⛔ 已退役口径"
    )
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
    return "\n".join(ln for ln in text.splitlines() if not ln.startswith(GEN_LINE_PREFIX))


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
        print(
            f"[FAIL] {OUTPUT_DOC} 已过期，与 metrics 不一致；请运行 gen_claimed_vs_actual.py 重新生成"
        )
        return 1

    OUTPUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_DOC.write_text(new_content, encoding="utf-8")
    print(f"[OK] 已生成 {OUTPUT_DOC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
