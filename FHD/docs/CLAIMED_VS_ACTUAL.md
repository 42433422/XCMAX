# 对外声称 vs 实测（CLAIMED_VS_ACTUAL）

> 自动生成，请勿手改；源 `FHD/scripts/dev/gen_claimed_vs_actual.py`；生成于 2026-06-21T15:45:00Z

> 本文为「对外声称 vs 实测」对照的**单一事实来源（SSOT）**，由 `scripts/dev/gen_claimed_vs_actual.py` 从 `metrics/` 自动汇编。覆盖率唯一数字 SSOT 见 [`metrics/coverage-dual-summary.json`](../metrics/coverage-dual-summary.json)。

## 声称 vs 实测对照表

| 维度 | 声称 | 实测 | 数据源 | 状态 |
|---|---|---|---|---|
| 后端行覆盖率 | ≥90%（目标） | 85.07% | coverage-dual-summary.json#committed_head.backend_line_pct | 🟡 |
| 后端分支覆盖率 | ≥85%（目标） | 74.22% | coverage-dual-summary.json#committed_head.backend_branch_pct | 🟡 |
| 前端行覆盖率 | ≥80%（目标） | 90.03% | coverage-dual-summary.json#committed_head.frontend_line_pct | 🟢 |
| 前端分支覆盖率 | ≥75%（目标） | 80.02% | coverage-dual-summary.json#committed_head.frontend_branch_pct | 🟢 |
| 前端函数覆盖率 | ≥77%（floor） | 77.2% | coverage-dual-summary.json#committed_head.frontend_function_pct | 🟢 |
| 后端行 floor（fail_under 交叉校验） | 棘轮 floor=84 | pyproject fail_under=84 | pyproject.toml fail_under vs coverage-dual-summary.json#ratchet_floors.backend_line | 🟢 |
| 覆盖率趋势（最新 2026-06-20） | 趋势上行 | 后端行 84.46% / 前端行 89.98% | coverage-history.jsonl（最后一行） | 🟡 |
| 健康探针 /api/health | P50 < 500ms 预算 | 5.02ms（status 200） | sla-snapshot.json#probe.probe_result.health | 🟢 |
| DORA 部署频率 | 持续交付 | 窗口 7d / 事件 0 / 频率 0.0/d | dora-20260613.json | 🟡 |
| 前端 E2E spec 数 | 有 E2E 套件 | 10 个 spec | frontend/e2e/*.spec.ts | 🟢 |
| Android 端交付等级 | 实验骨架 | 实验骨架·非签约级 | VERSION.md『各端交付等级』vs docs/guides/MOBILE_ANDROID.md | 🟢 |

**状态图例**：🟢 实测 ≥ 目标 · 🟡 floor ≤ 实测 < 目标 · 🔴 实测 < floor 或 声称≠实测 · ⛔ 已退役口径

## 已退役口径（黑名单，禁止对外引用）

| 维度 | 声称 | 实测 | 数据源 | 状态 |
|---|---|---|---|---|
| 退役口径 `full_app_60_63` | （曾对外引用） | 已退役，禁止再引用 | coverage-dual-summary.json#_retired.values | ⛔ 富依赖环境 + 历史窄 include 混报（2026-06-04） |
| 退役口径 `ci_narrow_70` | （曾对外引用） | 已退役，禁止再引用 | coverage-dual-summary.json#_retired.values | ⛔ 窄包 include/omit 门禁（2026-06-08 前）；已改为全量 source=[app] + coverage_ratchet.py |
| 退役口径 `claimed_77_4_or_88` | （曾对外引用） | 已退役，禁止再引用 | coverage-dual-summary.json#_retired.values | ⛔ 周报误报，2026-06-08 已撤回 |

