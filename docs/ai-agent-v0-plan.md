# AI Agent 平台 V0 实施计划（M2-W2）

> **状态（2026-06）**：**demo 已留证** — CLI `run_demo.py` + `demo-checklist.sh --verify` 可过；不得在 [`CLAIMED_VS_ACTUAL.md`](CLAIMED_VS_ACTUAL.md) 标「已验证」除非负责人对账。  
> **对照 SSOT**：[`M1-kickoff-checklist.md`](M1-kickoff-checklist.md) M2-W2 · [`specs/对标头部SaaS-步骤路径图.md`](../../specs/对标头部SaaS-步骤路径图.md) 阶段 1  
> **不依赖 M0 staging**（T36–T37）：可与 API 契约测试、Mod 四图并行开工。

---

## 1. 目标与边界

### 1.1 M1 验收原文（对账）

| 项 | 内容 |
|----|------|
| 任务 | **AI Agent 平台 V0** |
| 验收 | 自然语言 → 工作流；**1 个 demo 跑通**（`workflow/engine.py` + LLM planner） |
| staging 依赖 | **否** |

### 1.2 V0 做什么（In Scope）

**核心链路**（已有代码，V0 只做「选场景 + 跑通 + 留证」）：

```text
用户自然语言
    → LLMWorkflowPlanner.plan()     # planner.py：ReAct/CoT + ToolProbe + fallback
    → PlanGraph（nodes + depends_on）
    → HybridRiskGate.evaluate()     # 低风险自动执行；中高风险需确认
    → WorkflowEngine.run()          # engine.py：拓扑批执行 或 AgenticLoop
    → WorkflowRunResult + 可读回复
```

**V0 demo 范围（最小可演示）**：

| 维度 | V0 约定 |
|------|---------|
| 入口 | **CLI 脚本**（`scripts/ai_agent_v0/run_demo.py`）为主；可选复用现有 AI 聊天 API（`/api/...` 经 `ai_chat_app_service`）作二次验证 |
| 场景数 | **1 条**端到端 happy path |
| 推荐场景 | **只读查询链**：如「查一下七彩乐园有哪些产品」→ `customers.query` → `products.query`（低风险、无审批、不依赖 Excel） |
| 执行模式 | `agentic_loop=False`（批执行 `_run_batch`）；AgenticLoop（`_run_agentic_loop`）列为 **V0.1**，不在 M2-W2 阻塞项 |
| LLM | 需配置 `DEEPSEEK_API_KEY`（或项目现有 AI gateway 等价变量）；无 Key 时允许 **fallback planner** 跑通并标注 `SYNTHETIC` |
| 数据 | 本地 dev DB / mock 均可；**禁止**伪造「已对接 staging 生产库」 |

### 1.3 V0 不做什么（Out of Scope）

- 新增业务工具或改 `specs/` 下任何文件
- 大改 `ai_chat_app_service.py`、前端工作流可视化、审批 UI
- AgenticLoop + Excel 多步自主决策（已有 `engine.py` 能力，非 V0 验收）
- 依赖 staging 7 天流量、只读生产库（属 AI 月报 M2-W3）
- 在 CLAIMED 标「已验证」前提交假截图 / 假 JSON

---

## 2. 现有代码对照（`workflow/engine.py` 等）

V0 **复用**以下模块，原则上 **不改业务逻辑**（仅 demo 脚本与文档）：

| 模块 | 路径 | V0 角色 |
|------|------|---------|
| 类型与校验 | [`app/application/workflow/types.py`](../app/application/workflow/types.py) | `PlanGraph` / `WorkflowNode` / `validate_plan_graph` |
| LLM 规划器 | [`app/application/workflow/planner.py`](../app/application/workflow/planner.py) | `LLMWorkflowPlanner.plan()` · `get_tool_registry()` · fallback |
| 执行引擎 | [`app/application/workflow/engine.py`](../app/application/workflow/engine.py) | `WorkflowEngine.run()` · `_run_batch` ·（可选后续）`_run_agentic_loop` |
| 风险门控 | [`app/application/workflow/risk_gate.py`](../app/application/workflow/risk_gate.py) | `HybridRiskGate` — 只读 demo 应 `requires_confirmation=False` |
| 聊天集成 | [`app/application/ai_chat_app_service.py`](../app/application/ai_chat_app_service.py) | 生产路径：`plan → gate → engine.run`（约 L1977–2063） |
| 工具分发 | [`app/services/tools_workflow_registered.py`](../app/services/tools_workflow_registered.py) | `WorkflowEngine` 共用 dispatcher |
| 单元/冒烟 | [`XCAGI/tools/smoke_tests/test_dynamic_workflow_engine.py`](../XCAGI/tools/smoke_tests/test_dynamic_workflow_engine.py) | 回归基线（mock dispatcher，无 LLM） |

### 2.1 引擎行为摘要（实施时需对齐）

**批执行**（V0 默认）— `WorkflowEngine._run_batch`：

- 按 `depends_on` 拓扑顺序执行节点；失败即短路返回
- `runtime_context["node_outputs"]` 累积上游输出
- `products.query` / `customers.query` 可在 params 为空时注入用户原话（`_merge_runtime_fallback_params`）

**Agentic 循环**（V0.1）— `WorkflowEngine._run_agentic_loop`：

- LLM 单步决策 → 调工具 → 写 history → 直至 `action=done` 或 `max_steps=10`
- 当前聊天路径仅在存在 `excel_analysis.file_path` 时启用（`ai_chat_app_service` L2049）

**规划器** — `LLMWorkflowPlanner._plan_with_react_multiagent`：

- Decomposer → ToolProbe（低风险只读）→ PlanComposer → Critic 修复 → 失败则 `_fallback_plan`

---

## 3. 推荐 Demo 场景（1 条）

### 场景 A（V0 默认）：客户 + 产品只读链

| 步骤 | 内容 |
|------|------|
| 输入 | `查一下七彩乐园有哪些产品`（或仓内已有 seed 客户名） |
| 期望 PlanGraph | ≥2 节点：`customers.query` → `products.query`，含合法 `depends_on` |
| 期望执行 | `WorkflowRunResult.success == True`；`node_results` 长度 ≥2 |
| 期望门控 | 全 `risk=low` → 无需用户「确认」 |
| 证据 | 终端日志 + 结构化 JSON 入 [`evidence/ai-agent-v0/`](evidence/ai-agent-v0/) |

### 场景 B（可选加分，非阻塞）

- 含 `medium` 写节点（如 `customers.ensure_exists`）→ 验证 `HybridRiskGate` 返回确认态，**不自动执行**

---

## 4. 文件清单

### 4.1 已有（只读 / 集成点）

| 文件 | 说明 |
|------|------|
| `app/application/workflow/types.py` | 计划图数据结构 |
| `app/application/workflow/planner.py` | LLM 规划 + fallback |
| `app/application/workflow/engine.py` | 执行引擎 |
| `app/application/workflow/risk_gate.py` | 风险门控 |
| `app/application/workflow/approval_service.py` | 审批节点（V0 只读场景不触发） |
| `app/application/ai_chat_app_service.py` | 线上聊天工作流编排 |
| `app/routes/tools.py` | `get_workflow_tool_registry()` |
| `app/services/tools_workflow_registered.py` | 工具 dispatcher |
| `XCAGI/tools/smoke_tests/test_dynamic_workflow_engine.py` | 无 LLM 冒烟 |

### 4.2 V0 新增（本计划交付 / 后续实现）

| 文件 | 状态 | 说明 |
|------|------|------|
| [`docs/ai-agent-v0-plan.md`](ai-agent-v0-plan.md) | ✅ 本文 | 范围、清单、验收 |
| [`docs/evidence/ai-agent-v0/README.md`](evidence/ai-agent-v0/README.md) | ✅ stub | 证据目录说明 |
| [`scripts/ai_agent_v0/demo-checklist.sh`](../scripts/ai_agent_v0/demo-checklist.sh) | ✅ stub | `--check-only` / `--verify` 占位 |
| `scripts/ai_agent_v0/run_demo.py` | ✅ | CLI：message → plan → run → 写 JSON |
| `docs/evidence/ai-agent-v0/demo-run-YYYYMMDD.json` | ✅ | 一次完整运行的结构化输出（见目录内 `demo-run-*.json`） |
| `docs/evidence/ai-agent-v0/demo-run-YYYYMMDD.log` | ⬜ 可选 | 终端重定向日志 |
| `docs/evidence/ai-agent-v0/demo-screenshot.png` | ⬜ 可选 | 聊天 UI 或 CLI 输出截图 |

### 4.3 环境变量（与现有 AI gateway 对齐）

| 变量 | 用途 |
|------|------|
| `DEEPSEEK_API_KEY` | planner +（若测 AgenticLoop）engine LLM |
| `DATABASE_URL` | 只读查询链需要本地 PG/SQLite（与 dev 启动方式一致） |

无 API Key 时：demo 须走 `LLMWorkflowPlanner._fallback_plan`，证据 JSON 中 `"planner_mode": "fallback"`，**不得**冒充 LLM 全链路。

---

## 5. 验收标准

### 5.1 必须满足（M2-W2 闭环）

1. **自然语言 → PlanGraph**：对场景 A 输入，`validate_plan_graph(plan)` 为 `None`；`plan.nodes` ≥1（LLM 或 fallback 均可）。
2. **PlanGraph → 执行完成**：`WorkflowEngine.run(..., agentic_loop=False)` 返回 `success=True`（只读链 + 本地有 seed 数据）。
3. **可重复运行**：`bash scripts/ai_agent_v0/demo-checklist.sh --check-only` 通过（目录与文档就位）；demo 完成后 `--verify` 通过（见证据 README）。
4. **证据入库**：至少 1 份 `docs/evidence/ai-agent-v0/demo-run-*.json`，字段含：`input_message`、`plan_id`、`intent`、`nodes`、`success`、`node_results` 摘要。
5. **回归不回归**：`pytest XCAGI/tools/smoke_tests/test_dynamic_workflow_engine.py -q` 仍全绿。
6. **CLAIMED 纪律**：未满足 1–4 前，不更新 CLAIMED「AI Agent」类行；满足后由负责人单行追加并链到本目录。

### 5.2 建议满足（非阻塞）

- 有 API Key 时 `plan.metadata.planner` 含 `llm` / `react` 等，与 fallback 区分
- 同场景经聊天 API 复现一次（截图入 evidence）
- `run_demo.py` 支持 `--message` / `--dry-plan`（只规划不执行）

### 5.3 禁止

- 修改 `specs/` 下文件冒充验收
- 无 demo JSON 对外宣称「AI Agent V0 已跑通」
- 将 V0 demo 与 staging SLO / AI 月报（T36–T37、T56）混为一谈

---

## 6. 执行步骤（建议顺序）

| # | 动作 | 产出 |
|---|------|------|
| 1 | 读本文 + 对照 `engine.py` / `planner.py` | 确认场景 A 与工具 registry |
| 2 | 实现 `scripts/ai_agent_v0/run_demo.py`（薄封装，调现有类） | 本地可执行 |
| 3 | 配置 dev DB +（可选）API Key，跑场景 A | `demo-run-*.json` |
| 4 | `demo-checklist.sh --verify` | 证据校验通过 |
| 5 | 更新 [`M1-kickoff-checklist.md`](M1-kickoff-checklist.md) M2-W2 行 → ✅ | 阶段对账 |
| 6 | 按需更新 CLAIMED（事实一行 + 链接） | 对外一致 |

---

## 7. 自动化

**脚本 SSOT**：[`scripts/ai_agent_v0/demo-checklist.sh`](../scripts/ai_agent_v0/demo-checklist.sh)

```bash
cd FHD
bash scripts/ai_agent_v0/demo-checklist.sh --check-only   # 仅校验目录/文档（无需 LLM/DB）
bash scripts/ai_agent_v0/demo-checklist.sh --verify       # demo JSON 就位后校验
# 待 run_demo.py 就绪：
# python3 scripts/ai_agent_v0/run_demo.py --message "查一下七彩乐园有哪些产品"
```

---

## 8. 相关文档

- M1 启动清单：[`M1-kickoff-checklist.md`](M1-kickoff-checklist.md)
- M0 剩余缺口：[`M0-remaining-gaps.md`](M0-remaining-gaps.md)
- 声称对照：[`CLAIMED_VS_ACTUAL.md`](CLAIMED_VS_ACTUAL.md)
- 工作流冒烟：[`XCAGI/tools/smoke_tests/test_dynamic_workflow_engine.py`](../XCAGI/tools/smoke_tests/test_dynamic_workflow_engine.py)
- 证据目录：[`evidence/ai-agent-v0/`](evidence/ai-agent-v0/)

---

| 日期 | 更新 |
|------|------|
| 2026-06-05 | 初版：对照 M1 M2-W2 与 workflow 引擎/planner；定点 demo 范围与验收 |
