# AI Agent V0 证据目录（M2-W2）

> **状态（2026-06-05）**：**mock demo 已留证**（`demo-run-20260605.json`，`planner_mode=fallback`，`execution_mode=mock`）。本机无 LLM API Key；`AI_AGENT_V0_LIVE_TOOLS=1` 曾尝试 live 工具链但 `products.query` 因 `unit_name` 参数失败，故仍以 mock 为准。  
> **禁止**在 [`CLAIMED_VS_ACTUAL.md`](../../CLAIMED_VS_ACTUAL.md) 标「已验证」。  
> **实施计划**：[`docs/ai-agent-v0-plan.md`](../../ai-agent-v0-plan.md)

---

## 0. 运行环境（2026-06-05 复跑）

```bash
cd FHD
# Python ≥3.10；系统 python3 若为 3.9 请用 .venv（uv venv --python 3.11 && uv pip install -r requirements-base.txt）
.venv/bin/python scripts/ai_agent_v0/run_demo.py --mock-tools
# 或：AI_AGENT_V0_MOCK_TOOLS=1 .venv/bin/python scripts/ai_agent_v0/run_demo.py
```

| 条件 | 结果 |
|------|------|
| 无 `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` / `.env` | `planner_mode=fallback`（符合禁止无 Key 标 `llm`） |
| `AI_AGENT_V0_LIVE_TOOLS=1`（无 mock） | `execution_mode=live`，`success=false`（`get_products(unit_name=…)` 与当前 `ProductApplicationService` 签名不匹配） |
| `AI_AGENT_V0_MOCK_TOOLS=1` | `execution_mode=mock`，`success=true`，`demo-checklist.sh --verify` **通过** |

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
