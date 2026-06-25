# Postmortem：v10 CI 基线恢复（42 failed → 门禁可演示）

## 摘要

| 字段 | 内容 |
|------|------|
| 严重级别 | SEV-2（主分支 CI 长期黄） |
| 基线 | [`pytest-full-last.txt`](../../FHD/test_reports/pytest-full-last.txt)（最近一次全量 pytest 快照；旧 `pytest-v10-baseline.txt` 未随仓保留） |
| 目标 | `0 failed / 0 errors / 0 xpassed` |

## 影响

- GitHub `backend-test` 全量 pytest + `--cov-fail-under=70` 失败时，尽调判定「不可发布」。
- 历史快照：42 failed、2 errors、1083 xpassed（旧基线）。

## 根因分类

| 簇 | 代表用例 | 根因 |
|----|----------|------|
| unified_ledger | `phase7_routes` | mock 目标迁移至 `user_cs_app_service` |
| inventory | `test_inventory_repository_impl` | fixture / seed 与 sqlite 对齐 |
| 收集/导入 | 18 collection errors | 缺失符号、错误 re-export、marshmallow 4 |
| 环境 | 500+ 本地失败 | 本机 `.env` 指向 Postgres，CI 无此问题 |

## 修复摘要（2026-06-04）

- 恢复 `sqlite_per_mod_copies_enabled`、`DataScope`/`Tenant` 导出、token Redis 锁。
- `_deployment_is_production` + `_neuro_reliability_wanted(production_default=)`。
- `register_legacy_gap_routers` 从 `fastapi_routes` 再导出。
- 尽调文档：`DUE_DILIGENCE_CI.md`、`DUE_DILIGENCE_RELIABILITY.md`。

## 行动项

| 项 | Owner | 状态 |
|----|-------|------|
| Windows `backend-test` 全绿 | 平台 | 跟踪中 |
| 本地与 CI 统一 sqlite 默认 | 测试 | 完成（conftest） |
| OpenAPI drift 硬失败 | CI | 完成 |

## 48h RCA

本报告于基线修复启动后 48h 内落盘，满足 [SLO.md](../../FHD/docs/SLO.md) 错误预算耗尽时的 RCA 要求（工程效能类）。
