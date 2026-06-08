# 门户 Flask（仓库根 `app.py`）观测与健康检查

供 **`log-monitor-incident`** / **`nginx-config-engineer`** 与值班巡检对齐字段；不包含 ModStore FastAPI 自身日志格式。

## 1. HTTP：`GET /health`

返回 JSON（**不满足上游探测时隔 HTTP 503**），顶层字段稳定便于告警：

| 字段 | 含义 |
|------|------|
| `ok` | `upstream.reachable` 且上游 HTTP 状态非 5xx |
| `service` | 固定 `portal-flask` |
| `version` | `PORTAL_VERSION`，否则 `MODSTORE_VERSION`，否则 `unknown` |
| `timestamp` | UTC ISO8601 |
| `upstream` | 对象：`url`、`reachable`、`latency_ms`、`status`、`http_status`、`detail` |

探测目标：`MODSTORE_BACKEND_URL`（默认 `http://127.0.0.1:8000`）下的 **`GET /api/health`**。超时：`PORTAL_HEALTH_UPSTREAM_TIMEOUT`（默认秒 `2`）。

## 2. 全链路探测（SLO）

单依赖 **`GET /health`** 无法证明 **`GET /api/health` 经 Flask 代理**是否正常；建议在合成监控中另行请求同源 **`GET /api/health`**（或其它低频 GET）。

## 3. 结构化日志事件（`portal.flask` / root）

单行 JSON，`logging.basicConfig` 默认启用（可用 `PORTAL_CONFIGURE_LOGGING=0` 关闭；级别 `PORTAL_LOG_LEVEL`，默认 `INFO`）。

| `event` | 何时 |
|---------|------|
| `portal_request` | 每条请求（**跳过** `/assets/`、`/uploads/`、`/styles.css`、`/main.js`），字段：`method`、`path`、`status`、`duration_ms` |
| `portal_proxy_upstream_unreachable` | 代理上游抛出 `requests.RequestException`（502 给用户），字段：`method`、`path`、`upstream_url`、`detail` |
| `portal_proxy_upstream_5xx` | 上游响应 HTTP ≥ 500 |
| `portal_config_warning` | 例如仍在使用默认 `PORTAL_SECRET_KEY` |

关联运维关键字 **`Event loop is closed`** 通常出在 **Uvicorn/asyncio** 进程日志；Flask 侧重点对齐 **`upstream unreachable`**、**`upstream_5xx`**、**`/health` 503**。

## 4. Nginx：静态工具页 `excel-to-ai.html`（可选）

该页为**纯静态**，无需 Flask `Flask-Limiter`。如需边缘限速（扫库 / 带宽），可在站点配置中为精确路径单独设 **`limit_req`** / **`limit_conn`**，例如（示意）：

```nginx
limit_req_zone $binary_remote_addr zone=portal_tools:10m rate=10r/s;

location = /excel-to-ai.html {
    limit_req zone=portal_tools burst=20 nodelay;
    # proxy_pass / alias 等与现有静态路由一致
}
```

---

后台会话：**`PORTAL_ADMIN_PASSWORD`** 启用 `/admin`、`/admin/news` 登录门（`/admin/login`）；**`PORTAL_SECRET_KEY`** / **`FLASK_SECRET_KEY`** 用于会话签名。
