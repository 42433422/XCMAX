# WebSocket：Nginx（或同类反代）与应用层心跳对齐

适用于 Market 前端通过 [`market/src/realtimeClient.ts`](../../market/src/realtimeClient.ts) 连接的 **`/api/realtime/ws`**，以及服务端 [`modstore_server/realtime_ws.py`](../../modstore_server/realtime_ws.py)。

## 前端行为摘要

- 约 **50s** 发送一次 JSON：`{"type":"ping","t":...}`。
- 断线后对 **同一 handler** 做指数退避重连。
- WS URL：`ws(s)://<host>/api/realtime/ws?token=<JWT>`。

## 服务端行为摘要

- 收到 `ping` 回 `{"type":"pong","t": ...}`。
- 若 **`130s`** 内未收到任何客户端文本帧（含 ping），主动 `close`，并计入指标 `modstore_realtime_ws_events_total{event="idle_timeout"}`。

## Nginx（与 nginx-config-engineer 对齐）

需在 **WebSocket Upgrade** 的 `location` 上保证超时大于应用心跳间隔，并留有余量：

- `proxy_read_timeout` **建议 ≥ 75s**，更稳妥 **`120s` 或以上**（须大于 50s ping，并覆盖偶发调度抖动）。
- `proxy_send_timeout` 同理。
- 保留标准 Upgrade 头：`Upgrade`、`Connection`。

若超时过短，现象为：无明显错误日志、前端周期性重连、`idle_timeout` 或代理层断开同时出现。

## 排障清单

| 症状 | 检查 |
| --- | --- |
| 瞬时反复重连 | 反代是否未配置 Upgrade；`/api/realtime` 是否走错 upstream |
| 固定间隔断开 | `proxy_read_timeout` 是否与 ~50–60s 同级或更短 |
| 长时间占连无推送 | 正常；依赖 ping 维持。观察 `ping`/`idle_timeout` 指标 |

## 监控

- Prometheus：`modstore_realtime_ws_events_total`（`accepted`、`ping`、`idle_timeout`、`unregister` 等）。
- **log-monitor-incident**：对 `idle_timeout` 在单位时间内的异常暴增配置告警阈值前，应先区分「客户端退市」与「代理杀连接」——结合 access log 断开码与同一时间窗内 HTTP 延迟。
