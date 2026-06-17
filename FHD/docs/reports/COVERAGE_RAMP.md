# 覆盖率分阶段提升与守护机制

本文档与 [`pyproject.toml`](../../pyproject.toml) `[tool.coverage.report].fail_under`、
[`metrics/coverage_ratchet_baseline.json`](../../metrics/coverage_ratchet_baseline.json) 与
[`frontend/vitest.config.js`](../../frontend/vitest.config.js) thresholds 对齐。

**最后更新**：2026-06-17

## 唯一可复现 SSOT（2026-06-17）

> **唯一对外口径 = 不含 ml extra 的全量 `source=[app]`（后端）/ `src/**`（前端）实测。**
> 权威数字见 [`metrics/coverage-dual-summary.json`](../../metrics/coverage-dual-summary.json)；
> 趋势见 [`metrics/coverage-history.jsonl`](../../metrics/coverage-history.jsonl)。
> 富依赖环境数字（58 / 60.63 / 66.33 / 77.4%）与窄包 70% 门禁**一律退役**，禁止混报。

### HEAD 已提交（最后全绿 bump · 2026-06-14 · `1569dfa4`）

| 维度 | 后端实测 | 后端目标 | 前端实测 | 前端目标 |
|------|---------:|---------:|---------:|---------:|
| 行 | **52.74%**（39,747 / 75,357） | ≥90% | **55.82%** | ≥80% |
| 分支 | **37.17%** | ≥85% | **62.80%** | ≥75% |
| 函数 | n/a | — | **51.15%** | ≥80% |
| pytest | **3,785 passed** / 0 failed / 51 skipped | 全绿 | — | — |
| vitest | — | — | **1,143 passed** / 0 failed | 全绿 |

### 工作区 WIP（2026-06-17 · `feat/enterprise-deploy-maturity` · 未提交）

| 维度 | 后端实测 | 前端实测 | 状态 |
|------|---------:|---------:|------|
| 行 | **74.56%**（56,846 / 76,237） | **74.15%** | 覆盖率已拉升 |
| 分支 | **61.80%** | **69.54%** | 同上 |
| 函数 | n/a | **65.06%** | 同上 |
| pytest | **12,675 passed** / **196 failed** / **7 errors** | — | **不可 bump 棘轮** |

WIP 数字仅供内部跟踪；对外材料、棘轮 `--bump`、发版门禁仍以 **HEAD 全绿** 为准，待红灯清零后再 bump。

### 棘轮 floor（当前 CI 守护）

| 项 | floor | 来源 |
|----|------:|------|
| 后端行 | **51%** | `pyproject.toml` `fail_under` |
| 后端分支 | **36%** | `coverage_ratchet_baseline.json` |
| 前端 lines / statements | **54%** | `vitest.config.js` + ratchet |
| 前端 branches | **62%** | 同上 |
| 前端 functions | **50%** | 同上 |

详见 [`COVERAGE_GAP.md`](COVERAGE_GAP.md)（Top-N 未覆盖清单）。

## 铁律6：行/分支独立统计的工程取舍

`coverage.py` 开启 `branch=true` 后，`percent_covered` 变成"行+分支合并"指标，
不再等于纯行覆盖率。为保持 `fail_under` 仍是**行覆盖率** floor：

- `[tool.coverage.run] branch = true`：一次测量同时拿行+分支数据。
- 标准命令传 `--cov-fail-under=0`：关掉 coverage 自带的合并指标门禁。
- `scripts/dev/coverage_ratchet.py --check`：从 `coverage.json` 原始计数分别算
  行覆盖率与分支覆盖率，各自对 floor 把关。

## 覆盖率棘轮（只升不降）

```bash
# CI 门禁（ci-cd.yml backend-test 已接入）
python scripts/dev/coverage_ratchet.py --check --require-backend

# 本地补测后提升基线（须 pytest 全绿后再执行）
python scripts/dev/coverage_ratchet.py --bump

# 趋势
python scripts/dev/coverage_ratchet.py --history
```

## 复测命令（可复现）

```bash
# 后端（.venv = CI 等价依赖）
cd FHD
XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 .venv/bin/python -m pytest tests/ \
  --cov --cov-branch --cov-fail-under=0 \
  --cov-report=json:coverage.json --cov-report=term-missing -q

# 前端（全量 src/**）
cd FHD/frontend && CI=true npm run test:coverage
```

## 分阶段目标（前后端并行）

| Phase | 后端行 | 前端行 | 重点区域 | 状态（2026-06-17） |
|-------|-------:|-------:|----------|-------------------|
| 1（P0 核心） | ~55% | 起步 | routes/domains · *_app_service · middleware | **HEAD 已达标** |
| 2（P1 业务） | ~72% | ~中 | facades · services · infrastructure | **WIP 行覆盖已达标；红灯待清** |
| 3（P2 完善） | ~85% | ~高 | neuro_bus · mod_sdk · desktop_runtime | 进行中 |
| 4（P3 长尾） | ≥90% | ≥80% | 零覆盖逐文件 · 变异测试 | 未达 |

每进入下一阶段：本地与 CI 跑全量复测，确认**全绿** + `--check` 通过后再 `--bump`。

## Phase 4 剩余清单（2026-06-17 更新）

HEAD 基线后端行 **52.74%**、分支 **37.17%**；WIP 后端行 **74.56%**、分支 **61.8%**。
距定版门禁（90/85）仍差约 **15–16pp**（行）/ **23pp**（分支，按 HEAD 计）。

**WIP 待修红灯（优先）**

- `purchase_service` — 源码改动，测试未对齐
- `wechat_contact_cache_import` / `wechat_task_service`
- `tools_workflow_registered`
- `test_im_sync.py` / `test_im_v0.py` — SQLAlchemy 7 errors

**定版前检查**

- [ ] pytest 全绿（当前 WIP：**196 failed + 7 errors**）
- [ ] 后端行 ≥90%、分支 ≥85%（`coverage_ratchet.py --check`）
- [ ] 前端 lines ≥80%（vitest thresholds）
- [ ] mutmut + Stryker 杀死率 ≥80%
- [ ] `fail_under` 升至 90（仅整体达标后）

## 历史（已退役口径，仅存档）

- 旧 M1~M4（fail_under 40→55→**70**→80，"full_app **60.63%**"）：窄 include + 富依赖混报，已退役。
- 周报误报 **77.4% → ≥88%**（2026-06-08 撤回）。
- Phase 4 起点诚实基线 **36.35%** 行（2026-06-13）— 仅作 ramp 起点记录，非当前值。
