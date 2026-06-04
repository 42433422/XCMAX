# M0 剩余缺口（2026-06-05）

本地/文档侧 M0 已基本闭环（仓根 **~7.8 GB**、e2e 14/14、mypy 6/6、脚本/env 收口）。**下列三项仍缺**，不可在 CLAIMED 中标为完成。

| # | 缺口 | 验收 | 阻塞 |
|---|------|------|------|
| 1 | **staging 7 天流量 + SLO 截图** | `docs/evidence/slo/` 含 4 域 PNG + 7 天基线写入 CLAIMED | `specs/BLOCKERS.md` **T36–T37**（约 2026-09） |
| 2 | **1 个真实 Mod 商家** | `docs/evidence/mod/01–04.png` | 商务/环境；见 `mod-merchant-pilot.md` |
| 3 | **Docker 本地 SLO PNG** | `grafana-local-m0-*.png` 入 `docs/evidence/slo/` | 本机需 Docker；[`local_stack_up.sh`](../scripts/observability/local_stack_up.sh) |

## 已达标（勿重复开工）

- 工作区体积 ≤8 GB（plan SSOT）
- Playwright P0：`npm run test:e2e:p0` → 14/14（mock + Vite :5001）
- 可观测：`local_stack_up.sh --check-only` 通过

## 相关文档

- Staging SLO：[`k8s/monitoring/STAGING_RUNBOOK.md`](../k8s/monitoring/STAGING_RUNBOOK.md)
- Mod 试点：[`mod-merchant-pilot.md`](mod-merchant-pilot.md)
- 声称对照：[`CLAIMED_VS_ACTUAL.md`](CLAIMED_VS_ACTUAL.md)
- 阻塞 SSOT：[`specs/BLOCKERS.md`](../../specs/BLOCKERS.md)
