# AI Agent V0 证据目录（M2-W2）

> **状态（2026-06）**：**待 demo** — 跑通前禁止在 [`CLAIMED_VS_ACTUAL.md`](../../CLAIMED_VS_ACTUAL.md) 标「已验证」。  
> **实施计划**：[`docs/ai-agent-v0-plan.md`](../../ai-agent-v0-plan.md)

---

## 1. 必交产物

| 文件 | 说明 |
|------|------|
| `demo-run-YYYYMMDD.json` | 一次完整「自然语言 → plan → engine.run」的结构化输出 |
| （可选）`demo-run-YYYYMMDD.log` | CLI 终端重定向 |
| （可选）`demo-screenshot.png` | 聊天 UI 或 CLI 成功输出截图 |

### JSON 最低字段（`demo-checklist.sh --verify` 会检查）

```json
{
  "input_message": "查一下七彩乐园有哪些产品",
  "planner_mode": "llm | fallback",
  "plan_id": "...",
  "intent": "...",
  "nodes": [{"node_id": "...", "tool_id": "...", "action": "..."}],
  "success": true,
  "node_results_summary": [{"node_id": "...", "success": true}]
}
```

---

## 2. 校验命令

```bash
cd FHD
bash scripts/ai_agent_v0/demo-checklist.sh --check-only
bash scripts/ai_agent_v0/demo-checklist.sh --verify
```

---

## 3. 禁止

- 提交空 JSON / 手工编造 node 结果冒充真实执行
- 无 API Key 时将 `planner_mode` 标为 `llm`
- 将本目录证据与 staging SLO（T36–T37）或 AI 月报混为一谈

---

## 4. 关联

- 计划：[`ai-agent-v0-plan.md`](../../ai-agent-v0-plan.md)
- M1 对账：[`M1-kickoff-checklist.md`](../../M1-kickoff-checklist.md) M2-W2
