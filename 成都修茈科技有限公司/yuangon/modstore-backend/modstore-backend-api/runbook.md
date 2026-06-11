# Runbook — MODstore 后端 API 员

| 字段 | 值 |
|------|----|
| 员工 ID | `modstore-backend-api` |
| 最后更新 | 2026-05-06 |
| 应急联系 | admin |

## 日常巡检

```bash
cd MODstore_deploy

# 语法检查核心文件
python -m py_compile modstore_server/workbench_api.py
python -m py_compile modstore_server/market_api.py
python -m py_compile modstore_server/llm_chat_proxy.py

# 运行单元测试
python -m pytest tests/ -q --tb=short

# API 冒烟（服务需运行）
curl -s http://localhost:8000/health
```

## 异常处置

### 异常 1：API 返回 500

1. 查看 Flask 日志（通知 `log-monitor-incident`）。
2. `python -m py_compile <file>.py` 确认无语法错误。
3. 隔离问题蓝图，逐步回滚。

### 异常 2：LLM 代理超时

1. 检查上游 LLM API Key 是否有效（联系 `security-secrets-guard`）。
2. 检查 `llm_chat_proxy.py` 超时配置是否过短。
3. 临时启用备用模型。

### 异常 3：WebSocket 连接断开

1. 检查 `realtime_ws.py` 心跳间隔配置。
2. 检查 Nginx `proxy_read_timeout` 设置（联系 `nginx-config-engineer`）。

## ESkill 动态阶段触发记录

| 日期 | 触发原因 | patch_id | 结果 | 是否固化 |
|------|----------|----------|------|----------|
| — | — | — | — | — |
