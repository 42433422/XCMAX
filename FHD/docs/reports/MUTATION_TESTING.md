# 变异测试（mutmut / Stryker）

> v10 线内迭代 · 2026-08-05 更新 · 与 [`COVERAGE_RAMP.md`](COVERAGE_RAMP.md) Phase 4 对齐

## 后端（mutmut）

作用域：`app/di` + `app/contexts`（见 [`pyproject.toml`](../../pyproject.toml) `[tool.mutmut] source_paths`）。
测试选择：`tests/test_di` + `tests/test_contexts`。

```bash
cd FHD
uv pip install mutmut
uv run mutmut run          # 作用域：app/di + app/contexts
uv run mutmut results      # 查看存活变异
uv run mutmut show <id>    # 查看单个变异 diff
```

可复现门禁命令：

```bash
uv run mutmut run && uv run python scripts/dev/mutation_kill_report.py --threshold 80
```

### 实测基线（2026-08-05）

| 指标 | 值 |
|------|-----|
| 变异总数 | 86（7 个源文件） |
| 杀死 | 80 |
| 存活 | 6 |
| 超时 | 0 |
| 无测试 | 0 |
| 杀死率 | **93.02%**（阈值 80%，达标） |

存活变异明细（Top 存活模块，均为弱断言难以覆盖的边界分支，非门禁阻断项）：

- `app/di/fastapi_deps.py` → `x_get_service_container`（4 个存活）
- `app/contexts/flags.py` → `is_any_event_primary_enabled` / `is_event_primary_enabled`（2 个存活）

基线已记录至 `metrics/mutation-history.jsonl`（追加模式，每行一个 JSON 对象）。

配置与门禁见下方"CI 接入"。

## 前端（Stryker + Vitest）

```bash
cd FHD/frontend
npm i -D @stryker-mutator/core @stryker-mutator/vitest-runner
npx stryker run
```

配置见 [`frontend/stryker.conf.json`](../../frontend/stryker.conf.json)。首轮聚焦 `src/utils/**` 与 `src/composables/**` 纯函数。

## CI 接入

- 后端：PR gate `mutation-smoke.yml`（阈值 kill rate ≥ 80%，作用域 `app/di` + `app/contexts`）。
  - 触发：`pull_request`（仅 `app/di/**`、`app/contexts/**`、`tests/test_di/**`、`tests/test_contexts/**` 及门禁相关文件变更时）+ 每周一 03:00 UTC（schedule）+ `workflow_dispatch`。
  - 判定：`uv run mutmut run` → `python scripts/dev/mutation_kill_report.py --threshold 80`，低于 80% 退出码 1 阻断归并。
  - 2026-07-21 加回 `pull_request` gate（此前曾撤下）。
- 前端：`npx stryker run` 在 `test:coverage` 绿后 nightly 跑。