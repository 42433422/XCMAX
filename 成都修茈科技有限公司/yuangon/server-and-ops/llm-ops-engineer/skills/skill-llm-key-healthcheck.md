# skill-llm-key-healthcheck

职责：检测各 LLM provider 的 API key 健康状态（有效性、限额、欠费、过期），输出结构化健康报告。

## 适用场景

- 日常巡检：每天一次全 provider 健康检查。
- 告警触发：`security-secrets-guard` 检测到 401/403/429 异常时升级到本技能。
- Key 轮换前：评估当前 key 是否还能支撑业务，决定是否需要轮换。

## 标准流程

1. 调 `read_llm_env_config` 拉取所有已配置 provider 的 key 列表（脱敏后）。
2. 调 `list_configured_providers` 列出 provider 列表与对应模型清单。
3. 对每个 provider 调 `test_llm_key_health`：
   - 用最小 prompt（如 "ping"）发一次请求。
   - 解析返回：`status=valid|invalid|rate_limited|insufficient_quota|expired`。
   - 记录 `remaining_quota`、`last_ok_at`、`error_code`。
4. 失效/限额/欠费立即上报：
   - 触发事件 `employee.task.escalate:security-secrets-guard`。
   - 同步通知 `daily-orchestrator` 暂停该 provider 的路由。
5. 输出结构化报告：

```json
{
  "status": "ok|warn|fail",
  "summary": "...",
  "items": [
    {
      "provider": "deepseek",
      "key_id": "sk-***abcd",
      "status": "valid",
      "remaining_quota": 1000000,
      "last_ok_at": "2026-06-28T11:00:00Z"
    }
  ],
  "warnings": ["..."],
  "error": null,
  "meta": {"checked_at": "...", "checked_by": "llm-ops-engineer"}
}
```

## 禁止事项

- 直接修改 `.env` 中的 key 明文（必须经 admin 审批 + `security-secrets-guard` 协作）。
- 在输出中明文输出完整 key 字符串，必须脱敏为 `sk-***xxxx` 格式。
- 用历史缓存数据代替实时探测结果。

## 输出契约

- summary：整体健康结论。
- evidence：每个 provider 的实测响应码、剩余配额、最后成功时间。
- risks：限额临近、欠费风险、key 过期风险。
- next_actions：是否需要轮换、是否需要切备选 provider、是否需要 admin 介入。
- requires_human：key 轮换必须人工确认。
