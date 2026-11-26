# 对外声称 vs 实测（CLAIMED_VS_ACTUAL）

> 自动生成，请勿手改；源 `FHD/scripts/dev/gen_claimed_vs_actual.py`；生成于 2026-11-25T08:41:17Z

> 本文为「对外声称 vs 实测」对照的**单一事实来源（SSOT）**，由 `scripts/dev/gen_claimed_vs_actual.py` 从 `metrics/` 自动汇编。覆盖率唯一数字 SSOT 见 [`metrics/coverage-dual-summary.json`](../metrics/coverage-dual-summary.json)。生成时间只表示汇编时间；采样版本和日期取自原始凭据，不能作为当前 HEAD 的测试结果。

## 声称 vs 实测对照表

| 维度 | 声称 | 实测 | 数据源 | 状态 |
|---|---|---|---|---|
| 覆盖率证据范围 | 当前版本需独立验证 | 采集 2026-07-25T11:34:00Z / 来源 SHA 92505cab6；仅该采样版本，本版未验证 | coverage-dual-summary.json#committed_head | 🟡 |
| 后端行覆盖率（历史样本） | ≥90%（目标） | 88.19% | coverage-dual-summary.json#committed_head.backend_line_pct | 🟡 |
| 后端分支覆盖率（历史样本） | ≥85%（目标） | 81.5% | coverage-dual-summary.json#committed_head.backend_branch_pct | 🟡 |
| 前端行覆盖率（历史样本） | ≥80%（目标） | 93.21% | coverage-dual-summary.json#committed_head.frontend_line_pct | 🟡 |
| 前端分支覆盖率（历史样本） | ≥75%（目标） | 82.45% | coverage-dual-summary.json#committed_head.frontend_branch_pct | 🟡 |
| 前端函数覆盖率（历史样本） | ≥90%（floor） | 91.39% | coverage-dual-summary.json#committed_head.frontend_function_pct | 🟡 |
| 真实模型任务验收 | 当前版本需绑定 SHA 与原始任务凭据 | 本版未验证；历史状态 NOT_RUN / 模型实测标记 False / 采集 2026-11-24T10:46:52.200137+08:00 / 来源 SHA 1a5e1d194f1b361ea488bf9bd781a788f767419f；基准报告缺失：本次运行未产出 task_benchmark_report.json | benchmark_run_mode.json | 🟡 |
| 后端行 floor（fail_under 交叉校验） | 棘轮 floor=78 | pyproject fail_under=78 | pyproject.toml fail_under vs coverage-dual-summary.json#ratchet_floors.backend_line | 🟢 |
| 覆盖率趋势（历史 2026-06-26） | 保留历史采样，不代表当前版本 | 后端行 90.69% / 前端行 93.21% | coverage-history.jsonl（最后一行） | 🟡 |
| 健康探针 /api/health | P50 < 500ms 预算 | 11.23ms（status 200） | sla-snapshot.json#probe.probe_result.health | 🟢 |
| DORA 部署频率 | 持续交付 | 环境 production / 窗口 7d / 事件 4 / 频率 0.4286/d / 采集日 2026-11-25 | dora-20261125.json | 🟢 |
| DORA 平均恢复时长 | 仅以明确恢复回执计量 | 未知 / 有效恢复样本 0 | dora-20261125.json | 🟡 |
| 前端 E2E spec 数 | 有 E2E 套件 | 19 个 spec | frontend/e2e/*.spec.ts | 🟢 |
| Android 端交付等级 | 实验骨架 | 实验骨架·非签约级 | VERSION.md『各端交付等级』vs docs/guides/MOBILE_ANDROID.md | 🟢 |

**状态图例**：🟢 实测 ≥ 目标或证据已核验 · 🟡 floor ≤ 实测 < 目标或证据不足 · 🔴 实测 < floor 或 声称≠实测 · ⛔ 已退役口径

## 已退役口径（黑名单，禁止对外引用）

| 维度 | 声称 | 实测 | 数据源 | 状态 |
|---|---|---|---|---|
| 退役口径 `full_app_60_63` | （曾对外引用） | 已退役，禁止再引用 | coverage-dual-summary.json#_retired.values | ⛔ 富依赖环境 + 历史窄 include 混报（2026-06-04） |
| 退役口径 `ci_narrow_70` | （曾对外引用） | 已退役，禁止再引用 | coverage-dual-summary.json#_retired.values | ⛔ 窄包 include/omit 门禁（2026-06-08 前）；已改为全量 source=[app] + coverage_ratchet.py |
| 退役口径 `claimed_77_4_or_88` | （曾对外引用） | 已退役，禁止再引用 | coverage-dual-summary.json#_retired.values | ⛔ 周报误报，2026-06-08 已撤回 |

