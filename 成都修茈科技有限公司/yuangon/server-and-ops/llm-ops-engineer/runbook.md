# Runbook — LLM 运维工程师

| 字段 | 值 |
|------|----|
| 员工 ID | `llm-ops-engineer` |
| 负责区域 | `server-and-ops` |
| 最后更新 | 2026-06-28 |
| 应急联系 | admin |

---

## 日常巡检

### 巡检 1：Provider Key 健康

```bash
python -m modstore_server.scripts.llm_key_health --providers all --json
```

**预期**：每个 provider 返回 `{provider, status, remaining_quota, last_ok_at}`；失效/欠费/限额必须立即上报 `security-secrets-guard`。

### 巡检 2：Token 用量 Top-N

```bash
python -m modstore_server.scripts.llm_usage_top --since 24h --top 10 --by employee
```

**预期**：识别烧钱大户；任何员工单日 token 占比 > 30% 必须标红。

### 巡检 3：成本对比表新鲜度

```bash
python -m modstore_server.scripts.llm_price_table --check-freshness
```

**预期**：`updated_at` ≤ 7 天；超期需重新调研主流 provider 公开价格页。

### 巡检 4：本地 Ollama 可用性

```bash
curl -s http://localhost:11434/api/tags | jq '.models | length'
```

**预期**：≥ 1 个本地模型可用，作为故障切换兜底。

### 巡检 5：Provider 故障切换演练

```bash
python -m modstore_server.scripts.llm_failover_drill --provider deepseek --dry-run
```

**预期**：返回切换路径 `deepseek → tongyi → ollama-local`，且每跳都有 key 可用。

---

## 异常处置

### 异常 1：主 provider 失效

**症状**：`test_llm_key_health` 返回 `status=invalid` 或大量调用 401/429。  
**修复**：
1. 立即上报 `security-secrets-guard` + `daily-orchestrator`。
2. 出「轮换建议」报告：新 key 申请清单 + 影响员工列表 + 临时切到备选 provider 的路由变更。
3. admin 审批后由 `security-secrets-guard` 写 `.env`，本岗不直接动 key。

### 异常 2：某员工 token 异常突增

**症状**：`llm_usage_top` 显示某员工单日 token 占比 > 30%。  
**修复**：
1. 调 `query_local_token_usage` 拉该员工最近 7 天调用日志。
2. 判断是否 prompt 过长 / 死循环 / 误用强模型。
3. 出「模型路由策略」调整建议：把该员工的简单任务切到便宜模型。

### 异常 3：AGC / Provider 计费异常

**症状**：实际账单与本地计量偏差 > 5%。  
**修复**：
1. 调 `query_provider_usage` 拉对账数据。
2. 与 `dbops-engineer` 协同核对 `llm_billing` 表。
3. 出对账报告，偏差部分标注待确认。

---

## 已知未决工单

| # | 报告日 | 来源 | 现象 | 处置建议 |
|---|--------|------|------|----------|
| — | — | — | — | — |

## ESkill 动态阶段触发记录

| 日期 | 触发原因 | patch_id | 结果 | 是否固化 |
|------|----------|----------|------|----------|
| — | — | — | — | — |

---

## 应急升级路径

1. 主 + 备 provider 全挂 → 立即切 `ollama-local` 兜底 → 通知 admin 与 `daily-orchestrator` 暂停非关键 LLM 任务。
2. Key 泄露风险 → 立即联动 `security-secrets-guard` 旋转 → 本岗出影响评估报告。
3. 计费异常无法对账 → 暂停相关 provider 调用 → 上报 admin。
