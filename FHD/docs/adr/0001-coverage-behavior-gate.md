# ADR-0001 后端覆盖率门禁口径从「全量」切换为「行为」（排除 coverage_ramp stub）

- 状态：已采纳（2026-08-05）
- 决策者：DevOps / 工程负责人
- 关联 Issue：Delta A（P0-1：后端覆盖率门禁诚实化）
- 涉及文件：
  - `scripts/dev/coverage_ratchet.py`
  - `metrics/coverage_ratchet_baseline.json`
  - `pyproject.toml` `[tool.coverage.report] fail_under`
  - `.github/workflows/ci-cd.yml`
  - `tests/test_dev/test_coverage_ratchet_behavior.py`

## 背景

CI 后端覆盖率门禁此前测的是**含 87 个 `coverage_ramp` stub 的全量套件**
（`pytest tests/ --cov`，`coverage.json`）。这些 stub（`test_coverage_ramp_*.py`，
约 5274 用例，占 ~25%）由 `tests/conftest.py` 按文件名前缀自动打标，pyproject markers
自承「断言弱、杀变体能力低；非行为契约测试」。它们抬高行覆盖率口径，但**不构成行为契约**。

真实行为口径（`pytest -m 'not coverage_ramp'`）此前只在 `ci-cd.yml` 中**信息性展示**
（`|| true` + `continue-on-error`），不阻断流水线。结果：
- 对外声称的覆盖率被 stub 注水，无法反映真实行为覆盖；
- 行为覆盖率的真实回落无法被门禁捕获，存在静默退化风险。

## 决策

把后端覆盖率门禁的**唯一硬 gate 切换为行为口径**：

1. `coverage_ratchet.py` 新增 `--behavior` 模式，读 `coverage-behavior.json`
   （`pytest -m 'not coverage_ramp' --cov --cov-branch --cov-report=json:coverage-behavior.json`），
   计算纯行/分支覆盖率，与 `coverage_ratchet_baseline.json` 新增的
   `behavior_floors {lines, branches}` 比对，回退即退出码 1。
2. 复用现有 jitter（±0.5pt）与只升不降逻辑；不带 `--behavior` 时行为完全不变（向后兼容）。
3. `ci-cd.yml` 的 `Behavior coverage gate` 步骤从 `|| true` 改为
   `coverage_ratchet.py --check --behavior --require-backend --record`（硬阻断）。
4. `behavior_floors` 按本次实测值减安全余量（诚实值）设定，只升不降收口。
5. 全量口径（`coverage.json` + `fail_under`）保留为**参考/趋势**，不再作为唯一硬 gate，
   但 `fail_under` 仍是行覆盖率的 SSOT 字符串，不删除。

## 实测对照（2026-08-05，.venv = CI 等价依赖）

| 口径 | 行覆盖率 | 分支覆盖率 | 说明 |
|------|--------:|--------:|------|
| 全量（含 87 stub） | ~88% | ~81% | 历史基线，含注水 |
| 行为（排除 stub） | （见下方） | （见下方） | Delta A 采纳后唯一硬 gate |

> 行为实测值由本次 `XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/ -q -m 'not coverage_ramp' --cov --cov-branch --cov-report=json:coverage-behavior.json --cov-fail-under=0`
> 实测得到，记录于 `coverage_ratchet_baseline.json` 的 `last_measured.behavior_*`。

## 新 floor（诚实值）

`metrics/coverage_ratchet_baseline.json` 新增：

```json
"behavior_floors": {
  "lines": <行为行实测 - margin>,
  "branches": <行为分支实测 - margin>
}
```

行为行实测低于全量 `fail_under`（88），故 `pyproject.toml` 的 `fail_under` 是否需要下调
以本 ADR 为前提条件（`guard_coverage_floor.py` 强制把关）。此处不再下调 `fail_under`
字符串本身——它保留为全量口径的行 floor SSOT；行为硬 gate 由 `behavior_floors` 独立承担。

## 后果

- **正面**：门禁反映真实行为覆盖；stub 注水不再掩盖退化；CI 硬阻断行为覆盖回退。
- **代价**：行为实测值低于历史全量声称值，首次采纳后 CI 行为 gate 以诚实值放行，
  后续只能通过补行为测试提升（`--bump --behavior` 只升不降）。
- **兼容**：未启 `--behavior` 的既有调用（本地 / 打包产物）行为不变。