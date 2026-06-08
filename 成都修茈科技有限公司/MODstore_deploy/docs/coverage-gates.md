# MODstore 覆盖率双轨说明

与 FHD [`COVERAGE_RAMP.md`](../../../FHD/docs/reports/COVERAGE_RAMP.md) 对齐：CI 使用**分层门禁**，避免「全局 floor 低、关键路径无保障」的错觉。

## 双轨对照

| 轨道 | 范围 | CI 行为 | 当前值 |
|------|------|---------|--------|
| **全局 floor** | `modstore_server` 等（`MODSTORE_PY_COVERAGE_FLOOR`） | `ci-backend-python.yml` **硬失败** | **55%**（路线图 43→55→80） |
| **关键模块** | `payment_api.py`、`webhook_dispatcher.py`、合同包等 | 单独 `--fail-under` | **80%** / webhook **60%** |
| **Market 前端** | `paymentApi.ts` 等 | `ci-market.yml` Vitest thresholds | lines **80%** |
| **Java 支付** | 合同包 JaCoCo | `ci-payment-java.yml` `mvn verify` | line **80%** |

## 合并前检查

- 改支付 / webhook / 履约路径：本地 `pytest tests/test_coverage_gates.py` + 相关模块 `pytest --cov=... --cov-fail-under=80`
- PR 描述附 CI `ci-backend-python` 与 `ci-payment-java` 链接或覆盖率截图

## 集成测试入口

- 单元：`MODstore_deploy/tests/test_webhook_dispatcher.py`
- 集成：`MODstore_deploy/tests/integration/test_payment_webhook_flow.py`（验签 + 幂等 event id + replay）
