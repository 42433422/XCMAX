# XCAGI 可观测性告警 Runbook

与 `k8s/monitoring/prometheus/alert_rules.yml`（12 条）及 Grafana 四块仪表盘配套。  
Alertmanager 路由见 `k8s/monitoring/alertmanager/alertmanager.yml`。

## 通用步骤

1. 打开 Grafana 对应仪表盘（注解 `dashboard` 字段或下表链接）。
2. 确认是否为误报（部署窗口、压测、依赖维护）。
3. 按严重级别升级：`critical` → on-call + 事件频道；`warning` → 值班群。
4. 记录 incident ID，事后更新本 runbook（若步骤过时）。

| 告警 | 严重度 | 团队 | 首查动作 |
|------|--------|------|----------|
| HighErrorRate | critical | backend | Grafana API 概览 → 5xx 按路由分布；查最近部署与 DB 连接 |
| HighLatencyP95 | warning | backend | 慢端点 TopN；Redis/DB 延迟；是否 Mod 冷启动 |
| HighLatencyP99 | critical | backend | 同 P95，优先扩容或限流；查 NeuroBus 队列积压 |
| ModLoadFailure | warning | platform | Mod manifest / sandbox 日志；`edition=full` 注册表 |
| MissingSQLiteCopy | critical | platform | `get_mod_dal().healthcheck()`；桌面 data/ 目录权限 |
| CircuitBreakerOpen | warning | platform | 下游域名健康；恢复后观察 half-open |
| NeuroBusDrops | warning | platform | 事件丢弃率；worker 数与 Redis Streams lag |
| ServiceDown | critical | sre | Pod/进程存活；`curl /api/health`；K8s events |
| HighMemoryUsage | warning | sre | 内存泄漏或缓存膨胀；HPA / 重启策略 |
| HighCPUUsage | warning | sre | 热点路由；k6 压测是否并行运行 |
| DiskSpaceLow | critical | sre | 清理日志/上传；扩容 PVC |
| PodCrashLooping | critical | sre | `kubectl logs --previous`；迁移/配置错误 |
| AIRequestFailures | warning | ai | LLM 供应商状态；API Key 与配额 |

## 压测与 CI

- PR 门禁：`performance-smoke.yml` → k6 `smoke.js`（阈值失败即红）。
- 主干/手动：`load.js` 场景 1000 / 2000 / 5000 QPS（`constant-arrival-rate`）。

## 日志

- 生产默认 NDJSON：`LOG_FORMAT=json`，入口 `app.utils.logger.setup_structured_logging`。
- 本地调试：`LOG_FORMAT=text`。
