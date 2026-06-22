# MODstore 覆盖率双轨说明

与 FHD [`COVERAGE_RAMP.md`](../../../FHD/docs/reports/COVERAGE_RAMP.md) 对齐：CI 使用**分层门禁**，避免「全局 floor 低、关键路径无保障」的错觉。

## 哪份 workflow 真正运行（重要）

后端 Python workflow 是 **CI SSOT**：作者编辑
`MODstore_deploy/.github/workflows/ci-backend-python.yml`，由
`scripts/dev/publish_ci_workflows_to_root.py` 发布到 **XCMAX 仓库根**
`.github/workflows/modstore-ci-backend-python.yml`——**GitHub Actions 实际跑的是根的那份**。
改门禁必须改发布源并重跑 publisher，否则改动不会生效。
（`成都修茈科技有限公司/.github/workflows/ci-backend-python.yml` 是历史遗留副本，publisher 不读它，
不会进入 CI；保留仅为与发布源对齐，floor 也已对齐。）

## 双轨对照（目标 vs 当前实际执行）

> 诚实声明：全局 floor 的"当前执行值"= **40%**。这是**保守值**，本地未实测
> （`xcagi_common` 要求 Python>=3.10，沙箱仅 3.9 跑不动覆盖率），取 `pyproject.toml`
> 自承的"全量 tree 约 40%+"。它是**棘轮**：能挡回归、只可上调。**80% 是路线图目标，尚未达成**，
> 别把它当成"已经在执行的门禁"。补测并实测出真实数字后再上调 floor。

| 轨道 | 范围 | CI 行为 | 路线图目标 | **当前实际执行值** |
|------|------|---------|-----------|------------------|
| **全局 floor** | `modman` + `modstore_server`（`MODSTORE_PY_COVERAGE_FLOOR`） | 运行的根 `modstore-ci-backend-python.yml` `--cov-fail-under` **硬失败** | 80%（43→…→80） | **40%（保守、未实测）** |
| **关键模块** | `payment_api.py`、`webhook_dispatcher.py`、合同包等 | 单独 `--fail-under`（见发布源/孤儿副本中的 per-module 步骤） | 80% / webhook 60% | 80% / webhook 60% |
| **Market 前端** | `paymentApi.ts` 等 | `ci-market.yml` Vitest thresholds | lines 80% | lines 80% |
| **Java 支付** | 合同包 JaCoCo | `ci-payment-java.yml` `mvn verify` | line 80% | line 80% |

## 合并前检查

- 改支付 / webhook / 履约路径：本地 `pytest tests/test_coverage_gates.py` + 相关模块 `pytest --cov=... --cov-fail-under=80`
- PR 描述附 CI `ci-backend-python` 与 `ci-payment-java` 链接或覆盖率截图

## 集成测试入口

- 单元：`MODstore_deploy/tests/test_webhook_dispatcher.py`
- 集成：`MODstore_deploy/tests/integration/test_payment_webhook_flow.py`（验签 + 幂等 event id + replay）
