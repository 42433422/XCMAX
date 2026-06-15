# 计划阻塞项（需 staging / 外部资源）

> 配套 [`plan-2026-06-checklist.md`](plan-2026-06-checklist.md) · 下列任务**不得**在无资源时标为完成。

| 任务 | 阻塞原因 | 建议继续方 | 最早可开工 |
|------|----------|------------|------------|
| **T36–T37** staging SLO 截图（合同级实跑） | Round-1 已归档无效；**Round-2 k6 已启动**（2026-06-12）；满 168h 后 `run_staging_7d_acceptance.sh` + SRE 签字 | SRE / 平台 | Round-2 ETA +7d |
| **T56** 生产 AI 月报 | SYNTHETIC/SEED 已填；需 staging/生产只读库复核 | 业务分析 + 后端 | 2026-11 |
| **T59** split push | dry-run 清单已就绪；需 `git-filter-repo` + remote push 窗口 | 发布工程 / DevOps | 2026-10 |
| ~~**T45**~~ | **2026-06 已迁**：归档至 `FHD/docs/_archive/FHD-个人/`，仓根 stub | — | — |
| ~~**T58/T60**~~ | **2026-06 部分完成**：个人账号 3 空仓 + README 总览；org remote 待 Owner | — | — |
| ~~**T28**~~ | **2026-06 已收口**：`sqlite_write_guard` → `session_cache.py` + shim | — | — |
| ~~**T27**~~ | **2026-06 已收口** | — | — |

未列出的 P0/P1 项若依赖本机 `git rm --cached` 或 Windows 路径，由对应 P0 worker 在仓根卫生 PR 中处理。

---

## 本地可复现（非 staging 阻塞）

| 项 | 路径 |
|----|------|
| Prometheus + Grafana compose | [`FHD/scripts/observability/local_stack_up.sh`](../FHD/scripts/observability/local_stack_up.sh) |
| SYNTHETIC AI 月报 | [`FHD/scripts/ai_evidence/seed_synthetic_evidence.py`](../FHD/scripts/ai_evidence/seed_synthetic_evidence.py) |
| Split dry-run 清单 | [`成都修茈科技有限公司/docs/migration/SPLIT_DRY_RUN_MANIFEST.json`](../成都修茈科技有限公司/docs/migration/SPLIT_DRY_RUN_MANIFEST.json) |

---

## T27 — ~~删除 `app/db/ensure_mod_postgres.py`~~（2026-06 已收口）

- 实现：`scripts/bootstrap_mod_dbs.ensure_postgres_per_mod_databases`
- 入口：`app/db/bootstrap_mod.py`（`lifespan` / `db_init` 已切换）

---

## T28 — ~~合并 `sqlite_write_guard.py` → `session_cache.py`~~（2026-06 已收口）

- 实现：`app/db/session_cache.py` 导出 `sqlite_write_guard` + `ThreadSafeLRUCache`
- 兼容：`app/db/sqlite_write_guard.py` 为 re-export shim（单测 patch 已切至 `session_cache`）
- 引用：`customer_app_service` 直接 `from app.db.session_cache import sqlite_write_guard`
