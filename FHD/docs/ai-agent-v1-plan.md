# AI Agent 平台 V1 实施计划 — AI 全自动全流程

> **范围**：从 V0（1 条只读链 demo）升级到 V1（**多场景写操作 + 审批门控 + RAG + 端到端业务**）。  
> **依赖**：[`ai-agent-v0-plan.md`](ai-agent-v0-plan.md) 闭环（✅ 2026-06-05）。  
> **声称对照**：[`CLAIMED_VS_ACTUAL.md`](CLAIMED_VS_ACTUAL.md) V1 段（✅ 2026-06-05 已写入）。  
> **状态（2026-06-05）**：Phase 1-4 全部代码 + 留证闭环。Phase 4.1 Mod 商店 + Phase 4.2 ERP 端到端 JSON 已落盘 `docs/evidence/ai-agent-v1/`。

---

## 1. 目标与边界

### 1.1 V1 验收（与 V0 对照）

| 项 | V0（2026-06-05 已留证） | V1（本计划交付） |
|----|--------------------------|-----------------|
| 场景数 | 1 条只读链 | 7 条端到端业务链（3 写 + 4 混合） |
| 写操作 | ❌ | ✅（含审批门控） |
| 风险门控 | HybridRiskGate（仅标记） | HybridRiskGate + ApprovalService（**实际生成审批工单**） |
| LLM Planner | ReAct/CoT 多 Agent | 复用 + 写场景 prompt 增强 |
| RAG | 仅用户记忆 RAG | 语义分块 + 混合检索 + 引用溯源 |
| 工作流新节点 | 无 | HTTP / data_transform / loop / sub_workflow |
| 端到端 | 1 条只读 | 2 段真实业务录屏（Mod 商店 + ERP） |
| 留证 | 1 份 JSON | 7 份场景 JSON + 2 段视频/截图 + 月报 |

### 1.2 V1 做什么（In Scope）

```
用户自然语言
    → LLMWorkflowPlanner.plan()         # 复用 V0
    → ApprovalGatedEngine.evaluate()     # 【新】HybridRiskGate + ApprovalService
        ├ low-risk 节点：自动通过
        └ medium/high 节点：生成 approval_requests 工单
            ├ strategy=auto        ：自动批准（CLI 演示）
            ├ strategy=reject      ：自动拒绝（演示拒绝路径）
            └ strategy=interactive ：挂起（生产人工审批 → resume_after_approval）
    → ApprovalGatedEngine.run()         # 全批准后执行
    → WorkflowEngine._run_batch()       # 复用 V0
    → RAG 检索增强（Phase 3）
    → 端到端业务演示（Phase 4）
```

### 1.3 V1 不做什么（Out of Scope）

- 不替代现有 `/api/approval` 工作台（V1 与之并用）
- 不做 UI（V1 仅 CLI 演示 + API；UI 留给 V1.1）
- 不改业务域 14 路由登记
- 不依赖 staging（T36–T37）

---

## 2. Phase 划分

### Phase 1：写操作门控闭环（1-2 周）

| 交付 | 路径 |
|------|------|
| `ApprovalGatedEngine` | [`app/application/workflow/approval_gated_engine.py`](../app/application/workflow/approval_gated_engine.py) |
| 写链路 demo（创建客户+订单+审批） | [`scripts/ai_agent_v1/run_demo_create_order.py`](../scripts/ai_agent_v1/run_demo_create_order.py) |
| 证据 | `docs/evidence/ai-agent-v1/create-order-*.json` |
| `auto / interactive / reject` 三策略 | 同一 demo CLI 支持 `--strategy` |

### Phase 2：多场景 V1 demo（2-3 周）

| # | 场景 | 风险 | 工具链 |
|---|------|------|--------|
| 1 | 本周销售情况 | low | `shipment_records.query` |
| 2 | 创建订单 | medium | `customers.ensure_exists` → `shipment_generate.generate` |
| 3 | 标记发货 | medium | `shipment_records.update` |
| 4 | 库存补货 | medium | `inventory.query` → `purchase.draft` |
| 5 | OCR 失败重跑 | low | `ocr.retry` |
| 6 | 发货通知 | medium | `wechat_send.preview` |
| 7 | 导 Excel | low | `excel_export.run` |

每条 demo = 一份 `evidence/ai-agent-v1/scenario-N-*.json`。

### Phase 3：RAG + 工作流节点（3-4 周）

**3.1 RAG 能力（见 [`../../.trae/documents/补齐RAG与工作流能力.md`](../../.trae/documents/补齐RAG与工作流能力.md)）**
- 语义分块（`SemanticChunker`）
- 混合检索（BM25 + 向量 RRF）
- 引用溯源（`[1][2]` → `citations`）
- 分块策略可配置
- Embedding 维度对齐

**3.2 工作流新节点**
- `http_request`（GET/POST/PUT/DELETE，模板变量）
- `data_transform`（JSONPath + 字段映射）
- `loop`（for_each / while，最大 100 迭代）
- `sub_workflow`（递归深度 3）

**3.3 FHD 聊天集成 RAG**
- `XCAGI_RAG_ENABLED=1` 开关
- `app/fastapi_routes/knowledge.py` 代理 MODstore `/api/knowledge/v2/*`

### Phase 4：端到端业务跑通（2-3 周）

| 场景 | 真实业务 | 状态 |
|------|----------|------|
| Mod 商店：识别异常 → 自动发通知 → 出月报 | 真实 Mod 订单 `MOD17806547526741` ¥9.90 | ✅ 2026-06-05 |
| ERP：客户下单 → AI 自动审单 → 自动发货 → 通知 → 出 Excel | 真实发货单 | ✅ 2026-06-05（mock + live 留证） |

---

## 3. 文件清单

### 3.1 新增（本计划交付）

| 文件 | 状态 | 说明 |
|------|------|------|
| `docs/ai-agent-v1-plan.md` | ✅ 本文 | V1 范围、阶段、验收 |
| `app/application/workflow/approval_gated_engine.py` | ✅ | 写操作门控引擎 |
| `app/application/workflow/v1_builtin_nodes.py` | ✅ | http_request / data_transform / loop / sub_workflow |
| `app/infrastructure/rag/rag_service.py` | ✅ | 语义分块 + 混合检索 + 引用溯源 |
| `app/fastapi_routes/knowledge_v1.py` | ✅ | 简化 RAG 知识库 API |
| `scripts/ai_agent_v1/__init__.py` | ✅ | 脚本包 |
| `scripts/ai_agent_v1/run_demo_create_order.py` | ✅ | Phase 1 写链路 demo |
| `scripts/ai_agent_v1/run_demo_v1.py` | ✅ | Phase 2 七场景总入口 |
| `scripts/ai_agent_v1/run_e2e_modstore.py` | ✅ | Phase 4.1 Mod 商店端到端 |
| `scripts/ai_agent_v1/run_e2e_erp.py` | ✅ | Phase 4.2 ERP 端到端 |
| `docs/evidence/ai-agent-v1/README.md` | ✅ | 证据目录 |
| `docs/evidence/ai-agent-v1/create-order-*.json` | ✅ | Phase 1 留证（auto / interactive / reject） |
| `docs/evidence/ai-agent-v1/scenario-N-*.json` | ✅ | Phase 2 留证（N=1..7） |
| `docs/evidence/ai-agent-v1/e2e-modstore-*.json` | ✅ | Phase 4.1 留证（auto / interactive / reject / live-real-order） |
| `docs/evidence/ai-agent-v1/e2e-erp-*.json` | ✅ | Phase 4.2 留证（auto / interactive） |

### 3.2 复用（不改）

- `app/application/workflow/engine.py`（V0）
- `app/application/workflow/planner.py`（V0）
- `app/application/workflow/risk_gate.py`（V0）
- `app/application/workflow/approval_service.py`（已有）
- `app/routes/tools.py`（V0 工具注册表）
- `resources/config/approval_config.yaml`（审批规则配置源）

---

## 4. 验收标准

### 4.1 Phase 1 必过

1. `ApprovalGatedEngine` 单测通过（auto / interactive / reject 三策略）
2. `run_demo_create_order.py --strategy auto` 端到端跑通 + 留证
3. `run_demo_create_order.py --strategy interactive` 返回 `pending_approval=True` + 至少 1 个 `approval_request_id`
4. `run_demo_create_order.py --strategy reject` 返回 `any_rejected=True` + 无执行
5. 写节点的 `approval_request_id` 在 `app_approval_requests` 表可见
6. 回归 V0：`bash scripts/ai_agent_v0/demo-checklist.sh --verify` 仍绿

### 4.2 Phase 2 必过

7. 7 份 `scenario-*.json` 证据就位
8. 至少 3 条含 medium 风险节点走 `ApprovalGatedEngine` 自动批准
9. 至少 1 条含 medium 风险节点走 interactive 留证（不执行）

### 4.3 Phase 3 必过

10. `SemanticChunker.split_by_semantic()` 单测
11. `HybridRetriever.retrieve()` 融合 BM25 + 向量
12. `http_request` / `data_transform` / `loop` / `sub_workflow` 4 节点单测
13. `XCAGI_RAG_ENABLED=1` 启动后，AI 聊天响应含 `citations` 字段

### 4.4 Phase 4 必过

14. Mod 商店端到端：1 段录屏 + 真实订单号 + 真实通知
15. ERP 端到端：1 段录屏 + 真实发货单号 + 真实通知
16. `CLAIMED_VS_ACTUAL.md` V1 段 4 行使者从「未验证」→「已验证（live）」

### 4.5 禁止

- 仍禁止把 SYNTHETIC 标 "已验证"
- 仍禁止在 `staging` 阻塞（staging SLO 仍属 T36–T37）
- 仍禁止在 `docs/specs/` 冒充验收

---

## 5. 执行步骤

```
Week 1   Phase 1.1 ApprovalGatedEngine
         Phase 1.2 run_demo_create_order.py
         Phase 1.3 evidence + CLAIMED 登记

Week 2-3 Phase 2.1-2.2 7 场景 demo + evidence

Week 4-7 Phase 3.1-3.3 RAG + 工作流新节点 + 集成

Week 8-9 Phase 4.1-4.3 端到端 + 录屏 + CLAIMED 收口
```

---

## 6. 自动化脚本

```bash
# Phase 1 验证
cd FHD
python3 scripts/ai_agent_v1/run_demo_create_order.py --strategy auto
python3 scripts/ai_agent_v1/run_demo_create_order.py --strategy interactive
python3 scripts/ai_agent_v1/run_demo_create_order.py --strategy reject

# Phase 2 验证
python3 scripts/ai_agent_v1/run_demo_v1.py --scenario all
python3 scripts/ai_agent_v1/run_demo_v1.py --scenario 2 --strategy auto

# Phase 4.1 Mod 商店端到端
python3 scripts/ai_agent_v1/run_e2e_modstore.py --strategy auto
python3 scripts/ai_agent_v1/run_e2e_modstore.py --strategy interactive
python3 scripts/ai_agent_v1/run_e2e_modstore.py --strategy reject

# Phase 4.2 ERP 端到端
python3 scripts/ai_agent_v1/run_e2e_erp.py --strategy auto
python3 scripts/ai_agent_v1/run_e2e_erp.py --strategy interactive

# 校验
bash scripts/ai_agent_v1/v1-checklist.sh --verify
```

---

## 7. 相关文档

- V0：[`ai-agent-v0-plan.md`](ai-agent-v0-plan.md)
- RAG/工作流能力补齐：[`../../.trae/documents/补齐RAG与工作流能力.md`](../../.trae/documents/补齐RAG与工作流能力.md)
- 声称对照：[`CLAIMED_VS_ACTUAL.md`](CLAIMED_VS_ACTUAL.md)
- 审批服务：[`../app/application/workflow/approval_service.py`](../app/application/workflow/approval_service.py)
- 审批配置：[`../resources/config/approval_config.yaml`](../resources/config/approval_config.yaml)

---

| 日期 | 更新 |
|------|------|
| 2026-06-05 | 初版：V1 范围、4 Phase 划分、文件清单、验收 |
| 2026-06-05 | Phase 1-4 全部代码 + 留证闭环：写操作门控（ApprovalGatedEngine）、RAG（语义分块 + 混合检索 + 引用溯源）、工作流新节点（http_request / data_transform / loop / sub_workflow）、7 场景 demo、Mod 商店 + ERP 端到端 JSON；CLAIMED_VS_ACTUAL V1 段已写入 |
