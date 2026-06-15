# Phase 4 变异测试（mutmut / Stryker）

> v10 线内迭代 · 2026-06-14 · 与 [`COVERAGE_RAMP.md`](COVERAGE_RAMP.md) Phase 4 对齐

## 后端（mutmut）

```bash
cd FHD
pip install mutmut
mutmut run          # 首轮：app/http · app/contexts · app/di
mutmut results      # 查看存活变异
mutmut show <id>    # 查看单个变异 diff
```

配置见 [`pyproject.toml`](../../pyproject.toml) `[tool.mutmut]`。目标杀死率 ≥80%（Phase 4 定版门禁）。

## 前端（Stryker + Vitest）

```bash
cd FHD/frontend
npm i -D @stryker-mutator/core @stryker-mutator/vitest-runner
npx stryker run
```

配置见 [`frontend/stryker.conf.json`](../../frontend/stryker.conf.json)。首轮聚焦 `src/utils/**` 与 `src/composables/**` 纯函数。

## CI 接入（待 Phase 4 定版）

- 后端：可选 job `mutmut run --CI`（超时预算单独列）
- 前端：`npx stryker run` 在 `test:coverage` 绿后 nightly 跑
