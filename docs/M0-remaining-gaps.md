# M0 剩余缺口（2026-06-05）

本地/文档侧 M0 工程项已基本闭环（e2e 14/14、mypy 6/6、脚本/env 收口；可重建依赖外置 `~/XCMAX-archives/m0-venv-20260605/` ~1.6G，工作区仅指针）。**仓根 `du -sh Desktop/XCMAX` ~9.8G**（2026-06-05 实删后复扫：自 ~11G 去掉与 `~/XCMAX-archives/m0-venv-20260605/` 重复的 `FHD/.venv` + `FHD/frontend/node_modules` 实体（frontend ~744M；`.venv` 此前已仅指针）；工作区两路径仅 `ARCHIVE_POINTER.md`；含 `FHD/.git` ~9.4G；[`plan-2026-06.md`](../../specs/plan-2026-06.md) 工作区 ≤8G **未达标**）。**下列三项仍缺**，不可在 CLAIMED 中标为完成。

| # | 缺口 | 验收 | 阻塞 |
|---|------|------|------|
| 1 | **staging 7 天流量 + SLO 截图** | `docs/evidence/slo/` 含 4 域 PNG + 7 天基线写入 CLAIMED | `specs/BLOCKERS.md` **T36–T37**（约 2026-09） |
| 2 | **1 个真实 Mod 商家** | `docs/evidence/mod/01–04.png` | 商务/环境；见 [`mod-merchant-pilot.md`](mod-merchant-pilot.md) · 阻塞 [`mod-pilot-blockers.md`](mod-pilot-blockers.md) |
| 3 | **Docker 本地 SLO PNG** | `grafana-local-m0-*.png` 入 `docs/evidence/slo/` | 本机需 Docker；[`local_stack_up.sh`](../scripts/observability/local_stack_up.sh) |

## 已达标（勿重复开工）

- **不含 `.git` 交付树 ~0.3G**（2026-06-05；bulk/models 等见仓根 `ARCHIVE_POINTER.md` 与 `~/XCMAX-archives/`）
- Playwright P0：`npm run test:e2e:p0` → 14/14（mock + Vite :5001）
- 可观测：`local_stack_up.sh --check-only` 通过

## 体积（plan SSOT，勿误标已闭环）

- **工作区 `du -sh Desktop/XCMAX` ~9.8G**（含 `FHD/.git` ~9.4G；不含 `.git` 交付树 ~0.3G；`FHD/.venv` / `FHD/frontend/node_modules` 无实体）— plan ≤8G **未达标**；与 [`CLAIMED_VS_ACTUAL.md`](CLAIMED_VS_ACTUAL.md)「工作区体积」行一致（判定：夸大）

## 相关文档

- Staging SLO：[`k8s/monitoring/STAGING_RUNBOOK.md`](../k8s/monitoring/STAGING_RUNBOOK.md)
- Mod 试点：[`mod-merchant-pilot.md`](mod-merchant-pilot.md) · 阻塞清单 [`mod-pilot-blockers.md`](mod-pilot-blockers.md)
- 声称对照：[`CLAIMED_VS_ACTUAL.md`](CLAIMED_VS_ACTUAL.md)
- 阻塞 SSOT：[`specs/BLOCKERS.md`](../../specs/BLOCKERS.md)
