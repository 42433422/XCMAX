# 覆盖率分阶段提升与守护机制

本文档与 [`pyproject.toml`](../../pyproject.toml) `[tool.coverage.report].fail_under`、
[`metrics/coverage_ratchet_baseline.json`](../../metrics/coverage_ratchet_baseline.json) 与
[`frontend/vitest.config.js`](../../frontend/vitest.config.js) thresholds 对齐。

## 唯一可复现 SSOT（2026-06-14 重订）

历史上存在三份互相矛盾的"全量"基线（36.14 / 60.63 / 66.33），语句数 51,781→77,286 漂移，
根因是覆盖率随**可选重依赖**（torch/transformers/cv2/paddleocr/sklearn 等）是否安装而波动——
缺依赖时大量模块 import 失败被记 0%。CI 与开发 `.venv` 均**不装 ml extra**，故：

> **唯一对外口径 = 不含 ml extra 的全量 `source=[app]` 实测。** 富依赖环境数字（58/60.63/66.33）一律退役，禁止混报。

| 维度 | 后端基线 | 后端目标 | 前端基线 | 前端目标 |
|------|---------:|---------:|---------:|---------:|
| 行 | **40.48%**（本回合实测） | ≥90% | **21.52%** | ≥80% |
| 分支 | **23.09%**（本回合实测） | ≥85% | **49.07%** | ≥75% |
| 函数 | n/a（coverage.py 不原生统计） | — | **26.08%** | ≥80% |

详见 [`COVERAGE_GAP.md`](COVERAGE_GAP.md)（Top-N 未覆盖清单）。

## 铁律6：行/分支独立统计的工程取舍

`coverage.py` 开启 `branch=true` 后，`percent_covered` 变成"行+分支合并"指标（基线 32.28%），
不再等于纯行覆盖率。为保持 `fail_under` 仍是**行覆盖率** floor（与"35→90"一致）：

- `[tool.coverage.run] branch = true`：一次测量同时拿行+分支数据。
- 标准命令传 `--cov-fail-under=0`：关掉 coverage 自带的合并指标门禁。
- `scripts/dev/coverage_ratchet.py --check`：从 `coverage.json` 原始计数分别算
  行覆盖率（`covered_lines/num_statements`）与分支覆盖率（`covered_branches/num_branches`），
  各自对 floor 把关。行 floor 取自 `pyproject.toml fail_under`；分支 floor 与前端各项 floor 存
  `metrics/coverage_ratchet_baseline.json`（只升不降）。

## 覆盖率棘轮（只升不降）

与 `check_layer_ratchet.py` / `count_type_debt.py` / `count_raw_sql.py` 同级：

```bash
# CI 门禁：覆盖率回退即失败（ci-cd.yml backend-test 已接入）
python scripts/dev/coverage_ratchet.py --check --require-backend

# 本地补测后提升基线（只升；同步 vitest thresholds + 写 metrics/coverage-history.jsonl）
python scripts/dev/coverage_ratchet.py --bump

# 趋势
python scripts/dev/coverage_ratchet.py --history
```

与其它棘轮一致：**CI 只跑 `--check`**；`--bump`（提升 floor）是开发者本地动作，提交进版本库。

## 复测命令（可复现，铁律5）

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

| Phase | 后端行 | 前端行 | 重点区域 |
|-------|-------:|-------:|----------|
| 1（P0 核心） | ~55% | 起步 | routes/domains · *_app_service · middleware · db/models · http；stores · api · composables |
| 2（P1 业务） | ~72% | ~中 | facades · services · infrastructure · domain · ai_engines；views · components |
| 3（P2 完善） | ~85% | ~高 | neuro_bus · mod_sdk · desktop_runtime · contexts · di；router · utils |
| 4（P3 长尾） | ≥90% | ≥80% | 零覆盖逐文件 · pragma 审计 · 变异测试（杀死率≥80%） · 定版 |

每进入下一阶段：本地与 CI 跑全量复测，确认全绿 + `--check` 通过后再 `--bump`。

## Phase 4 剩余清单（p4-tail-mutation · 2026-06-14）

当前整体远未达 Phase 4 定版门禁（后端行 **40.48%** / 分支 **23.09%** vs 目标 90/85），本回合仅完成基础设施与长尾补测。**勿**提前将 `fail_under` 硬改为 90。棘轮已 bump：行 floor **39**、分支 floor **22**。

### pragma 审计（已完成扫描）

| 指标 | 值 |
|------|-----|
| `app/` 内 `pragma: no cover` 行数 | **7**（削减 2：health_k8s 诊断分支） |
| 相对语句数占比 | **~0.009%**（阈值 0.5%，无需批量削减） |
| 保留项（合理） | ImportError 回退（extensions/policy_nn/openapi_route_compat）、`__main__`（domain_registry）、平台可选（legacy_compat/tts_install）、审计容错（approval_workspace） |

### 变异测试基础设施（已落地）

| 工具 | 状态 | 入口 |
|------|------|------|
| **mutmut** | `[tool.mutmut]` 已配置 | `pip install mutmut && mutmut run` |
| **Stryker** | `frontend/stryker.conf.json` | `npm i -D @stryker-mutator/core @stryker-mutator/vitest-runner && npx stryker run` |
| 文档 | `docs/reports/MUTATION_TESTING.md` | — |

### 本回合补测（已完成）

- `tests/test_contexts/test_manifest_and_flags.py` — `manifest.py` + `flags.py`
- `tests/test_di/test_registry_and_deps.py` — `registry.py` + `fastapi_deps.py`
- `tests/routes/test_health_k8s_probe.py` — 诊断 `get_engine_status` 异常分支（去 pragma）

### 待补（按优先级）

**后端零覆盖小文件（<150 行纯函数）**

| 路径 | 行数 | 备注 |
|------|-----:|------|
| `app/http/__init__.py` | ~5 | re-export smoke |
| `app/contexts/__init__.py` | ~5 | re-export smoke |
| `app/di/__init__.py` | ~5 | re-export smoke |
| `app/contexts/context_notifier.py` | 16 | 已有单测；待 SSE 实现后扩展 |
| `app/mod_sdk/*.py` 零覆盖尾巴 | 若干 | Phase 3 遗留，按文件 <150 行逐个补 |
| `app/neuro_bus/*.py` 诊断/可选路径 | 大量 | Phase 3 主战场，mock NeuroBus |

**pragma 可进一步削减（非必须，占比已极低）**

- `approval_workspace_app_service.py:86` — mock `db.execute` 抛 `OperationalError` 即可覆盖审计容错
- `tts_install.py:165` / `legacy_compat.py:141` — 平台/ctypes 可选，保留合理

**变异测试 rollout**

1. mutmut 首轮绿 → 扩大 `paths_to_mutate` 至 `app/application/` 纯函数
2. Stryker 首轮绿 → 扩大至 `src/stores/`、`src/api/`
3. CI nightly 接入，杀死率 floor ≥80%

**定版前检查**

- [ ] 后端行 ≥90%、分支 ≥85%（`coverage_ratchet.py --check`）
- [ ] 前端 lines ≥80%（vitest thresholds）
- [ ] mutmut + Stryker 杀死率 ≥80%
- [ ] `fail_under` 升至 90（仅整体达标后）

## 历史（已退役口径，仅存档）

- 旧 M1~M4（fail_under 40→55→70→80，"full_app 60.63%"）：来自富依赖 + 窄 include 混报口径，
  与本 SSOT 不可比，已退役。见 `metrics/coverage-dual-summary.json`（标记 retired）。
