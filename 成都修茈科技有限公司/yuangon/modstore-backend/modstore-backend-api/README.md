# MODstore 后端 API 员（modstore-backend-api）

## 一句话职责

维护 MODstore 平台全部 Flask 蓝图 API，包含工作台（Workbench）、市场目录（Market Catalog）、工作流（Workflow NL Graph）、LLM 代理与 WebSocket 实时通道；是平台后端的核心守护者。

## 负责文件

| 文件 | 说明 |
|------|------|
| `workbench_api.py` | 工作台 API |
| `market_api.py` | 市场 API |
| `market_catalog_api.py` | 目录 API |
| `script_workflow_api.py` | 脚本工作流 API |
| `realtime_ws.py` | WebSocket 实时通道 |
| `llm_api.py` / `llm_chat_proxy.py` / `llm_catalog.py` | LLM 接口层 |
| `workflow_nl_graph.py` | 自然语言工作流图 |
| `api/**` | API 工厂、中间件、XSS 过滤 |
| `eventing/**` | 事件订阅 |
| `models.py` | 数据模型 |

## 典型任务

1. 新增 REST 接口（如 `/api/workbench/v2/action`）。
2. 修复 LLM 代理超时或 token 超限问题。
3. 更新 WebSocket 心跳逻辑。
4. 添加中间件（认证、限流）。
5. 修复 `workflow_nl_graph.py` 自然语言解析 bug。

## KPI

| 指标 | 目标 |
|------|------|
| API 可用率 | ≥ 99.9% |
| P99 响应时间 | < 500ms（非 LLM） |
| 测试覆盖率 | ≥ 80% |
| 上线后 P0 事故数 | 0 |

## 禁区

- `MODstore_deploy/market/src/**`（前端归 modstore-frontend）
- `payment_*.py`（归 payment-billing-reconciler）
- `employee_*.py`（归 employee-pack-curator）
- `_local_secrets/**`

## 协作关系

- API 变更通知 `market-frontend-dev` 同步更新 `api.ts`。
- 测试由 `test-qa-runner` 覆盖，失败由 `log-monitor-incident` 告警。

## 工作流执行引擎（职责边界）

- **平台运行时**：[`MODstore_deploy/modstore_server/workflow_engine.py`](../../../MODstore_deploy/modstore_server/workflow_engine.py) 的本仓库维护责任在本员工范围内（与 `workflow_api.py`、调度器等协同）。若增加 **结构化执行日志**（便于 `log-monitor-incident` 解析），请在 PR 说明中列出 JSON 字段，并协调监控侧更新 [`log-monitor-incident` runbook](../../server-and-ops/log-monitor-incident/runbook.md)。
- **Standalone 包**：[`vibe-coding/src/vibe_coding/workflow_engine.py`](../../../vibe-coding/src/vibe_coding/workflow_engine.py) 由 `vibe-coding-maintainer` 维护；适配器与入口对齐见 `skill-adapter-compat-check`。
