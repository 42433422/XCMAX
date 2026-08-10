# LG-W0-10｜LangGraph 运行时迁移设计（Runtime Migration Design）

> 目录：`FHD/docs/architecture/langgraph-absorption/10-runtime-migration.md`（本系列文档之一；01–09 为其他 Wave 0 主题，不在本任务范围）。
> 目标结构 SSOT：`FHD/docs/architecture/target-structure.md`
> 前置契约冻结：`FHD/tests/langgraph_absorption/test_legacy_runtime_contract.py`（LG-W0-06）+ `FHD/tests/langgraph_absorption/fixtures/legacy_contract.json`
> 上游吸收证据：`FHD/XCAGI/kb/absorption/langgraph/absorption_tasks.json`（8 项待吸收能力）
> vendored 依赖来源：`FHD/packages/xcagi_langgraph_core/`、`.../checkpoint/`、`.../checkpoint_backends/`、`.../prebuilt/`（均含 `PROVENANCE.json`+`MANIFEST.sha256`+`verify_vendor.py`+`LICENSE`）；原始基线 `FHD/third_party/langgraph/`
> 本任务性质：**纯设计文档，不改产品/包/测试文件、不做 `git add/commit/push/reset`、不做 `rm -rf`**。`(TO CREATE)` 标注反映**原始设计时**尚未创建的路径；**当前实现覆盖层**见下方「§0 执行状态」与 §9 各任务个别的实测核对，以日期区分「设计意图」与「实现事实」。

**版本事实（review 钉死）**
- 上游精确 tag 为 **`1.2.10`**（**绝不写成 `v1.2.10`**）。
- 上游锁定 commit：`41341457342327166d72fc11952ab28fb61ec0bf`（核心 `libs/langgraph`）。
- **core 与 prebuilt 目前仍依赖 registry 的 `langgraph-sdk`**，而同一 commit 的仓库内含 `libs/sdk-py`。→ **必须先完成 W0-11（SDK 包）与 W0-12（接线 core/prebuilt → 本地 SDK）**（见 §2），否则运行时无法做到「无 PyPI LangGraph 发行版」。

---

## §0 执行状态（2026-08-10 · LG-W1-T10-C SSOT 事实更新）

> 本文件 §1–§10 为**原始设计**：凡标注 `TO CREATE` 即表示设计时尚未创建。**本节为当前实现覆盖层的事实快照**，经只读核实后更新；「设计意图」与「实现事实」以日期（2026-08-10）与语义区分。

**Wave-1 T1–T10 本地已验收（locally ACCEPTED），最高 claim = `primary-ready`。**
- legacy 引擎（`WorkflowEngine`/legacy 路径）**仍可用，为回滚路径**（`legacy` 仍为默认门，§8）。
- **生产 shadow/canary 观测、业务回归验收、桌面端验收、发布制品（release artifact）、legacy 移除**均**未完成 / 未 claim**。
- **明确不 claim：production-ready、release-ready、legacy removed。** `remove` 为 §8 生产观察期后续门，不在本任务内。

| 维度 | 状态（2026-08-10） |
|---|---|
| Wave-1 T1–T10 | 本地 ACCEPTED（本地验收，非生产） |
| 最高声明 | `primary-ready` |
| legacy 引擎（回滚路径） | 可用，默认门，保留 |
| 生产 shadow/canary 观测 | 未完成 / 未 claim |
| 业务回归验收 | 未完成 / 未 claim |
| 桌面端验收 | 未完成 / 未 claim |
| 发布制品（release artifact） | 未完成 / 未 claim |
| legacy 移除 | 未完成 / **未 claim** |

---

## 1. 目的（TL;DR）

产品目标：**把钉死的 LangGraph（tag `1.2.10`，commit `41341457…`，MIT）吸收进自研 AIERP 运行时**，并做到**仓库内无任何 PyPI LangGraph 发行版参与运行时**。

- **图执行器 = XCAGI LangGraph 运行时**（infrastructure `langgraph_runtime.py`，真正执行图）。
- **NeuroBus = 独立事件桥**（`neuro_bus_bridge.py`），只做 `state.update` 等事件发布/订阅，**不执行图**。
- 现有手写 `WorkflowEngine` 作为 **legacy 路径**，经 `LegacyEngineAdapter` 暴露为 `WorkflowRuntime`，由灰度门控替换；**legacy 移除是生产观察期后的后续门，不属于 Wave-1 交付**（见 §8、T10）。
- 依赖方向严格保留：`routes → application → domain`；`application → ports`；`infrastructure → ports + domain`；组合根注入 infrastructure。**application 不得选择/import infrastructure**（选择器在 infrastructure，见 §5）。
- 门控 `legacy → shadow → canary → primary`（Wave-1 内）；`remove` 为生产观察期后续门（§8）。
- `app/neuro_bus/bus.py` **字节不变**；全部验收命令 **fail-closed**（无 `sys.path.insert`/`PYTHONPATH` 捷径、无 `|| true`）。

---

## 2. 前置：W0-11（SDK 包）与 W0-12（接线）必须都通过（Wave-1 前完成）

**背景**：`FHD/packages/xcagi_langgraph_core/pyproject.toml` 的 `dependencies` 含 `langgraph-sdk>=0.4.2,<0.5.0`（registry），且 `[tool.uv.sources]` **未**把 `langgraph-sdk` 重定向到本地。prebuilt 同理。上游同一 commit `41341457…` 的 `libs/sdk-py` 即该 SDK 源码。

> **发行版名 `langgraph-sdk`（连字符）；但 import 包与源码目录为 `langgraph_sdk`**（即 `import langgraph_sdk.client`），**绝非** `langgraph.sdk` / `langgraph/sdk`。

**W0-11（mandatory 前置，EXISTING AND ACCEPTED——SDK 包）**
- 已自上游 commit `41341457…` 的 `libs/sdk-py` 吸收，存在于 `FHD/packages/xcagi_langgraph_sdk/`（含 `langgraph_sdk/`、`PROVENANCE.json`、`MANIFEST.sha256`、`verify_vendor.py`、`LICENSE`）。
- **状态：ACCEPTED**——`FHD/packages/xcagi_langgraph_sdk/tests/test_import_probe.py` 已通过，`verify_vendor.py` 在线字节校验已通过；`import langgraph_sdk.client` 的 `__file__` 位于 `packages/` 下。

**W0-12（mandatory 前置，EXISTING AND ACCEPTED——接线 core/prebuilt → 本地 SDK）**
- 已完成：`FHD/packages/xcagi_langgraph_core/pyproject.toml` 与 `FHD/packages/xcagi_langgraph_prebuilt/pyproject.toml` 的 `[tool.uv.sources]` 已把 `langgraph-sdk` 指向本地 SDK 包，两包锁文件已使 `langgraph-sdk` 解析自本地源。
- **状态：ACCEPTED**——`uv lock --check` 通过；core/prebuilt 的 `langgraph-sdk` 解析到本地 SDK 包；`langgraph_sdk.client.__file__` 位于 `packages/` 下。

**两者均已 EXISTING AND ACCEPTED，Wave-1（§7 依赖接线 T1）以其为基。** `langgraph-cli` 明确非运行时、显式延期（`langgraph dev`/`langgraph build` 仅开发/运维工具，不参与运行时依赖，Wave-1 不吸收、不引入执行路径）。

---

## 3. 当前状态（证据）

| 组件 | 现状路径 | 迁移定位 |
|---|---|---|
| vendored LangGraph 核心 | `packages/xcagi_langgraph_core/langgraph/`（dist 名 `langgraph`，tag `1.2.10`） | **图执行器来源**（`langgraph.graph.state`/`START`/`END`/通道） |
| vendored checkpoint | `packages/xcagi_langgraph_checkpoint/langgraph/` | checkpoint 协议（`langgraph.checkpoint.base` / serde / store） |
| vendored backends | `packages/xcagi_langgraph_checkpoint_backends/{checkpoint-sqlite,checkpoint-postgres}/langgraph/` | 持久化桥来源（`langgraph.checkpoint.sqlite.SqliteSaver` / `langgraph.checkpoint.postgres.PostgresSaver`） |
| vendored prebuilt | `packages/xcagi_langgraph_prebuilt/langgraph/` | `langgraph.prebuilt.tool_node.ToolNode` / `create_react_agent` 等 |
| **vendored sdk（W0-11，EXISTING AND ACCEPTED）** | `FHD/packages/xcagi_langgraph_sdk/`（已吸收上游 `libs/sdk-py`，源码目录 `langgraph_sdk/`；测试+在线字节校验已过） | `langgraph_sdk.client`；让 core/prebuilt 摆脱 registry `langgraph-sdk` |
| 原始吸收基线 | `third_party/langgraph/`（`PROVENANCE.json`/`MANIFEST.sha256`/`verify_vendor.py`/`refresh_vendor.py`） | 字节比对基线（W0-01）；网络 tag 校验归 build/CI |
| 手写工作流引擎（legacy） | `app/application/workflow/engine.py`（`WorkflowEngine`） | legacy 路径，经适配器暴露为 `WorkflowRuntime`，待后续移除 |
| 类型化状态契约（现成，复用） | `app/application/workflow/types.py`（`StateSchema`/`Branch`/`PlanGraph`/`apply_state_schema`/`validate_plan_graph`） | 状态契约，保留 |
| 手写 checkpoint（legacy） | `app/application/workflow/checkpointer.py`（`DatabaseWorkflowCheckpointer`） | legacy 实现；被 vendored checkpoint 桥替代 |
| 规划 / agent 环 / 审批 / 风险门 | `app/application/workflow/{planner,agent_loop,approval_gated_engine,approval_card,risk_gate,plan_store}.py` | application 层编排，保留 |
| 消费方（现直接 new 引擎） | `app/application/ai_chat_app_service.py`（第 125、2202、2290 行直接 `WorkflowEngine(...)`/`DatabaseWorkflowCheckpointer()`） | 改组合根注入（T9） |
| NeuroBus（异步事件总线，核心不可改） | `app/neuro_bus/bus.py`（`NeuroBus`+`get_neuro_bus()`）、`bus_setup.py`、`events/base.py`（`NeuroEvent`）、`domains/`、`transports/`、`integrations/`、`sandbox.py` | **事件桥来源，非图执行器**；`bus.py` 字节不变 |
| 组合根 | `app/di/registry.py`（`ServiceContainer`）、`app/bootstrap.py`、`app/fastapi_app/lifespan.py`（`_init_neuro_ddd_async`） | 扩展注入运行时 |
| 特性开关先例 | `app/contexts/flags.py`（`XCAGI_EVENT_PRIMARY*`） | 沿用模式，新增 `lg_runtime_mode()` |
| 契约冻结 | `tests/langgraph_absorption/test_legacy_runtime_contract.py` + `fixtures/legacy_contract.json` | 迁移期红线；`primary-ready` 阶段以新运行时为 SSOT（legacy 移除另列后续门） |

> 结论：本次迁移**不是**重写引擎，而是把真正执行图的运行时换成 XCAGI 自有、基于 vendored `langgraph`（含 sdk）的执行器；NeuroBus 退位为事件桥；保持 DDD 分层 + 开关化 + 灰度门控。

---

## 4. 依赖方向（严格保留）

```
routes → application → domain
application → ports
infrastructure → ports + domain
composition root（app/di/registry.py + app/bootstrap.py + lifespan）注入 infrastructure
```

- `application` 不得 import `app.infrastructure.*`、`app.neuro_bus.*`、vendored `langgraph.*`、`sqlalchemy`、`fastapi`——一律走 ports。
- `application` **不得选择/import infrastructure**（运行时选择器放 infrastructure，见 §5）；`application/runtime/shadow_canary.py` 只依赖**注入的 ports**。
- `domain` 不得 import `routes`/`infrastructure`/`neuro_bus`/`langgraph`/`sqlalchemy`/`fastapi`/`openpyxl`。
- `routes` 不得 import `app.infrastructure`/`sqlalchemy`/`langgraph`/`app.neuro_bus`。
- **vendored `langgraph.*` 只允许被 infrastructure 的 LangGraph 运行时/持久化桥消费**（§7 门禁豁免A）。

---

## 5. NeuroBus 与运行时选择（建模分离）

### 5.1 NeuroBus = 事件总线桥（非图执行器）

NeuroBus 是**独立 infrastructure 事件总线域**，只做状态/业务事件发布订阅，**不执行图**。

| NeuroBus 内部件（现状路径） | 角色 | 迁移动作 |
|---|---|---|
| `app/neuro_bus/bus.py`（`NeuroBus`/`get_neuro_bus`） | 事件总线核心 + 可靠性层（DEDUP/CIRCUIT/RATE_LIMIT/LIFELINE/TRACE/DLQ_AUTO/SLA_LOG/RETRY） | **字节不变**，仅被 `neuro_bus_bridge.py` 包裹 |
| `app/neuro_bus/bus_setup.py`（`NeuroBusManager`/lifespan） | 生命周期管理 | 保留，组合根负责启停 |
| `app/neuro_bus/events/base.py`（`NeuroEvent`） | 事件载荷契约 | 不直接暴露给 application；由桥转 DTO |
| `app/neuro_bus/domains/`、`transports/`、`integrations/` | 处理器 / Redis / FastAPI 端点 | 保留 |
| `app/neuro_bus/sandbox.py` | 沙箱（影子阶段只读执行） | 复用 |

对 application 只暴露最小事件 port：`EventBusPort` + `StateEventPublisher`。对 `app.neuro_bus.*` 的 import **只允许出现在 `app/infrastructure/workflow/neuro_bus_bridge.py`**（§7 门禁豁免B）。

### 5.2 运行时选择器放 infrastructure，application 不选型

- 选择器：`app/infrastructure/workflow/runtime_selector.py`（**TO CREATE**），按 `XCAGI_LG_RUNTIME` 构建 legacy/新运行时。
- 开关 helper：`lg_runtime_mode()` 放 `app/contexts/flags.py`（跨切面配置）。
- 组合根（`app/di/registry.py`/`app/bootstrap.py`/`lifespan`）调用选择器并把运行时注入 application；application 层（含 `shadow_canary.py`）**从不 import 选择器或 infrastructure**，只消费注入的 ports。

---

## 6. XCAGI LangGraph 运行时（图执行器，本迁移核心）

新增 infrastructure 执行器（`TO CREATE`）：
- `app/infrastructure/workflow/langgraph_runtime.py`：实现 application port `WorkflowRuntime`，**真正执行图**。
- `app/infrastructure/workflow/langgraph_assert.py`：模块来源断言 + 本地 provenance/license 检查。

### 6.1 消费的 vendored 模块（直接 import，仅 infrastructure）

```python
from langgraph.graph.state import StateGraph, START, END     # vendored core  (LG-W0-02)
from langgraph.prebuilt.tool_node import ToolNode             # vendored prebuilt (LG-W0-05)
from langgraph.checkpoint.sqlite import SqliteSaver           # vendored checkpoint-sqlite
from langgraph.checkpoint.postgres import PostgresSaver       # vendored checkpoint-postgres
from langgraph_sdk.client import LangGraphClient              # vendored sdk (W0-11)
```

### 6.2 模块来源断言（检查**具体模块**，非 `langgraph.__file__`）

`langgraph_assert.py` 的 `assert_vendored_sources()` 校验**具体子模块**（如 `langgraph.graph.state`、`langgraph.checkpoint.sqlite`、`langgraph.prebuilt.tool_node`、`langgraph_sdk.client`）的 `__file__` 必须解析到 `FHD/packages/` 下的 vendored 目录——**禁止**落到 site-packages（无任何 PyPI LangGraph 发行版参与运行时）。

### 6.3 boot 校验 vs build/CI 校验（分开）

- **boot（每进程仅本地校验，fail-closed）**：本地 `PROVENANCE.json`（`upstream_commit_sha == 41341457…`、`license == "MIT"`）+ `MANIFEST.sha256` 完整性 + §6.2 模块来源断言。**不联网**。
- **build/CI（网络 tag 校验归此处）**：`verify_vendor.py`（`FHD/packages/*/` 与 `FHD/third_party/langgraph/`）负责字节级比对与 tag `1.2.10` 的远程校验；`refresh_vendor.py` 负责再吸收。**不在每次 boot 执行**。

### 6.4 provenance / license 边界

- 只允许 import vendored 模块；`langgraph-cli` 非运行时、显式延期（§2）。
- 运行时随包保留 `LICENSE`（MIT）与 `PROVENANCE.json` 引用，不改变上游许可语义。
- 执行器自身不直接触碰 NeuroBus / DB / FastAPI——通过 ports 与持久化桥/事件桥协作。

### 6.5 与 legacy 的关系

`XCAGILangGraphRuntime` 与 `LegacyEngineAdapter` 实现**同一** `WorkflowRuntime` port，由 infrastructure 选择器按开关选择（§5.2）；shadow/canary 阶段两者并行差分（§8）。legacy **移除是后续生产门**，Wave-1 不执行移除。

---

## 7. 依赖接线（Wave-1 T1）：仓库本地 editable 源，杜绝 PyPI

`FHD/pyproject.toml` + `FHD/uv.lock`（根）必须把以下映射到**仓库本地 editable 源**（`[tool.uv.sources]`）：
`langgraph` → `packages/xcagi_langgraph_core`、`langgraph-checkpoint` → `packages/xcagi_langgraph_checkpoint`、`langgraph-checkpoint-sqlite`/`-postgres` → `packages/xcagi_langgraph_checkpoint_backends/{checkpoint-sqlite,checkpoint-postgres}`、`langgraph-prebuilt` → `packages/xcagi_langgraph_prebuilt`、`langgraph-sdk` → `packages/xcagi_langgraph_sdk`。

- **证明无 PyPI LangGraph 发行版满足运行时**：T1 验收断言各具体模块 `__file__` 均位于 `packages/`（§6.2），且 `uv.lock` 解析自本地 sources。
- `bus.py` 全程只读；本任务不改产品代码，只改根依赖文件。

---

## 8. 灰度门控：legacy → shadow → canary → primary（Wave-1）/ remove（后续生产门）

| 门 | 行为 | 服务面 | 回滚 |
|---|---|---|---|
| `legacy`（默认） | 走 `LegacyEngineAdapter`（`WorkflowEngine` 原样） | 100% | — |
| `shadow` | `XCAGILangGraphRuntime` 并行执行，结果**不对外服务**，仅差分比对（复用 `app/neuro_bus/sandbox.py` 只读 dispatcher） | 0% | 关开关即回 legacy |
| `canary` | 新运行时承载 X% 流量，其余 legacy | X% | 降 X 或归零 |
| `primary` | 新运行时 100% | 100% | 翻回 legacy |
| `remove`（**非 Wave-1**） | **后续生产观察期门**：需显式证据（primary 运行 ≥ 观察窗口、零回归、差分收敛）+ 可回滚（进 `archive/` 前保留 tag）后才停用 legacy 适配器 | 100% | 需代码回滚（不可热回滚） |

> **Wave-1 不 claim 立即 legacy 移除。** T10 只达「本地验收 / primary-ready」，`remove` 是后续独立生产门，本系列文档 01–09 或后续 Wave 单独定义其证据与回滚。

### dual-write 风险与缓解（shadow/canary 阶段必须处理）

1. **副作用双执行**：写/高风险节点在两个运行时都执行 → shadow 阶段 dispatcher **只读/沙箱**（`app/neuro_bus/sandbox.py` 或 no-op dispatcher），禁止真实写；canary 阶段写节点强制串行且只在被选运行时执行。
2. **checkpoint 命名空间冲突**：vendored checkpoint 与 legacy `DatabaseWorkflowCheckpointer` 写同一 `plan_id` → 新运行时用独立命名空间（`plan_id + ":lg"`）或独立后端实例；`CheckpointStore` 按 `run_id` 隔离。
3. **事件去重**：NeuroBus 已内置 DEDUP（`_rel_dedup`）→ 双发 `state.update` 依赖其幂等；shadow 阶段不发布对外流式事件，仅本地记录差分。
4. **状态发散**：shadow 比对 `final_context` 归一化（复用 LG-W0-06 `_normalize_context` 思路），不一致记差分日志但不阻断。
5. **遥测双计**：指标按 `runtime=mode` 维度打点，避免聚合被影子流量污染。

---

## 9. Wave-1 任务（10 项，独占写域 + 依赖 + fail-closed 验收；依赖接线 T1 先行）

> 每任务写域**互不重叠（独占）**；`(TO CREATE)` 由该任务创建，其余为既有文件在该任务内修改。`bus.py` 全程**只读**。**禁 `rm -rf`**、禁 git 写操作。所有验收命令 **fail-closed**：无 `sys.path.insert`/`PYTHONPATH`、无 `|| true`；路径要么已存在要么标 `(TO CREATE)`。

### T1–T9 本地验收状态（2026-08-10，只读核实路径存在）

| 任务 | 写域路径（均已存在） | 本地状态 |
|---|---|---|
| T1 · 依赖接线 | `pyproject.toml`、`uv.lock` | ACCEPTED |
| T2 · Ports 契约 | `app/application/workflow/ports/{runtime,checkpoint,events,tools}.py` | ACCEPTED |
| T3 · LangGraph 运行时 | `app/infrastructure/workflow/{langgraph_runtime,langgraph_assert}.py` | ACCEPTED |
| T4 · Checkpoint 桥 | `app/infrastructure/workflow/checkpoint_bridge.py` | ACCEPTED |
| T5 · NeuroBus 桥 | `app/infrastructure/workflow/neuro_bus_bridge.py`（`bus.py` 字节不变） | ACCEPTED |
| T6 · Legacy 适配器 | `app/infrastructure/workflow/legacy_engine_adapter.py` | ACCEPTED |
| T7 · 选择器+开关 | `app/infrastructure/workflow/runtime_selector.py`、`app/contexts/flags.py` | ACCEPTED |
| T8 · Shadow+Canary | `app/application/workflow/runtime/shadow_canary.py` | ACCEPTED |
| T9 · 组合根装配 | `app/di/registry.py`、`app/bootstrap.py`、`app/fastapi_app/lifespan.py`、`app/application/ai_chat_app_service.py` | ACCEPTED |

> 以上仅依据既有路径与当前架构内容核实为**本地 ACCEPTED**；不构成生产证据。生产 shadow/canary 观测、业务回归、桌面端验收、发布制品、legacy 移除均**未 claim**（见 §0），legacy 引擎仍为可用回滚路径。

### T1 · 依赖接线（FHD 根：pyproject + uv.lock）
- **写域**：`FHD/pyproject.toml`、`FHD/uv.lock`（根，均**修改**）。
- **依赖**：W0-11 与 W0-12 均 EXISTING AND ACCEPTED（§2 前置，非 Wave-1）。
- **内容**：把全部 LangGraph 发行版（`langgraph`/`langgraph-checkpoint`/`langgraph-checkpoint-sqlite`/`langgraph-checkpoint-postgres`/`langgraph-prebuilt`/`langgraph-sdk`）加入 FHD 项目 `dependencies`，并在 `[tool.uv.sources]` 全部映射到仓库本地 editable 源；重新生成/校验 `FHD/uv.lock`。**实际同步一律用 `uv sync --locked --inexact`（不得用裸 `uv sync --locked`，否则会因运行时/开发依赖位于 optional extras 而卸载 159 个合法根包）**，先 `--dry-run`，再做前后 installed-distribution 清单比对，任何意外移除既有发行版即失败。
- **验收**（fail-closed；`--inexact` 不误删既有发行版）：
  ```bash
  cd FHD
  uv pip list --python .venv/bin/python --format=freeze > /tmp/lg-root-before.txt
  uv sync --locked --inexact --dry-run
  uv sync --locked --inexact
  uv pip list --python .venv/bin/python --format=freeze > /tmp/lg-root-after.txt
  comm -23 /tmp/lg-root-before.txt /tmp/lg-root-after.txt > /tmp/lg-root-removed.txt
  test ! -s /tmp/lg-root-removed.txt
  .venv/bin/python -c "import importlib; mods=['langgraph.graph.state','langgraph.checkpoint.sqlite','langgraph.prebuilt.tool_node','langgraph_sdk.client']; ms=[importlib.import_module(m) for m in mods]; assert all('/packages/xcagi_langgraph_' in m.__file__ for m in ms), [m.__file__ for m in ms]; print('all vendored: no PyPI langgraph')"
  ```
- 说明：`--dry-run` 预演 + 前后清单 inventory（`comm -23 before after` 非空即移除，`test ! -s` 阻断）+ 本地 editable 来源断言，共同证明同步安全且无 PyPI LangGraph 发行版参与运行时。

### T2 · Ports 契约（application）
- **写域**：`app/application/workflow/ports/{runtime,checkpoint,events,tools}.py`（**均 TO CREATE**）。
- **依赖**：T1；LG-W0-06 契约冻结（只读参考）。
- **验收**：
  ```bash
  cd FHD
  .venv/bin/python -m py_compile app/application/workflow/ports/runtime.py app/application/workflow/ports/checkpoint.py app/application/workflow/ports/events.py app/application/workflow/ports/tools.py
  ruff check app/application/workflow/ports/
  .venv/bin/python -m pytest tests/langgraph_absorption/test_legacy_runtime_contract.py -q
  ```

### T3 · XCAGI LangGraph 运行时（infrastructure，图执行器）
- **写域**：`app/infrastructure/workflow/langgraph_runtime.py`、`app/infrastructure/workflow/langgraph_assert.py`（**均 TO CREATE**）。
- **依赖**：T1、T2。
- **验收**（具体模块来源断言 + 本地 provenance，全部 fail-closed）：
  ```bash
  cd FHD
  .venv/bin/python -c "from app.infrastructure.workflow.langgraph_assert import assert_vendored_sources; assert_vendored_sources(); print('OK')"
  .venv/bin/python -c "from app.infrastructure.workflow.langgraph_runtime import XCAGILangGraphRuntime; r=XCAGILangGraphRuntime(); print('OK')"
  ruff check app/infrastructure/workflow/langgraph_runtime.py app/infrastructure/workflow/langgraph_assert.py
  ```

### T4 · Checkpoint 持久化桥（infrastructure）
- **写域**：`app/infrastructure/workflow/checkpoint_bridge.py`（**TO CREATE**）。
- **依赖**：T1、T2。
- **验收**：
  ```bash
  cd FHD
  .venv/bin/python -c "from app.infrastructure.workflow.checkpoint_bridge import LanggraphCheckpointBridge; print('OK')"
  .venv/bin/python -c "from langgraph.checkpoint.sqlite import SqliteSaver; from langgraph.checkpoint.postgres import PostgresSaver; print('OK')"
  ruff check app/infrastructure/workflow/checkpoint_bridge.py
  ```

### T5 · NeuroBus 事件桥（infrastructure；bus.py 字节不变）
- **写域**：`app/infrastructure/workflow/neuro_bus_bridge.py`（**TO CREATE**）。`app/neuro_bus/bus.py` **只读校验**。
- **依赖**：T1、T2。
- **验收**：
  ```bash
  cd FHD
  git diff --exit-code -- app/neuro_bus/bus.py
  .venv/bin/python -c "from app.infrastructure.workflow.neuro_bus_bridge import NeuroBusEventBridge; print('OK')"
  ruff check app/infrastructure/workflow/neuro_bus_bridge.py
  ```

### T6 · Legacy 引擎适配器（infrastructure）
- **写域**：`app/infrastructure/workflow/legacy_engine_adapter.py`（**TO CREATE**）。
- **依赖**：T1、T2。
- **验收**：
  ```bash
  cd FHD
  .venv/bin/python -c "from app.infrastructure.workflow.legacy_engine_adapter import LegacyEngineAdapter; print('OK')"
  .venv/bin/python -m pytest tests/langgraph_absorption/test_legacy_runtime_contract.py -q
  ruff check app/infrastructure/workflow/legacy_engine_adapter.py
  ```

### T7 · 运行时选择器 + 特性开关（infrastructure，application 不选型）
- **写域**：`app/infrastructure/workflow/runtime_selector.py`（**TO CREATE**）、`app/contexts/flags.py`（**修改**：新增 `lg_runtime_mode()` 读 `XCAGI_LG_RUNTIME`）。
- **依赖**：T3、T4、T5、T6。
- **验收**：
  ```bash
  cd FHD
  XCAGI_LG_RUNTIME=legacy .venv/bin/python -c "from app.infrastructure.workflow.runtime_selector import resolve_runtime; r=resolve_runtime(); assert r.__class__.__name__=='LegacyEngineAdapter'; print(r.__class__.__name__)"
  XCAGI_LG_RUNTIME=primary .venv/bin/python -c "from app.infrastructure.workflow.runtime_selector import resolve_runtime; r=resolve_runtime(); assert r.__class__.__name__=='XCAGILangGraphRuntime'; print(r.__class__.__name__)"
  .venv/bin/python -m pytest tests/langgraph_absorption/test_legacy_runtime_contract.py -q
  ```

### T8 · Shadow + Canary 编排（application，仅注入 ports）
- **写域**：`app/application/workflow/runtime/shadow_canary.py`（**TO CREATE**；含只读 dispatcher + 归一化差分 + canary 比例采样，复用 LG-W0-06 `_normalize_context` 思路）。**只 import ports，不 import infrastructure/selector/neuro_bus/langgraph。**
- **依赖**：T7。
- **验收**：
  ```bash
  cd FHD
  .venv/bin/python -c "from app.application.workflow.runtime.shadow_canary import ShadowCanaryRouter; from app.application.workflow.ports.runtime import WorkflowRuntime; print('OK')"
  XCAGI_LG_RUNTIME=shadow .venv/bin/python -m pytest tests/langgraph_absorption/test_legacy_runtime_contract.py -q
  ruff check app/application/workflow/runtime/shadow_canary.py
  ```

### T9 · 组合根装配 + 消费方接线（composition root + consumer）
- **写域**：`app/di/registry.py`（**修改**：`ServiceContainer` 懒加载经选择器构建运行时）、`app/bootstrap.py`（**修改**：新增 `get_workflow_runtime()`）、`app/fastapi_app/lifespan.py`（**修改**：启动期构建/重载运行时 + 本地模块来源断言，挂 `app.state`）、`app/application/ai_chat_app_service.py`（**修改**：去第 125/2202/2290 行直接 `WorkflowEngine(...)`/`DatabaseWorkflowCheckpointer()`，改组合根注入）。
- **依赖**：T7、T8。
- **验收**：
  ```bash
  cd FHD
  .venv/bin/python -c "from app.bootstrap import get_workflow_runtime; assert get_workflow_runtime() is not None; print('OK')"
  ruff check app/di/registry.py app/bootstrap.py app/fastapi_app/lifespan.py app/application/ai_chat_app_service.py
  .venv/bin/python -m pytest tests/test_application/test_ai_chat_app_service.py tests/test_application/test_ai_chat_app_service_ext.py -q
  .venv/bin/python -m pytest tests/langgraph_absorption/test_legacy_runtime_contract.py -q
  ```

### T10 · 目标运行时契约 + 静态边界 + 本地验收（primary-ready，**不移除 legacy、不改 legacy 契约**）
- **写域**：`scripts/dev/import_boundary.py`、`config/import_boundary.yaml`、`tests/langgraph_absorption/test_langgraph_runtime_contract.py`、`tests/langgraph_absorption/fixtures/langgraph_runtime_contract.json`（**均 EXISTING AND ACCEPTED**，2026-08-10 只读核实）、本文件（**修改**：状态勾选）。
- **不变更**：`tests/langgraph_absorption/test_legacy_runtime_contract.py` 与 `tests/langgraph_absorption/fixtures/legacy_contract.json` **保持原样，不覆盖、不挪用**（legacy 契约冻结红线，迁移期不改）。
- **依赖**：T1–T9 全部通过。
- **验收**（fail-closed；legacy 只读回归，不 claim 移除）：
  ```bash
  cd FHD
  python scripts/dev/import_boundary.py --check
  python scripts/dev/import_boundary.py --selfcheck
  .venv/bin/python -m pytest tests/langgraph_absorption/test_langgraph_runtime_contract.py -q
  .venv/bin/python -m pytest tests/langgraph_absorption/test_legacy_runtime_contract.py -q   # 只读回归：legacy 契约不改，仅复跑验证
  git diff --exit-code -- app/neuro_bus/bus.py tests/langgraph_absorption/test_legacy_runtime_contract.py tests/langgraph_absorption/fixtures/legacy_contract.json
  ```
- **说明**：目标运行时以 `XCAGILangGraphRuntime` 为 SSOT 的**独立新契约文件**验收（`test_langgraph_runtime_contract.py` + `fixtures/langgraph_runtime_contract.json`，由该测试自行生成/冻结），不触碰 legacy 契约；`primary` 为 Wave-1 上限；`remove` 需后续生产观察期门（§8）另行定义证据与回滚，**不在本任务 claim**。
- **T10 本地验收证据（2026-08-10，fail-closed 复跑确认）**：
  - `import_boundary.py --check`：**4 条规则**分别扫描 **6 / 1282 / 7 / 320** 个 Python 文件，**0 违规**（`workflow-application-ports-runtime`=6、`no-langgraph-outside-infra-workflow`=1282、`neuro-bus-only-in-infra-workflow-bridge`=7、`application-must-not-import-infra-workflow`=320）。
  - `import_boundary.py --selfcheck`：**22 个用例全部 PASS**。
  - `test_langgraph_runtime_contract.py`：**64 tests 通过**（连续两次复跑一致）。
  - `test_legacy_runtime_contract.py`：**46 tests 通过**（frozen legacy 契约只读回归）。
  - `ruff check` 与 `ruff format --check`（`import_boundary.py` + `test_langgraph_runtime_contract.py`）：**通过**。
  - 新冻结 fixture SHA256：`b5d2c7042bd2da8eeaff1e563bd2d65b55872ccf1b16b8c927fe52f86adcf34f`。
  - protected diff（`git diff --exit-code`）：`app/neuro_bus/bus.py`、`tests/langgraph_absorption/test_legacy_runtime_contract.py`、`tests/langgraph_absorption/fixtures/legacy_contract.json` **均零 diff**。
  - 受保护 SHA256：`app/neuro_bus/bus.py` = `e2e9d6f895b5d4f743376349376983b89587bd32992c1d754d9ca6a83fa8d3db`；frozen legacy test = `6f401b95671deb411ac68c5aee5772e87d86d9282ec6b90e420f666558502194`；frozen legacy fixture = `4d57c8c236fcc2b61e0895997aee07f37de7805a2f78afb9f4cbe35636188e41`。

### 依赖图（Wave-1）

```
T1 → (T2, T3, T4, T5, T6)      # 依赖接线先行
T2 → (T3, T4, T5)
T3, T4, T5, T6 → T7
T7 → T8
T7, T8 → T9
T1..T9 → T10
```

---

## 10. 范围与约束

- **只允许修改本文件**（本任务产物）；其余 `(TO CREATE)` 路径由对应 Wave-1 任务创建。
- **不改产品/包/测试文件、不做 `git add/commit/push/reset`、不做 `rm -rf`**（旧实现移 `archive/` 或停用保留）。
- `app/neuro_bus/bus.py` 全程**只读**，验收含 `git diff --exit-code`。
- 前置：**W0-11（SDK 包）与 W0-12（接线 core/prebuilt → 本地 SDK）均已 EXISTING AND ACCEPTED**（W0-11 测试+在线字节校验通过，W0-12 本地 editable SDK 源通过）；Wave-1 T1 以其为基；`langgraph-cli` 非运行时显式延期。
- 上游精确 tag **`1.2.10`**（非 `v1.2.10`）；强 pin 用 commit `41341457…`。
- application **不得选择/import infrastructure**；选择器在 infrastructure，application shadow/canary 仅依赖注入 ports。
- 模块来源断言检查**具体模块**（`langgraph.graph.state`/`checkpoint.sqlite`/`prebuilt.tool_node`/`langgraph_sdk.client`），非 `langgraph.__file__`。
- boot 仅本地校验（PROVENANCE/MANIFEST/模块来源）；网络 tag 校验归 build/CI（`verify_vendor.py`）。
- 门控 `legacy→shadow→canary→primary` 属 Wave-1；`remove` 为后续生产观察期门，T10 只达 primary-ready，**不 claim 立即移除**。
- 图执行器 = XCAGI LangGraph 运行时；NeuroBus = 事件桥。
- 全部验收命令 **fail-closed**；路径要么已存在要么标 `(TO CREATE)`。
