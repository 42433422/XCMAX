# 覆盖率分阶段提升与守护机制

**最后更新**：2026-07-18

本文是覆盖率治理契约的 SSOT；可变数字仍以各层机器可读文件为准。

覆盖率数据分为三层。三层用途不同，禁止互相冒充。

## 三层真相契约

### 1. 门槛层（threshold）

- 后端行门槛：[`pyproject.toml`](../../pyproject.toml) 的
  `[tool.coverage.report].fail_under`。
- 后端分支和前端各项门槛：
  [`metrics/coverage_ratchet_baseline.json`](../../metrics/coverage_ratchet_baseline.json)。
- [`frontend/vitest.config.js`](../../frontend/vitest.config.js) 的 thresholds 是前端门槛派生件，
  由 `coverage_ratchet.py --bump` 同步。

具体数值只从这些文件读取，不在文档中复制“当前值”。

### 2. 实测层（measurement）

- 后端：本次测试生成的 `coverage.json`。
- 前端：本次测试生成的 `frontend/coverage/coverage-summary.json`。
- 后端生产 job 必须运行 `coverage_ratchet.py --check --require-backend`。
- 前端生产 job 必须运行 `coverage_ratchet.py --check --require-frontend`。

实测产物是单次 CI 的临时证据。缺产物必须失败，不能静默跳过，也不能拿历史文件补位。

### 3. 对外口径层（publication）

[`metrics/coverage-dual-summary.json`](../../metrics/coverage-dual-summary.json) 是带采集日期的
已发布快照；[`metrics/coverage-history.jsonl`](../../metrics/coverage-history.jsonl) 保存趋势。
发布快照可以展示一次已确认的结果，但不得反向决定门槛，也不得冒充当前 CI 实测。

## 行/分支独立统计

`coverage.py` 开启 `branch=true` 后，`percent_covered` 是行与分支的合并指标。为保持
`fail_under` 只表达后端行门槛：

- `[tool.coverage.run] branch = true`：一次测量同时生成行与分支原始计数。
- 标准 pytest 命令传 `--cov-fail-under=0`，关闭 coverage.py 的合并指标门禁。
- `scripts/dev/coverage_ratchet.py --check` 从 `coverage.json` 原始计数分别计算行和分支，
  再与门槛层比较。

## 覆盖率棘轮（只升不降）

```bash
# 后端 CI：产物缺失或覆盖率回退都失败
python scripts/dev/coverage_ratchet.py --check --require-backend

# 前端 CI：产物缺失或覆盖率回退都失败
python scripts/dev/coverage_ratchet.py --check --require-frontend

# 全量测试通过后提升门槛，并同步派生件/发布快照元数据
python scripts/dev/coverage_ratchet.py --bump

# 查看历史趋势
python scripts/dev/coverage_ratchet.py --history
```

## 可复现实测

```bash
# 后端
cd FHD
XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 .venv/bin/python -m pytest tests/ \
  --cov --cov-branch --cov-fail-under=0 \
  --cov-report=json:coverage.json --cov-report=term-missing -q
python scripts/dev/coverage_ratchet.py --check --require-backend

# 前端
cd FHD/frontend
CI=true npm run test:coverage
cd ..
python scripts/dev/coverage_ratchet.py --check --require-frontend
```

每次提升门槛前必须满足：相关测试全绿、实测产物存在、棘轮检查通过。历史窄包覆盖率、
富依赖环境数字和未全绿工作区数字仅可作为归档，禁止再作为当前门槛、当前实测或对外口径。
