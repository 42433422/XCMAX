# Tier C 高并发验收证据

| 文件 | 场景 | 生成方式 |
|------|------|----------|
| `sustained-report.json` | SLO-TIER-C-01/02/03 | `k6 run scripts/loadtest/tier_c_sustained.js --summary-export=...` |
| `chat-streams-report.json` | SLO-TIER-C-04/05 | `k6 run -e STREAM_CONCURRENCY=200 scripts/loadtest/tier_c_chat_streams.js` |
| `celery-latency.png` | SLO-TIER-C-06 | Grafana celery 面板截图 |
| `acceptance-tier-c.yaml` | 汇总 | 手工填写指向上述文件 |

模板 `acceptance-tier-c.yaml` 记录压测日期、RPS、错误率、P95。
