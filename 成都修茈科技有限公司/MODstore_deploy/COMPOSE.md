# MODstore Docker Compose

## 启动基础设施

```bash
docker compose up -d
```

这会启动 PostgreSQL、Redis、RabbitMQ（三者均无 `profiles`，不受 `--profile app` 影响）。默认密码仅用于本地开发，生产环境必须在 `.env` 中改掉。

## 启动完整本地栈

```bash
docker compose --profile app up --build
```

- 市场前端：http://localhost:4173/market/
- FastAPI：http://localhost:8765/api/health
- Java 支付服务：http://localhost:8080/actuator/health
- RabbitMQ 管理台：http://localhost:15672

## 关键变量

- `APT_MIRROR`：构建 **api** 镜像前换 Debian apt 源（仅影响 `Dockerfile` 里 `apt-get`）。国内示例：在 `.env` 中设置 `APT_MIRROR=https://mirrors.aliyun.com` 或 `https://mirrors.tuna.tsinghua.edu.cn`，然后 `docker compose --profile app build api` / `docker compose --profile app up --build`。不要尾斜杠。
- `PAYMENT_BACKEND=python|java`：是否由 FastAPI 代理支付/钱包请求到 Java 支付服务。
- `REDIS_URL` / `REDIS_PASSWORD`：支付幂等、防重放和缓存使用 Redis，生产环境应启用认证并限制网络。
- `MODSTORE_WEBHOOK_URL` / `MODSTORE_WEBHOOK_SECRET`：支付和退款事件的业务 Webhook 地址与签名密钥。
- `ALIPAY_NOTIFY_URL`：公网支付宝异步通知地址，路径保持 `/api/payment/notify/alipay`。

## 生产服务器闭环

生产单机部署建议从模板开始：

```bash
cp .env.production.example .env
```

替换所有 `CHANGE_ME` 后再启动：

```bash
docker compose --profile app up -d --build
```

远程服务器日常运维入口见：

- **`scripts/unified-deploy.ps1`**（推荐）：本机统一部署入口；`-Mode FullSync` 走整包 tar 同步（与 `sync-modstore-to-server.ps1` 相同），`-Mode RemoteGit` 走远端 git + compose（与 `remote-sre.ps1 -Action deploy` 相同），另有 `Preflight` / `Smoke` / `Backup` / `Rollback` 等。`-Mode Help` 查看用法。
- `scripts/ssh-install-docker-and-deploy.ps1`：本机 PowerShell 一键「SSH → 安装 Docker（若未就绪）→ `remote-sre` deploy」。需 root 或具备安装 Docker 的 sudo 权限；服务器需能访问 `https://get.docker.com`。
- `scripts/remote-sre.ps1`：本机通过 SSH 触发远程 preflight、deploy、backup、smoke、loadtest、rollback。
- `scripts/remote_sre_ops.sh`：远程实际执行脚本。
- `docs/runbooks/remote-server-operations.md`：完整操作手册。

最小上线验收：

```bash
python scripts/sre_smoke_check.py \
  --base-url http://127.0.0.1:${MODSTORE_API_PORT:-8765} \
  --market-url http://127.0.0.1:${MODSTORE_MARKET_PORT:-4173} \
  --payment-url http://127.0.0.1:${JAVA_PAYMENT_PORT:-8080} \
  --prometheus-url http://127.0.0.1:${PROMETHEUS_PORT:-9090}
```
