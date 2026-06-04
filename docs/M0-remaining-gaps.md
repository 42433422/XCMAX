# M0 剩余缺口（2026-06-05）

本地/文档侧 M0 工程项已基本闭环（**e2e 14/14** **`02a5d890`** / **`e2db1aaa`**、**vitest `src/api` 367/367** **`618e4ade`**、mypy 6/6、脚本/env 收口；可重建依赖外置 `~/XCMAX-archives/`，工作区仅指针）。**下列三项仍 `[ ]` 未闭**，不可在 CLAIMED 中标为 M0 完成。

| # | 状态 | 缺口 | 验收 | 阻塞 |
|---|------|------|------|------|
| 1 | **`[ ]`** | **staging 7 天流量 + SLO 截图** | `docs/evidence/slo/` 含 4 域 **staging** PNG + 7 天基线写入 CLAIMED | `specs/BLOCKERS.md` **T36–T37**（约 2026-09） |
| 2 | **`[ ]`** | **1 个真实 Mod 商家** | `docs/evidence/mod/01–04.png` | 商务/环境；见 [`mod-merchant-pilot.md`](mod-merchant-pilot.md) · [`mod-pilot-blockers.md`](mod-pilot-blockers.md) |
| 3 | **`[ ]`** | **SLO 四域 PNG**（**staging 优先**） | `grafana-staging-m0-*.png` 或 staging 7 天基线；本地可选 `grafana-local-m0-*.png` | **T36–T37**；[`local_stack_up.sh`](../scripts/observability/local_stack_up.sh) **≠** 本条验收（**`1b69f614`** 仅为脚手架） |

## 已达标（勿重复开工）

- **不含 `.git` 交付树 ~0.3G / ~285M**（SSOT ≤8 GB ✅；见 [`workspace-size-delivery-tree.md`](workspace-size-delivery-tree.md)）
- Playwright P0 全栈：`E2E_FULL_STACK=1 npm run test:e2e:p0` → **14/14**（mock + Vite :5001）
- API 契约：`npm run test -- src/api` → **367/367**
- AI Agent V0：mock + live JSON（**`82091ce6`** · **`087cf0a9`**）；[`evidence/ai-agent-v0/`](evidence/ai-agent-v0/)
- K8s 监控脚手架：Grafana 看板 / Prometheus 规则 / runbook（**`1b69f614`** · **`3b3d9627`**）
- 可观测：`local_stack_up.sh --check-only` 通过

## 体积（双口径，勿误标 M0 三项已闭）

| 口径 | 约体积 | M0 判定 |
|------|--------|---------|
| **交付树**（不含 `.git`） | **~285M / ~0.3G** | **≤8 GB ✅**（尽调 SSOT） |
| **`du -sh` 含 `.git`** | **~9.7G**（`FHD/.git` ~9.4G） | **仅跟踪**；**不等于**交付树未达标 |

plan 条文「工作区 ≤8G」若用 `du -sh` 含对象库仍会 **>8G**（主因 `.git`）；与 [`CLAIMED_VS_ACTUAL.md`](CLAIMED_VS_ACTUAL.md)「工作区体积」行、[`specs/weekly/2026-W24.md`](../../specs/weekly/2026-W24.md) 脚注一致。**勿**因交付树已达标而勾掉上表 **#1–#3**。

## 相关文档

- Staging SLO：[`k8s/monitoring/STAGING_RUNBOOK.md`](../k8s/monitoring/STAGING_RUNBOOK.md)
- Mod 试点：[`mod-merchant-pilot.md`](mod-merchant-pilot.md) · 阻塞清单 [`mod-pilot-blockers.md`](mod-pilot-blockers.md)
- 声称对照：[`CLAIMED_VS_ACTUAL.md`](CLAIMED_VS_ACTUAL.md)
- 阻塞 SSOT：[`specs/BLOCKERS.md`](../../specs/BLOCKERS.md)
- 本周周报：[`specs/weekly/2026-W24.md`](../../specs/weekly/2026-W24.md)
