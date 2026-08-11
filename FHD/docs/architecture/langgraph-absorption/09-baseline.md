# LG-W0-09 — LangGraph 吸收基线基准

> spec: `LG-W0-09` · 结果与回归门禁均来自**本次基准运行**（可复现）。

## 测量对象

- **legacy WorkflowEngine**：`app/application/workflow/engine.py`（FHD 当前产品实现）
- **vendored LangGraph**：`packages/xcagi_langgraph_core (vendored, pinned 1.2.10)`（仓库 vendored、锁定版本）

## 场景与方法学

| 场景 | 含义 |
|------|------|
| `compile_100` / `compile_1000` | 图构造 + 校验/编译（100 / 1000 节点） |
| `execute_100` / `execute_1000` | 顺序执行 100 / 1000 节点 |
| `fanout_64` | 64 个独立并行节点（fan-out） |
| `checkpoint_200` | 200 节点 + 逐步 checkpoint |

- seed=`20260810`（确定性构造）· warmup=`5` · measured repeats=`7`
- 每个场景输出 `min` / `median` / `p95` / `max`（单位 ms）

## 机器条件（本次运行）

| 项 | 值 |
|----|----|
| Python | 3.11.15 (CPython) |
| OS | Darwin 25.3.0 |
| Machine | arm64 |
| Processor | arm |

## 实测结果（本次运行，ms）

| 引擎 | 场景 | min | median | p95 | max |
|------|------|-----|--------|-----|-----|
| legacy_workflow_engine | `compile_100` | 0.057 | 0.058 | 0.081 | 1.448 |
| legacy_workflow_engine | `execute_100` | 11.207 | 12.61 | 15.075 | 16.066 |
| legacy_workflow_engine | `compile_1000` | 0.241 | 0.637 | 1.975 | 2.677 |
| legacy_workflow_engine | `execute_1000` | 159.644 | 198.099 | 203.2 | 221.351 |
| legacy_workflow_engine | `fanout_64` | 0.764 | 0.779 | 0.831 | 0.873 |
| legacy_workflow_engine | `checkpoint_200` | 162.579 | 166.275 | 179.262 | 194.934 |
| vendor_langgraph | `compile_100` | 3.219 | 3.588 | 4.254 | 4.474 |
| vendor_langgraph | `execute_100` | 10.332 | 10.563 | 11.241 | 13.889 |
| vendor_langgraph | `compile_1000` | 31.821 | 33.827 | 59.82 | 71.508 |
| vendor_langgraph | `execute_1000` | 300.639 | 339.822 | 465.728 | 512.384 |
| vendor_langgraph | `fanout_64` | 6.475 | 6.789 | 7.278 | 7.343 |
| vendor_langgraph | `checkpoint_200` | 44.603 | 48.616 | 75.98 | 86.093 |

## 回归门禁（本次实测，p95 上限）

| 引擎 | 门禁 | 上限(ms) | 实测(ms) | 通过 |
|------|------|----------|----------|------|
| legacy_workflow_engine | compile_100_p95_ms | 500 | 0.081 | ✅ |
| legacy_workflow_engine | execute_100_p95_ms | 1000 | 15.075 | ✅ |
| legacy_workflow_engine | compile_1000_p95_ms | 1000 | 1.975 | ✅ |
| legacy_workflow_engine | execute_1000_p95_ms | 3000 | 203.2 | ✅ |
| legacy_workflow_engine | fanout_64_p95_ms | 500 | 0.831 | ✅ |
| legacy_workflow_engine | checkpoint_200_p95_ms | 3000 | 179.262 | ✅ |
| vendor_langgraph | compile_100_p95_ms | 500 | 4.254 | ✅ |
| vendor_langgraph | execute_100_p95_ms | 2000 | 11.241 | ✅ |
| vendor_langgraph | compile_1000_p95_ms | 3000 | 59.82 | ✅ |
| vendor_langgraph | execute_1000_p95_ms | 5000 | 465.728 | ✅ |
| vendor_langgraph | fanout_64_p95_ms | 3000 | 7.278 | ✅ |
| vendor_langgraph | checkpoint_200_p95_ms | 5000 | 75.98 | ✅ |

## legacy 契约门禁（W0-06 fixture）

- fixture：`tests/langgraph_absorption/fixtures/legacy_contract.json`
- 期望 executed_nodes：`['n1', 'n2', 'n3']` · 实测：`['n1', 'n2', 'n3']` · success=`True`
- **契约匹配：✅**

## 总体门禁：**PASS**

## 精确重跑命令

```bash
cd FHD
XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 .venv/bin/python -m scripts.benchmarks.langgraph_absorption_baseline
XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 .venv/bin/python -m scripts.benchmarks.langgraph_absorption_baseline --write-doc
```

## LangGraph 来源合规（本次运行）

| 检查项 | 结果 |
|--------|------|
| langgraph.core 来自仓库 XCAGI vendored 来源 | ✅ |
| langgraph.checkpoint 来自仓库 XCAGI vendored 来源 | ✅ |

## LangGraph 来源合规说明

- LangGraph 由 vendored 包自身锁定 uv 环境（`uv run --project packages/xcagi_langgraph_core`，uv.lock + [tool.uv.sources] → 兄弟 vendored 包）子进程导入。
- 不使用根 site-packages、不使用 /tmp 源码、不做 PYTHONPATH / sys.path 注入；core 包 .venv 被外部清理时按锁定来源按需重建，不改兄弟包。
- 输出 JSON 不含绝对路径、不含易变时间戳；来源自检仅以布尔进 JSON，绝对路径仅打到 stderr。
