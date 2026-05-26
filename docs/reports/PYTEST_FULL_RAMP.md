# 全量 Pytest 收敛计划（782 用例）

## 当前（2026-05-26）

| 指标 | 数值 |
|------|------|
| 收集 | **782** |
| 全量（无 skip） | **755 通过 / 23 失败 / 1 skip**（2026-05-26 收尾轮） |
| CI 稳定子集 `CI_STABLE_ONLY=1` | **~127+ 通过**，其余 skip |

## 已修簇

- 发货 `Quantity`、微信任务、产品服务、excel_utils、NeuroBus 核心测试、打印机服务、DB 读 token（ERP 短路）

## 剩余失败 Top 簇（约 23）

1. `test_edition_policy`（全量套件顺序污染，单文件 8/8 通过）
2. `test_db/test_models`、`test_services/test_orm_models`（SQLite 内存 FK/元数据）
3. `test_platform_shell`、`test_neuro_migration_smoke`、零散集成
4. `test_start_lan_launcher`（控制台 UI 在非交互环境）
5. `benchmarks/test_intent_accuracy`（已 skip，需 `INTENT_BENCHMARK_RUN=1`）

## 阶段

- **A**：维持 `CI_STABLE_ONLY` 扩面（每修一文件加入 `conftest` 片段）
- **B**：按上表簇逐个清零，每周目标失败数 < 30
- **C**：去掉 `CI_STABLE_ONLY`，全量进 CI（目标 0 失败）

本地全量：`python -m pytest tests/ -q`  
稳定子集：`$env:CI_STABLE_ONLY='1'; python -m pytest tests/ -q`
