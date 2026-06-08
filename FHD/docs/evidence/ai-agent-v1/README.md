# AI Agent V1 证据目录

> **状态（2026-06-05）**：Phase 1-4 留证已闭环。Phase 1（写链路 demo）+ Phase 2（7 场景 demo）+ Phase 4（Mod 商店 + ERP 端到端）均已落盘；Phase 3（RAG + 工作流新节点）代码就绪并随 V0 V1 一并验证。

## 文件说明

| 文件 | 来源 | 说明 |
|------|------|------|
| `create-order-auto-*.json` | `run_demo_create_order.py --strategy auto` | 自动批准 + 完整执行 |
| `create-order-interactive-*.json` | `run_demo_create_order.py --strategy interactive` | 挂起审批 + 不执行 |
| `create-order-reject-*.json` | `run_demo_create_order.py --strategy reject` | 自动拒绝 + 不执行 |
| `scenario-N-*.json` | `run_demo_v1.py --scenario N` | 7 场景 V1 demo（N=1..7） |
| `e2e-modstore-*-auto.json` | `run_e2e_modstore.py --strategy auto` | Mod 商店端到端：mock 全部跑通 |
| `e2e-modstore-*-interactive.json` | `run_e2e_modstore.py --strategy interactive` | Mod 商店端到端：挂起审批 |
| `e2e-modstore-*-reject.json` | `run_e2e_modstore.py --strategy reject` | Mod 商店端到端：自动拒绝 |
| `e2e-modstore-*-live-real-order.json` | Mod 商店端到端 live | 真实 Mod 订单 `MOD17806547526741` ¥9.90 走通（详见 [`mod-pilot-blockers.md`](../../mod-pilot-blockers.md)） |
| `e2e-erp-*-auto.json` | `run_e2e_erp.py --strategy auto` | ERP 端到端：客户下单 → 审单 → 发货 → 通知 → Excel |
| `e2e-erp-*-interactive.json` | `run_e2e_erp.py --strategy interactive` | ERP 端到端：挂起审批 |

## 字段说明（与 V0 兼容 + 扩展）

```json
{
  "generated_at": "2026-06-05T12:00:00Z",
  "input_message": "...",
  "execution_mode": "live|mock",
  "approval_strategy": "auto|interactive|reject|null",
  "plan_id": "v1-...",
  "intent": "create_order_for_unit",
  "risk_level": "medium",
  "nodes": [...],
  "gated_decision": {
    "risk_decision": {...},
    "node_decisions": [...],
    "approval_request_ids": [...],
    "all_approved": true,
    "pending_approval": false,
    "any_rejected": false
  },
  "success": true,
  "message": "工作流执行完成",
  "node_results_summary": [...]
}
```

## 复现

```bash
cd FHD

# Phase 1: 写链路 demo
python3 scripts/ai_agent_v1/run_demo_create_order.py --strategy auto
python3 scripts/ai_agent_v1/run_demo_create_order.py --strategy interactive
python3 scripts/ai_agent_v1/run_demo_create_order.py --strategy reject

# Phase 2: 7 场景 V1
python3 scripts/ai_agent_v1/run_demo_v1.py --scenario all
python3 scripts/ai_agent_v1/run_demo_v1.py --scenario 2 --strategy auto

# Phase 4.1: Mod 商店端到端（识别异常 → 通知 → 月报）
python3 scripts/ai_agent_v1/run_e2e_modstore.py --strategy auto
python3 scripts/ai_agent_v1/run_e2e_modstore.py --strategy interactive
python3 scripts/ai_agent_v1/run_e2e_modstore.py --strategy reject

# Phase 4.2: ERP 端到端（客户下单 → 审单 → 发货 → 通知 → Excel）
python3 scripts/ai_agent_v1/run_e2e_erp.py --strategy auto
python3 scripts/ai_agent_v1/run_e2e_erp.py --strategy interactive

# 校验
bash scripts/ai_agent_v1/v1-checklist.sh --verify
```
