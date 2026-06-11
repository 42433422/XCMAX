# Runbook — 测试质量运行员

| 字段 | 值 |
|------|----|
| 员工 ID | `test-qa-runner` |
| 版本 | 2.0.2 |
| 最后更新 | 2026-05-08 |
| 应急联系 | admin |

## 日常巡检

环境指纹：pytest 首轮输出 `[pytest-env]`，Playwright `globalSetup` 输出 `[playwright-env]`。与 CI 对照时可比对其中的 Python/Node 版本与锁文件摘要。设 `MODSTORE_TEST_ENV_QUIET=1` 可关闭 pytest 指纹行。

```bash
# MODstore 后端测试
cd MODstore_deploy
python -m pytest tests/ -q --tb=short

# vibe-coding 测试
cd vibe-coding
python -m pytest tests/ -q --tb=short

# vibe-coding：仅 Agent 子目录（多 Agent 协同 / 军团式编排回归）
cd vibe-coding
python -m pytest tests/agent/ -q --tb=short
python -m pytest tests/agent/ --cov=src/vibe_coding/agent --cov-report=term-missing -q

# MODstore 后端覆盖率
cd MODstore_deploy
python -m pytest tests/ --cov=modstore_server --cov-report=term-missing -q

# vibe-coding 覆盖率
cd vibe-coding
python -m pytest tests/ --cov=src/vibe_coding --cov-report=term-missing -q

# Market 前端单测 + 覆盖率
cd MODstore_deploy/market
npx vitest run --coverage

# TypeScript 类型检查
cd MODstore_deploy/market
npx vue-tsc --noEmit -p tsconfig.strict-baseline.json

# Playwright E2E
npx playwright test --reporter=html

# 覆盖率门禁
cd MODstore_deploy
python -m pytest tests/test_coverage_gates.py -v

# pre-commit hook 检查
pre-commit run --all-files
```

## 失败码与 `log-monitor-incident` 对齐（`.cursor/contracts/error-code-map.yaml`）

CI / 本地套件失败时，在摘要或 PR 评论中为每条失败 **附加 `code` 标签**，便于与 `log-monitor-incident` 的 `triage_entries` 及服务台路由一致：

1. 根据失败来源选择 `source`：`pytest` | `playwright` | `vitest` | `cursor_log`（若为 agent 日志）。
2. 对 traceback / stderr 行依次匹配 **`error-code-map.yaml` 的 `entries[].pattern`（Python `re`）**；命中则输出 `code`（如 `MS-E2E-TIMEOUT`）、`root_cause_class`、`recommended_owner_employee`。
3. 未命中时输出 `code: UNMAPPED`，并在纪要中贴 **≤400 字符** 的原文片段，供扩充契约（变更契约需 admin 审批）。
4. Prometheus / 告警名类失败由 `log-monitor-incident` 主导映射；本员工在 E2E 报告中引用同一文件即可保持标签一致。

## 异常处置

### 异常 1：pytest 失败（非 flaky）

1. 解析失败 case 和 traceback。
2. 判断是测试 bug 还是被测代码 bug。
3. 测试 bug：修复测试 case；被测代码 bug：通知对应员工（`modstore-backend-api`/`vibe-coding-maintainer`）。

### 异常 2：Playwright E2E 失败

1. 查看 `playwright-report/` 中的截图和 trace。
2. 判断是前端问题还是环境问题。
3. 前端问题通知 `market-frontend-dev`/`workbench-ux-stylist`。
4. 环境问题通知 `deploy-release-officer`。

### 异常 3：pre-commit hook 阻断提交

1. 确认 hook 触发的具体 linter 错误。
2. 如属于 linter 误报，评估是否更新规则（不绕过 hook）。
3. 如 hook 缺失，补充对应 linter/formatter 的 hook 配置。

### 异常 4：vitest 单测失败

1. 解析失败 case 的错误信息和堆栈。
2. 判断是测试 bug 还是前端源码 bug。
3. 测试 bug：修复测试文件（仅限 `*.test.ts`/`*.spec.ts`）。
4. 前端 bug：通知 `market-frontend-dev` 修复。

### 异常 5：TypeScript 类型检查失败

1. 解析类型错误，按严重程度分类（P0：编译阻断 / P1：类型不安全 / P2：any 推断）。
2. 生成修复建议并通知 `market-frontend-dev`。
3. 不自行修改前端源码。

### 异常 6：覆盖率门禁未通过

1. 识别未达标的模块和覆盖率缺口。
2. 分析缺口原因（新增代码未覆盖 / 测试被删除 / 代码重构导致覆盖率下降）。
3. 生成补充测试建议，通知对应员工补充测试。
4. 覆盖率下降 > 5% 时主动补充测试 case。

### 异常 7：pre-commit hook 缺失或过时

1. 对比项目实际使用的 linter/formatter（ruff、eslint、prettier）与现有 hook。
2. 生成缺失 hook 的配置 diff。
3. 验证新 hook 可执行后更新 `.pre-commit-config.yaml`。

### 异常 8：CI 测试步骤不完整

1. 审查 `.github/workflows/ci-*.yml` 中的测试步骤。
2. 识别缺失的测试框架（pytest/vitest/playwright/vue-tsc）。
3. 生成 CI 配置更新建议，通知 `deploy-release-officer` 执行。

### 异常 9：vibe-coding `tests/agent/` 失败

1. 在仓库根确认 `cd vibe-coding` 后再执行 pytest；依赖使用 `pip install -e ".[test]"`（见 `vibe-coding/pyproject.toml`）。
2. 阅读失败用例模块名：编排类失败优先看 `tests/agent/test_orchestration.py`；沙盒/Docker 类检查是否缺可选依赖或环境隔离。
3. 判定为被测代码缺陷时 **不** 修改 `vibe-coding/src/**`，通知 `vibe-coding-maintainer` 修复并补充单测。

## ESkill 动态阶段触发记录

| 日期 | 触发原因 | patch_id | 结果 | 是否固化 |
|------|----------|----------|------|----------|
| — | — | — | — | — |
