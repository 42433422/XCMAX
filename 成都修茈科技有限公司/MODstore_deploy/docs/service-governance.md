# MODstore 单机服务治理约定

本文档记录当前单机/少量服务器部署下已经落地的服务治理能力，以及迁移到 Kubernetes/Service Mesh 前的边界。

## 网关层

`market/nginx.conf` 是容器化部署的入口反代，负责：

- `/api/auth/` 每 IP 5 r/s，突发 10。
- `/api/payment/`、`/api/wallet/` 每 IP 10 r/s，突发 20。
- 其他 `/api/`、`/v1/` 每 IP 20 r/s，突发 40。
- `/api/realtime/` 保持 WebSocket 长连接，`proxy_read_timeout 1d`。
- 其他 `/api/`、`/v1/`：`proxy_read_timeout` / `proxy_send_timeout` 设为 **3600s**（含 LLM 流式、工作台编排）；过短会在上游仍在处理时由 nginx 返回 **504**。
- 所有反代请求透传 `X-Request-Id`，便于从 Nginx、FastAPI、Java 日志串联。
- `/nginx-health` 作为容器健康检查，不依赖前端构建产物路由。

## Nginx 与 Java 支付：数据路径（易误解点）

**默认架构里，Nginx 并不直连 Java 支付服务。**

1. 浏览器 → **Nginx** → `proxy_pass` 到 **FastAPI（Python）** 的监听端口（示例为 `127.0.0.1:8765`；你方单机也可能是 `9999` 等，以 `systemctl`/实际为准）。
2. 仅当环境变量 **`PAYMENT_BACKEND=java`** 时，FastAPI 内的 **`payment_backend_proxy_middleware`**（`modstore_server/api/middleware.py`）才会用 **httpx** 把下列前缀转发到 **`JAVA_PAYMENT_SERVICE_URL`**（默认 `http://127.0.0.1:8080`，无尾斜杠）：
   - `/api/payment`、`/api/wallet`、`/api/refunds`（与 `payment_contract.PROXY_PREFIXES` 一致）。
3. **Java 健康检查**在 Spring Boot 上一般为 **`GET http://127.0.0.1:8080/actuator/health`**，不是 Nginx 里常见的 `/health`（后者若反代到 Python，对应的是 Python 自带探针，**不能**用来证明 Java 已就绪）。
4. 若 Nginx `location /api/` 的 **`proxy_pass` 端口写错**（例如 Python 已改到 `9999` 仍写 `8765`），浏览器会看到 **502**，容易误判为「Java 挂了」；应在**应用所在机**上先执行：
   - `curl -sS http://127.0.0.1:8080/actuator/health` → 期望 `status":"UP"`；
   - `curl -sS http://127.0.0.1:<Python端口>/api/payment/plans` → 期望 JSON `plans`；
   - `grep PAYMENT_BACKEND JAVA_PAYMENT_SERVICE_URL /path/to/MODstore_deploy/.env` → 期望 `PAYMENT_BACKEND=java` 且 URL 与 Java 实际监听一致。
5. **502 且响应体含** `Java 支付服务不可用` **与** `JAVA_PAYMENT_SERVICE_URL=...`：来自 Python 连不上 Java（地址/端口/防火墙/Java 未起），与 Nginx 到 Python 这一段无关。
6. **401** 在 `/api/payment/my-plan` 等：多为 JWT 无效；**Java 与 Python 的 `MODSTORE_JWT_SECRET`（及 Java `jwt.secret`）必须一致**，否则 Python 能认、Java 不认。

### 浏览器里 `/api/payment/*`、`/api/wallet/*` 全是 401

Spring 返回体常为 `{"detail":"未登录或登录已过期"}`。含义是：**到达 Java 时要么没有 `Authorization: Bearer …`，要么 JWT 未通过校验**（与 Nginx「是否直连 Java」无关：流量仍是 Nginx→Python→Java）。

按顺序自查：

1. **同一套密钥**  
   `modstore` 与 `modstore-payment` 的 systemd `EnvironmentFile` 应指向**同一份**生产 `.env`（避免一份更新了 `MODSTORE_JWT_SECRET`、另一份未更新）。改完后**两边都需重启**（至少重启 Java），用户需**重新登录**拿新 access token。

2. **反代是否丢头**  
   少数 CDN / 边缘规则会去掉 `Authorization`。在 Nginx 对 `location /api/` 显式增加：  
   `proxy_set_header Authorization $http_authorization;`  
   并对 `/api/payment/`、`/api/wallet/` 禁用不当的缓存（`proxy_no_cache 1` / `add_header Cache-Control "no-store"`），避免把 401 缓存给别的客户端。

3. **看 Java 日志**  
   部署带 `JwtAuthenticationFilter` 的告警日志后，拒绝原因会打在 `JWT rejected for …` 一行（过期、签名错、缺 `type=access` 等）。

4. **WebSocket**  
   `/api/realtime/ws?token=…` 由 **Python** 校验，与 Java 无关；若仅 WS 失败而 HTTP 正常，查 Nginx `Upgrade`/`Connection` 与超时，而不是 Java JWT。

## FastAPI 网关层

FastAPI 已安装以下治理能力：

- `X-Request-Id` 中间件：若入口未传入，则生成新的 request id，并写回响应头。
- HTTP 指标：`modstore_http_requests_total`、`modstore_http_request_duration_seconds`。
- 支付代理指标：`modstore_payment_proxy_requests_total`、`modstore_payment_proxy_duration_seconds`。
- Java 支付代理超时由环境变量控制：
  - `PAYMENT_PROXY_CONNECT_TIMEOUT_SECONDS`，默认 `5`。
  - `PAYMENT_PROXY_READ_TIMEOUT_SECONDS`，默认 `30`。

当 `PAYMENT_BACKEND=java` 时，只有 `payment_contract.PROXY_PREFIXES` 中定义的路径会被代理到 Java，其余业务仍由 Python 服务处理。

## Java 支付层

Java 支付服务继续使用 Spring Boot Actuator/Micrometer 暴露 JVM、HTTP、Hikari 连接池指标，并补充业务指标：

- `modstore_payment_checkout_total{channel,result,reason}`：下单尝试结果。
- `modstore_payment_notify_total{provider,result}`：支付回调处理结果。
- `modstore_webhook_delivery_total{event_type,result,status,attempt}`：业务 Webhook 投递结果。

这些指标已经纳入 `monitoring/prometheus/rules/modstore-alerts.yml` 的支付告警与 Grafana dashboard。

## 灰度与回滚约束

- 支付后端切换必须按 `docs/PAYMENT_GRAY_RELEASE.md` 执行预检、预发灰度、生产切换和回滚。
- 任意发布前必须至少通过 `scripts/sre_smoke_check.py` 的核心健康检查。
- 开启 `PAYMENT_BACKEND=java` 前必须确认 Java `/actuator/health` 为 UP，且 `MODSTORE_JWT_SECRET` 与 Python 一致。
- 回滚到 Python 支付时，要明确 Java 期间产生的订单仍在 PostgreSQL，不能假设 Python JSON 订单存储完整。
- LLM/RAG/工作流等长链路不应复用支付短请求超时，需要按业务链路单独配置和压测。

## 服务网格目标态

当前部署不依赖 Kubernetes，不强行引入 Istio/Linkerd。短期用 Nginx + FastAPI + Actuator 获得限流、超时、指标和灰度回滚能力。迁移到 Kubernetes 后，再评估：

- mTLS 与服务身份。
- 自动重试、熔断、连接池策略。
- 金丝雀发布和流量镜像。
- 多副本跨节点流量治理。
