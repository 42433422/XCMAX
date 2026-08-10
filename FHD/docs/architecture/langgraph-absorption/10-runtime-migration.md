# LG-W0-10｜LangGraph 运行时迁移设计（Runtime Migration Design）

> 目录：`FHD/docs/architecture/langgraph-absorption/10-runtime-migration.md`（本系列文档之一；01–09 为其他 Wave 0 主题，不在本任务范围）。
> 目标结构 SSOT：`FHD/docs/architecture/target-structure.md`
> 前置契约冻结：`FHD/tests/langgraph_absorption/test_legacy_runtime_contract.py`（LG-W0-06）+ `FHD/tests/langgraph_absorption/fixtures/legacy_contract.json`
> 上游吸收证据：`FHD/XCAGI/kb/absorption/langgraph/absorption_tasks.json`（8 项待吸收能力）
> vendored 依赖来源：`FHD/packages/xcagi_langgraph_core/`、`.../xcagi_langgraph_checkpoint/`、`.../xcagi_langgraph_checkpoint_backends/`、`.../xcagi_langgraph_prebuilt/`（均含 `PROVENANCE.json` + `MANIFEST.sha256` + `verify_vendor.py` + `LICENSE`）；原始基线 `FHD/third_party/langgraph/`
> 本任务性质：**纯设计文档，不改产品代码、不做 `rm -rf`**。所有新增包路径标注 `(TO CREATE)`。

---

## 0. 目的（TL;DR）

产品目标：**把钉死的 LangGraph（pinned commit `41341457342327166d72fc11952ab28fb61ec0bf`，tag `v1.2.10`，MIT）吸收进自研 AIERP 运行时**。因此本次迁移的**核心交付物是一个 XCAGI 自有的、真正执行图的 LangGraph 运行时（infrastructure 层 `langgraph_runtime.py`）**，它直接 import 仓库内 vendored 的 `langgraph`（core / checkpoint / backends / prebuilt）包，并带**模块来源断言 + provenance/license 边界**。

- **图执行器 = XCAGI LangGraph 运行时**（不是 NeuroBus）。
- **NeuroBus 只是独立的事件总线桥**（`neuro_bus_bridge.py`），负责 `state.update` 等状态事件发布/订阅，**不执行图**。
- 现有手写 `WorkflowEngine`（`app/application/workflow/engine.py`）作为 **legacy 路径**，由灰度门控逐步替换，最终 `remove`。
- 依赖方向严格保留：`routes → application → domain`；`application → ports`；`infrastructure → ports + domain`；组合根注入 infrastructure。
- 通过 `legacy → shadow → canary → primary → remove` 五阶段门控上线，含回滚与 dual-write 风险管理。
- `app/neuro_bus/bus.py` **字节不变**；全部验收命令**fail-closed**（无 `sys.path.insert`/`PYTHONPATH` 捷径、无 `|| true`）。

---

## 1. 当前状态（证据）

| 组件 | 现状路径 | 迁移定位 |
|---|---|---|
| vendored LangGraph 核心 | `packages/xcagi_langgraph_core/langgraph/`（dist 名 `langgraph` v1.2.10） | **图执行器来源**（`StateGraph`/`START`/`END`/`StateSchema` 通道等） |
| vendored checkpoint | `packages/xcagi_langgraph_checkpoint/langgraph/` | checkpoint 协议（`langgraph.checkpoint.base` / serde / store） |
| vendored backends | `packages/xcagi_langgraph_checkpoint_backends/{checkpoint-sqlite,checkpoint-postgres}/langgraph/` | 持久化桥来源（`langgraph.checkpoint.sqlite.SqliteSaver` / `langgraph.checkpoint.postgres.PostgresSaver`） |
| vendored prebuilt | `packages/xcagi_langgraph_prebuilt/langgraph/` | `ToolNode` / `create_react_agent` 等预构建节点 |
| 原始吸收基线 | `third_party/langgraph/`（`PROVENANCE.json`/`MANIFEST.sha256`/`verify_vendor.py`/`refresh_vendor.py`） | 字节比对基线（W0-01） |
| 手写工作流引擎（legacy） | `app/application/workflow/engine.py`（`WorkflowEngine`） | legacy 路径，经适配器暴露为 `WorkflowRuntime`，待移除 |
| 类型化状态契约（现成，复用） | `app/application/workflow/types.py`（`StateSchema`/`Branch`/`PlanGraph`/`apply_state_schema`/`validate_plan_graph`） | 状态契约，保留 |
| 手写 checkpoint（legacy） | `app/application/workflow/checkpointer.py`（`DatabaseWorkflowCheckpointer`） | legacy 实现；被 vendored checkpoint 桥替代 |
| 规划 / agent 环 / 审批 / 风险门 | `app/application/workflow/{planner,agent_loop,approval_gated_engine,approval_card,risk_gate,plan_store}.py` | application 层编排，保留 |
| 消费方（现直接 new 引擎） | `app/application/ai_chat_app_service.py`（第 125、2202、2290 行直接 `WorkflowEngine(...)`/`DatabaseWorkflowCheckpointer()`） | 改组合根注入（T9） |
| NeuroBus（异步事件总线，核心不可改） | `app/neuro_bus/bus.py`（`NeuroBus`+`get_neuro_bus()`）、`bus_setup.py`、`events/base.py`（`NeuroEvent`）、`domains/`、`transports/`、`integrations/`、`sandbox.py` | **事件总线桥来源，非图执行器**；`bus.py` 字节不变 |
| 组合根 | `app/di/registry.py`（`ServiceContainer`）、`app/bootstrap.py`、`app/fastapi_app/lifespan.py`（`_init_neuro_ddd_async`） | 扩展注入运行时 |
| 特性开关先例 | `app/contexts/flags.py`（`XCAGI_EVENT_PRIMARY*`） | 沿用模式，新增 `lg_runtime_mode()` |
| 契约冻结 | `tests/langgraph_absorption/test_legacy_runtime_contract.py` + `fixtures/legacy_contract.json` | 迁移期红线；`remove` 阶段改新运行时为 SSOT |

> 结论：本次迁移**不是**重写引擎，而是**把真正执行图的运行时换成 XCAGI 自有的、基于 vendored `langgraph` 的执行器**（`langgraph_runtime.py`），NeuroBus 退位为事件桥，并保持 DDD 分层 + 开关化 + 灰度门控。

---

## 2. 依赖方向（严格保留）

```
routes → application → domain
application → ports
infrastructure → ports + domain
composition root（app/di/registry.py + app/bootstrap.py + lifespan）注入 infrastructure
```

- `application` 不得 import `app.infrastructure.*`、`app.neuro_bus.*`、vendored `langgraph.*`、`sqlalchemy`、`fastapi`——一律走 ports。
- `domain` 不得 import `routes`/`infrastructure`/`neuro_bus`/`langgraph`/`sqlalchemy`/`fastapi`/`openpyxl`。
- `routes` 不得 import `app.infrastructure`/`sqlalchemy`/`langgraph`/`app.neuro_bus`。
- **vendored `langgraph.*` 只允许被 infrastructure 的 LangGraph 运行时/持久化桥消费**（见 §7 门禁）。

---

## 3. NeuroBus 内部建模（事件总线桥，非图执行器）

NeuroBus 是**独立 infrastructure 事件总线域**，只做状态/业务事件的发布订阅，**不执行图**。内部不再按 DDD 四层展开，仅定义对外边界：

| NeuroBus 内部件（现状路径） | 角色 | 迁移动作 |
|---|---|---|
| `app/neuro_bus/bus.py`（`NeuroBus`/`get_neuro_bus`） | 事件总线核心 + 可靠性层（DEDUP/CIRCUIT/RATE_LIMIT/LIFELINE/TRACE/DLQ_AUTO/SLA_LOG/RETRY） | **字节不变**，仅被 `neuro_bus_bridge.py` 包裹 |
| `app/neuro_bus/bus_setup.py`（`NeuroBusManager`/lifespan） | 生命周期管理 | 保留，组合根负责启停 |
| `app/neuro_bus/events/base.py`（`NeuroEvent`） | 事件载荷契约 | 不直接暴露给 application；由桥转成「状态事件」DTO |
| `app/neuro_bus/domains/`、`transports/`、`integrations/` | 处理器 / Redis / FastAPI 端点 | 保留 |
| `app/neuro_bus/sandbox.py` | 沙箱（影子阶段只读执行） | 复用 |

对 application 只暴露最小事件 port：`EventBusPort` + `StateEventPublisher`（见 §6.2）。对 `app.neuro_bus.*` 的 import **只允许出现在 `app/infrastructure/workflow/neuro_bus_bridge.py`**（由 §7 门禁强制）。

---

## 4. XCAGI LangGraph 运行时（图执行器，本迁移核心）

新增 infrastructure 执行器（`TO CREATE`）：

- `app/infrastructure/workflow/langgraph_runtime.py`：实现 application port `WorkflowRuntime`，**真正执行图**。
- `app/infrastructure/workflow/langgraph_assert.py`：模块来源断言 + provenance/license 边界检查（import-time / boot 校验）。

### 4.1 消费的 vendored 模块（直接 import）

```python
# 仅 infrastructure 层可用（§7 门禁）
from langgraph.graph import StateGraph, START, END          # vendored core     (LG-W0-02)
from langgraph.prebuilt import ToolNode, create_react_agent # vendored prebuilt (LG-W0-05)
from langgraph.checkpoint.sqlite import SqliteSaver         # vendored checkpoint-sqlite (LG-W0-04b)
from langgraph.checkpoint.postgres import PostgresSaver     # vendored checkpoint-postgres (LG-W0-04b)
```

> `langgraph` dist 模块即 XCAGI vendored fork（`packages/xcagi_langgraph_core/pyproject.toml`：`name = "langgraph"`，version 1.2.10，`[tool.uv.sources]` 将 prebuilt/checkpoint/sqlite/postgres 重定向到兄弟 vendored 包）。

### 4.2 模块来源断言（module-source assertion）

`langgraph_assert.py` 在运行时启动/首用前校验：
1. 每个消费的 `langgraph` 子模块 `__file__` 必须解析到 `FHD/packages/` 下的 vendored 目录（**禁止**解析到 site-packages 的 PyPI 版本）。
2. 逐包校验 `PROVENANCE.json`：`upstream_commit_sha == 41341457342327166d72fc11952ab28fb61ec0bf`、`license == "MIT"`、`version == "1.2.10"`。
3. 逐包运行 `verify_vendor.py` + `MANIFEST.sha256` 完整性校验（字节级一致）。
4. 任一断言失败即抛异常、进程 fail-closed（不降级静默）。

### 4.3 provenance / license 边界

- 只允许 import vendored 模块；`langgraph-sdk` / `langgraph-cli` 无 vendored 版本，**禁止**引入运行时执行路径。
- 运行时随包保留 `LICENSE`（MIT）与 `PROVENANCE.json` 引用，不改变上游许可语义。
- 执行器自身不直接触碰 NeuroBus / DB / FastAPI——通过 ports 与持久化桥/事件桥协作。

### 4.4 与 legacy 的关系

`XCAGILangGraphRuntime` 与 `LegacyEngineAdapter`（包住 `WorkflowEngine`）实现**同一** `WorkflowRuntime` port，由组合根按 `XCAGI_LG_RUNTIME` 开关选择（§5）；shadow/canary 阶段两者并行差分（§8）。

---

## 5. bus.py 字节不变 vs 特性开关激活（冲突消解）

1. `bus.py` **不改**（所有可靠性层、事件分发原样保留）。
2. 新增开关 `XCAGI_LG_RUNTIME`，取值 `legacy | shadow | canary | primary`（默认 `legacy`），helper `lg_runtime_mode()` 放 `app/contexts/flags.py`。
3. 组合根选择运行时：`ServiceContainer`（`app/di/registry.py`）懒加载构建所选运行时（legacy→`LegacyEngineAdapter`，其余→`XCAGILangGraphRuntime`），经 `app/bootstrap.py` 的 `get_workflow_runtime()` 暴露。
4. 入口接线：`app/fastapi_app/lifespan.py` 的 `_init_neuro_ddd_async` 已启动 NeuroBus（事件桥）；在此追加「按开关构建/重载运行时 + 模块来源断言，挂到 `app.state`」。`ai_chat_app_service` 不再自行 `new`，从组合根取注入运行时（T9）。
5. **Import 边界门禁（静态，非 import 包装器）**：见 §7——用 AST 静态扫描**禁止**非法 import，让违规在 CI 失败，**不做**运行时动态代理去掩盖。

---

## 6. 包边界、port 契约、compat 适配器

### 6.1 新增包（`TO CREATE`）

| 包/文件 | 层 | 职责 |
|---|---|---|
| `app/application/workflow/ports/` | application | 只有 protocol，无实现 |
| `app/application/workflow/runtime/` | application | 选择器 + shadow/canary 编排 |
| `app/infrastructure/workflow/` | infrastructure | LangGraph 运行时 / 持久化桥 / NeuroBus 桥 / legacy 适配器 |
| `scripts/dev/import_boundary.py` + `config/import_boundary.yaml` | 工具 | 静态 import 边界门禁 |

### 6.2 Port 契约（`app/application/workflow/ports/`）

```python
# runtime.py
class WorkflowRuntime(Protocol):
    def run(self, plan, *, runtime_context=None, state_schema=None,
            checkpointer=None, state_event_callback=None, **kw): ...
    def resume_run(self, plan, checkpoint_id, *, checkpointer=None): ...
    def replay_run(self, plan_id, *, checkpointer=None): ...

# checkpoint.py
class CheckpointStore(Protocol):
    def save_checkpoint(self, plan_id, step_index, runtime_context, executed_nodes, *, blocked=None) -> str: ...
    def get_checkpoint(self, plan_id, checkpoint_id): ...
    def list_checkpoints(self, plan_id): ...
    def latest_checkpoint(self, plan_id): ...

# events.py
class EventBusPort(Protocol):            # 事件桥，屏蔽 NeuroBus 细节（非执行器）
    def publish(self, event) -> bool: ...
    def subscribe(self, event_type, handler): ...
class StateEventPublisher(Protocol):
    def emit_state_update(self, *, node_id, status, output_summary, plan_id): ...

# tools.py
class ToolDispatcher(Protocol):
    def dispatch(self, tool_name, *args, **kw): ...
```

### 6.3 状态 / 事件 / checkpoint 契约（现成，复用）

- **状态契约**：`StateSchema`（`app/application/workflow/types.py`）——typed keys + `merge ∈ {set, append, merge_dict}`；`apply_state_schema` 失败抛明确 `ValueError`（LG-W0-06 已冻结）。
- **事件契约**：`state.update` 负载 `{node_id, status, output_summary, plan_id}`（与 legacy `engine.py` 的 `_state_event_callback` 一致；契约冻结 `["state.update"]*n` 按节点顺序）。
- **checkpoint 契约**：`save/get/list/latest` 四方法；快照含 `runtime_context`/`executed_nodes`/`blocked`/`step_index`。legacy 由 `DatabaseWorkflowCheckpointer` 满足；新路径由 vendored `langgraph.checkpoint` 后端经 `checkpoint_bridge.py` 满足。

### 6.4 infrastructure 适配器（`app/infrastructure/workflow/`，均 `TO CREATE`）

| 适配器 | 包住/实现 | 暴露为 | 角色 |
|---|---|---|---|
| `legacy_engine_adapter.py` | `app/application/workflow/engine.py` 的 `WorkflowEngine`（契约冻结对象） | `WorkflowRuntime` | legacy 路径 |
| `langgraph_runtime.py` + `langgraph_assert.py` | vendored `langgraph`（core/prebuilt/checkpoint） | `WorkflowRuntime` | **图执行器（核心）** |
| `checkpoint_bridge.py` | vendored `SqliteSaver`/`PostgresSaver` | `CheckpointStore` | 持久化桥 |
| `neuro_bus_bridge.py` | `app.neuro_bus.bus` + `bus_setup` | `EventBusPort` / `StateEventPublisher` | 事件桥（非执行器） |

> 关键：`LegacyEngineAdapter` 保持 `WorkflowEngine` 原签名 → LG-W0-06 契约测试在迁移期持续绿；`XCAGILangGraphRuntime` 满足同一 `WorkflowRuntime` port，作为 primary 路径。

---

## 7. Import 边界门禁（静态扫描，非包装器）

新增（`TO CREATE`）：`scripts/dev/import_boundary.py`（AST 扫描，参考 `FHD/scripts/arch_fitness.py`、`FHD/scripts/dev/ssot_plugins/repository_ssot.py`）+ `config/import_boundary.yaml`。

禁止规则（按 target-structure.md 的 Forbidden Dependencies）：
```
domain/*            → 禁 import app.infrastructure, app.neuro_bus, app.routes, app.fastapi_*, langgraph, sqlalchemy, fastapi, openpyxl
application/* (非 ports) → 禁 import app.infrastructure, app.neuro_bus, langgraph      （必须走 ports）
application/ports/* → 禁 import app.infrastructure, app.neuro_bus, langgraph
routes/*            → 禁 import app.infrastructure, sqlalchemy, langgraph, app.neuro_bus
infrastructure/*    → 允许 import ports + domain + 外部库；禁 import routes
唯一豁免A（vendored 消费）：app/infrastructure/workflow/{langgraph_runtime,langgraph_assert,checkpoint_bridge}.py → 允许 import langgraph.*
唯一豁免B（事件桥）：app/infrastructure/workflow/neuro_bus_bridge.py → 允许 import app.neuro_bus.*
```
- 纯静态门禁（CI 阶段失败），**不做**运行时 import 包装/代理掩盖违规。
- 接入：独立 CI check 或并入 `scripts/arch_fitness.py` 调用链；命令 `python scripts/dev/import_boundary.py --check`。

---

## 8. 灰度门控：legacy → shadow → canary → primary → remove

`XCAGI_LG_RUNTIME` 取值对应门（每步可回滚，**禁 `rm -rf`**，旧实现移 `archive/` 或停用保留）：

| 门 | 行为 | 服务面 | 回滚 | 风险 |
|---|---|---|---|---|
| `legacy`（默认） | 走 `LegacyEngineAdapter`（`WorkflowEngine` 原样） | 100% | — | 无（现状） |
| `shadow` | `XCAGILangGraphRuntime` 并行执行，结果**不对外服务**，仅差分比对（复用 `app/neuro_bus/sandbox.py` 只读 dispatcher） | 0% | 关开关即回 legacy | **dual-write 副作用** |
| `canary` | 新运行时承载 X% 流量，其余 legacy | X% | 降 X 或归零 | 部分双写 |
| `primary` | 新运行时 100% | 100% | 翻回 legacy | 低 |
| `remove` | legacy 适配器停用/移 `archive/`，契约测试改为新运行时为 SSOT | 100% | 需回滚代码（进 archive 前保留 tag） | 低（不可热回滚） |

### dual-write 风险与缓解（shadow/canary 阶段必须处理）

1. **副作用双执行**：写/高风险节点在两个运行时都执行 → shadow 阶段 dispatcher **只读/沙箱**（`app/neuro_bus/sandbox.py` 或 no-op dispatcher），禁止真实写；canary 阶段写节点强制串行且只在被选运行时执行。
2. **checkpoint 命名空间冲突**：vendored checkpoint 与 legacy `DatabaseWorkflowCheckpointer` 写同一 `plan_id` → 新运行时用独立命名空间（`plan_id + ":lg"`）或独立后端实例；`CheckpointStore` 按 `run_id` 隔离。
3. **事件去重**：NeuroBus 已内置 DEDUP（`_rel_dedup`）→ 双发 `state.update` 依赖其幂等；shadow 阶段不发布对外流式事件，仅本地记录差分。
4. **状态发散**：shadow 比对 `final_context` 归一化（复用 LG-W0-06 `_normalize_context` 思路），不一致记差分日志但不阻断。
5. **遥测双计**：指标按 `runtime=mode` 维度打点，避免聚合被影子流量污染。

---

## 9. Wave-1 任务（10 项，独占文件域 + 依赖 + 验收命令）

> 每任务 `文件域` **互不重叠（独占）**；`(TO CREATE)` 由该任务创建，其余为既有文件在该任务内修改。`bus.py` 全部任务**只读**。**禁 `rm -rf`**。所有验收命令 **fail-closed**：无 `sys.path.insert`/`PYTHONPATH` 捷径、无 `|| true`；引用的每条路径要么已存在，要么标注 `(TO CREATE)`。

### T1 · Ports 契约
- **文件域**：`app/application/workflow/ports/{runtime,checkpoint,events,tools}.py` —— **全部 TO CREATE**；不触碰其他文件。
- **依赖**：LG-W0-06 契约冻结（只读参考，不改）。
- **验收**：
  ```bash
  cd FHD
  .venv/bin/python -m py_compile app/application/workflow/ports/runtime.py app/application/workflow/ports/checkpoint.py app/application/workflow/ports/events.py app/application/workflow/ports/tools.py
  ruff check app/application/workflow/ports/
  .venv/bin/python -m pytest tests/langgraph_absorption/test_legacy_runtime_contract.py -q
  ```

### T2 · Legacy 引擎适配器
- **文件域**：`app/infrastructure/workflow/legacy_engine_adapter.py`（**TO CREATE**）。
- **依赖**：T1。
- **验收**：
  ```bash
  cd FHD
  .venv/bin/python -c "from app.infrastructure.workflow.legacy_engine_adapter import LegacyEngineAdapter; print('OK')"
  .venv/bin/python -m pytest tests/langgraph_absorption/test_legacy_runtime_contract.py -q
  ruff check app/infrastructure/workflow/legacy_engine_adapter.py
  ```

### T3 · XCAGI LangGraph 运行时（图执行器）
- **文件域**：`app/infrastructure/workflow/langgraph_runtime.py`、`app/infrastructure/workflow/langgraph_assert.py`（**均 TO CREATE**）。
- **依赖**：T1。
- **验收**（模块来源断言 + provenance/license 边界，全部 fail-closed）：
  ```bash
  cd FHD
  .venv/bin/python -c "import langgraph, langgraph.checkpoint.sqlite, langgraph.prebuilt; p=langgraph.__file__; assert '/packages/xcagi_langgraph_core/' in p, p; print(p)"
  .venv/bin/python -c "from app.infrastructure.workflow.langgraph_assert import assert_vendored_provenance; assert_vendored_provenance(); print('OK')"
  .venv/bin/python -c "from app.infrastructure.workflow.langgraph_runtime import XCAGILangGraphRuntime; r=XCAGILangGraphRuntime(); print('OK')"
  ruff check app/infrastructure/workflow/langgraph_runtime.py app/infrastructure/workflow/langgraph_assert.py
  ```

### T4 · Checkpoint 持久化桥
- **文件域**：`app/infrastructure/workflow/checkpoint_bridge.py`（**TO CREATE**）。
- **依赖**：T1。
- **验收**：
  ```bash
  cd FHD
  .venv/bin/python -c "from app.infrastructure.workflow.checkpoint_bridge import LanggraphCheckpointBridge; print('OK')"
  .venv/bin/python -c "from langgraph.checkpoint.sqlite import SqliteSaver; from langgraph.checkpoint.postgres import PostgresSaver; print('OK')"
  ruff check app/infrastructure/workflow/checkpoint_bridge.py
  ```

### T5 · NeuroBus 事件桥（bus.py 字节不变）
- **文件域**：`app/infrastructure/workflow/neuro_bus_bridge.py`（**TO CREATE**）。`app/neuro_bus/bus.py` **只读校验**。
- **依赖**：T1。
- **验收**：
  ```bash
  cd FHD
  git diff --exit-code -- app/neuro_bus/bus.py
  .venv/bin/python -c "from app.infrastructure.workflow.neuro_bus_bridge import NeuroBusEventBridge; print('OK')"
  ruff check app/infrastructure/workflow/neuro_bus_bridge.py
  ```

### T6 · 特性开关 + 运行时选择器
- **文件域**：`app/contexts/flags.py`（**修改**：新增 `lg_runtime_mode()` 读 `XCAGI_LG_RUNTIME`）、`app/application/workflow/runtime/selector.py`（**TO CREATE**）。
- **依赖**：T2、T3、T4、T5。
- **验收**：
  ```bash
  cd FHD
  XCAGI_LG_RUNTIME=legacy .venv/bin/python -c "from app.application.workflow.runtime.selector import resolve_runtime; r=resolve_runtime(); assert r.__class__.__name__=='LegacyEngineAdapter'; print(r.__class__.__name__)"
  XCAGI_LG_RUNTIME=primary .venv/bin/python -c "from app.application.workflow.runtime.selector import resolve_runtime; r=resolve_runtime(); assert r.__class__.__name__=='XCAGILangGraphRuntime'; print(r.__class__.__name__)"
  .venv/bin/python -m pytest tests/langgraph_absorption/test_legacy_runtime_contract.py -q
  ```

### T7 · Shadow + Canary 差分编排
- **文件域**：`app/application/workflow/runtime/shadow_canary.py`（**TO CREATE**，含只读 dispatcher + 归一化差分 + canary 比例采样，复用 LG-W0-06 `_normalize_context` 思路）。
- **依赖**：T3、T4、T5、T6。
- **验收**：
  ```bash
  cd FHD
  XCAGI_LG_RUNTIME=shadow .venv/bin/python -m pytest tests/langgraph_absorption/test_legacy_runtime_contract.py -q
  XCAGI_LG_RUNTIME=canary .venv/bin/python -c "from app.application.workflow.runtime.shadow_canary import route_mode; m=route_mode(rate=0.2); print(m)"
  ruff check app/application/workflow/runtime/shadow_canary.py
  ```

### T8 · 静态 Import 边界门禁
- **文件域**：`scripts/dev/import_boundary.py`（**TO CREATE**）、`config/import_boundary.yaml`（**TO CREATE**）。
- **依赖**：无（可与 T1–T5 并行）。
- **验收**：
  ```bash
  cd FHD
  python scripts/dev/import_boundary.py --check
  python scripts/dev/import_boundary.py --selfcheck
  ```

### T9 · 组合根装配 + 消费方接线
- **文件域**：`app/di/registry.py`（**修改**：`ServiceContainer` 懒加载所选运行时）、`app/bootstrap.py`（**修改**：新增 `get_workflow_runtime()`）、`app/fastapi_app/lifespan.py`（**修改**：启动期构建/重载运行时 + 模块来源断言，挂 `app.state`）、`app/application/ai_chat_app_service.py`（**修改**：去第 125/2202/2290 行直接 `WorkflowEngine(...)`/`DatabaseWorkflowCheckpointer()`，改组合根注入）。
- **依赖**：T6。
- **验收**：
  ```bash
  cd FHD
  .venv/bin/python -c "from app.bootstrap import get_workflow_runtime; assert get_workflow_runtime() is not None; print('OK')"
  ruff check app/di/registry.py app/bootstrap.py app/fastapi_app/lifespan.py app/application/ai_chat_app_service.py
  .venv/bin/python -m pytest tests/test_application/test_ai_chat_app_service.py tests/test_application/test_ai_chat_app_service_ext.py -q
  .venv/bin/python -m pytest tests/langgraph_absorption/test_legacy_runtime_contract.py -q
  python scripts/dev/import_boundary.py --check
  ```

### T10 · Acceptance + Removal（SSOT 契约迁移 + 收口）
- **文件域**：`tests/langgraph_absorption/test_legacy_runtime_contract.py`（**修改**：断言目标改为 `XCAGILangGraphRuntime`）、`tests/langgraph_absorption/fixtures/legacy_contract.json`（**修改**：按该文件 `regenerate_fixture()` 字节恒等重生成）、`docs/architecture/langgraph-absorption/10-runtime-migration.md`（**修改**：状态勾选）。旧 legacy 适配器**移 `archive/` 或停用保留（禁 `rm -rf`）**。
- **依赖**：T2–T9 全部通过，且 canary/primary 观察期满足（§8 门控）。
- **验收**：
  ```bash
  cd FHD
  .venv/bin/python -m pytest tests/langgraph_absorption/test_legacy_runtime_contract.py -q
  .venv/bin/python tests/langgraph_absorption/test_legacy_runtime_contract.py -q
  git diff --exit-code -- app/neuro_bus/bus.py
  python scripts/dev/import_boundary.py --check
  ```

### 依赖图（Wave-1）

```
T8 ────────────────┐
T1 ──┬── T2 ──┬── T6 ──┬── T7 ── T9 ── T10
     ├── T3 ──┤        └── T9
     ├── T4 ──┤
     └── T5 ──┘
```
T8 可并行；主链 `T1 → (T2,T3,T4,T5) → T6 → (T7,T9) → T10`。

---

## 10. 范围与约束

- **只允许修改本文件**（本任务产物）。其余 `(TO CREATE)` 路径由对应 Wave-1 任务创建，本任务不创建。
- **不改产品代码、不做 `rm -rf`**（旧实现移 `archive/` 或停用保留）。
- `app/neuro_bus/bus.py` 全部任务**只读**，验收含 `git diff --exit-code`。
- 契约冻结（LG-W0-06）为迁移期红线；`remove` 阶段以新运行时 `XCAGILangGraphRuntime` 为新 SSOT。
- 图执行器为 XCAGI LangGraph 运行时（vendored `langgraph`）；NeuroBus 仅为事件桥，非执行器。
- 灰度门控 `legacy→shadow→canary→primary→remove` 按序推进，shadow/canary 落实 §8 dual-write 缓解。
- 所有验收命令 **fail-closed**；路径要么已存在要么标 `(TO CREATE)`。
