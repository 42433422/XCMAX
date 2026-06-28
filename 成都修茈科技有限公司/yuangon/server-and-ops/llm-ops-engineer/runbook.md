# Runbook - LLM 运维工程师

| 字段 | 值 |
|------|----|
| 员工 ID | `llm-ops-engineer` |
| 负责区域 | `server-and-ops` |
| 应急联系 | admin |

## 日常巡检

```bash
# 查看 LLM 相关变更
git diff --name-only HEAD~5 -- \
  FHD/app/infrastructure/llm \
  MODstore_deploy/modstore_server/llm_*.py \
  MODstore_deploy/market/src/domain/llm

# 检查生产健康面是否暴露 LLM 关键状态
curl -fsS http://127.0.0.1:9999/api/health
```

## 异常处置

### provider 失败或限流

1. 识别失败 provider、错误码、最近失败次数。
2. 分类为配置错误、额度问题、限流、网络故障或模型下线。
3. 输出不含 key 明文的切换建议。
4. 通知 `security-secrets-guard` 与 `daily-orchestrator`。

### token 成本异常

1. 找出员工、模型、时间窗口。
2. 估算成本并标出异常倍数。
3. 给出降级模型或限额建议。
