# 覆盖率与棘轮

本文是覆盖率领域 SSOT 的维护入口，具体阈值以配置为准。

当前门槛以 [`pyproject.toml`](../../pyproject.toml)、[`coverage_ratchet_baseline.json`](../../metrics/coverage_ratchet_baseline.json) 和 [`vitest.config.js`](../../frontend/vitest.config.js) 为准；历史测量不能代表当前提交。

后端同时测量行与分支，标准采集使用 `--cov --cov-branch --cov-fail-under=0 --cov-report=json:coverage.json`，再运行 `python scripts/dev/coverage_ratchet.py --check --require-backend`。前端在 `FHD/frontend` 运行 `CI=true npm run test:coverage`。

全量测试通过后才可用 `python scripts/dev/coverage_ratchet.py --bump` 提升基线；历史趋势使用 `--history`。门槛来源和检验逻辑见 [`docs/CI_SSOT.md`](../../../docs/CI_SSOT.md) 和 [ADR-0005](../adr/0005-coverage-floor-recalibrate-stub-retirement.md)。
