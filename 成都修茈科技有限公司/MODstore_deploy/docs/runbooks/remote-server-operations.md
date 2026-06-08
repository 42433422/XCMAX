# 远程服务器 SRE 运维手册

本手册面向单机/少量服务器 Docker Compose 部署。目标是在远程服务器上把部署、健康检查、备份、压测、演练和回滚串成可重复流程。

## 首次准备

服务器需要具备：

- Git
- Docker Engine 与 Docker Compose plugin
- Python 3
- curl
- 可访问代码仓库的权限

推荐目录：

```bash
/root/modstore-git
```

服务器上准备环境变量：

```bash
cd /root/modstore-git/MODstore_deploy
cp .env.production.example .env
vim .env
```

必须替换所有 `CHANGE_ME`，尤其是数据库、Redis、RabbitMQ、JWT、支付签名、Grafana 密码和支付回调地址。

若 **Nginx 将 `xiu-ci.com` 的 `/api` 指到 Docker `:8765`**，而 **每日摘要 / 身份码在宿主机 systemd `:9999`** 生成，会出现两套 MODstore；对齐方式见 **[xiu-ci-single-modstore-upstream.md](./xiu-ci-single-modstore-upstream.md)**。

## 本地触发远程操作

在本机 `MODstore_deploy` 目录，推荐使用 **`scripts/unified-deploy.ps1`** 作为统一入口（`-Mode FullSync` / `RemoteGit` / `Preflight` / `Smoke` 等）；`-Mode Help` 打印用法。底层仍调用 `sync-modstore-to-server.ps1` 与 `remote-sre.ps1`。

也可直接运行：

```powershell
.\scripts\remote-sre.ps1 `
  -Action preflight `
  -SshTarget root@your-server `
  -RemoteRepo /root/modstore-git
```

也可以通过环境变量减少参数：

```powershell
$env:DEPLOY_SSH = "root@your-server"
$env:DEPLOY_REMOTE_REPO = "/root/modstore-git"
$env:DEPLOY_GIT_BRANCH = "main"
```

从本机到服务器的多种推送方式（Git+Compose、tar 全量同步、仅 market）的整理说明见：**[local-to-remote-push-flow.md](./local-to-remote-push-flow.md)**。

## 支持动作


| Action          | 作用                                                                   |
| --------------- | -------------------------------------------------------------------- |
| `preflight`     | 检查远程命令、目录、`.env`、Compose 配置、磁盘和容器状态                                  |
| `smoke`         | 远程执行 `scripts/sre_smoke_check.py`                                    |
| `backup`        | 远程执行 `scripts/backup_modstore.py`                                    |
| `deploy`        | `git fetch/reset`、备份、`docker compose --profile app up -d --build`、冒烟 |
| `loadtest`      | 运行 Compose `loadtest` profile 的 k6 冒烟/阶梯压测                           |
| `chaos-dry-run` | 打印混沌演练命令，不实际停止服务                                                     |
| `rollback`      | 回滚到指定 Git ref，重建应用栈并冒烟                                               |


## 日常发布

```powershell
.\scripts\remote-sre.ps1 -Action deploy -SshTarget root@your-server -RemoteRepo /root/modstore-git -Branch main
```

发布动作会在远端执行：

1. `preflight`
2. `git fetch origin <branch>`
3. `git reset --hard origin/<branch>`
4. `python scripts/backup_modstore.py`
5. `docker compose --profile app up -d --build`
6. `python scripts/sre_smoke_check.py ...`

若使用 `scripts/sync-modstore-to-server.ps1` 将代码解压到 `$REMOTE_BASE/MODstore_deploy`（默认 `$REMOTE_BASE=/root/modstore-git`），请保证 `**modstore.service` 的 `WorkingDirectory` / `ExecStart` 指向同一棵树**，否则会出现「同步成功但进程仍跑旧目录/旧 venv」。在服务器上以 root 执行 `MODstore_deploy/scripts/align_modstore_systemd_to_deploy.sh`（或通过同步脚本加 `-AlignSystemd`）写入 systemd drop-in 对齐路径。

## 后台任务（workflow_scheduler）

FastAPI 进程仅在环境变量 `**MODSTORE_RUN_BACKGROUND_JOBS=1`** 时启动 outbox worker、订阅续费调度与 `**workflow_scheduler`**（含每日运营摘要邮件 `daily_ops_digest_email`、工作流 DB cron、收件轮询等）。多 worker / 多 API 实例时**禁止**在对外 API 上打开该开关（会重复执行）；应使用**单独的单 worker 进程**跑后台任务。

### Docker Compose（本手册默认路径）

`[docker-compose.yml](../../docker-compose.yml)` 已定义 `**scheduler`** 服务（`MODSTORE_RUN_BACKGROUND_JOBS=1`，`127.0.0.1:9990`，`--workers 1`），与 `api` 共用 `modstore_data` 卷并依赖 **RabbitMQ**（`MODSTORE_BUS=rabbitmq`）。

- 发布命令 `docker compose --profile app up -d --build` 会拉起 `scheduler`；**不要**只 `up api market` 而漏掉 `scheduler`。
- 验证：`docker compose --profile app ps --status running` 列表中应包含服务名 `scheduler`。
- 日志：`docker compose --profile app logs scheduler --tail=100`；正常时不应长期只有 API 日志里的 `Background jobs SKIPPED` 而无 scheduler 进程。
- `scripts/remote_sre_ops.sh` 的 `smoke` / `deploy` 会检查 `scheduler` 处于 **running**，缺失则失败（避免 silently 无定时任务）。

### systemd（宿主机直接跑 uvicorn，无 Compose 后台容器）

1. **API 单元**（`modstore.service`）保持 `**MODSTORE_RUN_BACKGROUND_JOBS=0`**。仓库示例：`[systemd/modstore.service.example](../../systemd/modstore.service.example)`。
2. **调度单元**：复制或生成 `[systemd/modstore-scheduler.service.example](../../systemd/modstore-scheduler.service.example)` 为 `/etc/systemd/system/modstore-scheduler.service`，将路径改为服务器上的 `MODstore_deploy` 目录；或执行：
  ```bash
   sudo INSTALL_MODSTORE_SCHEDULER=1 MODSTORE_DEPLOY_DIR=/root/modstore-git/MODstore_deploy \
     bash MODstore_deploy/scripts/align_modstore_systemd_to_deploy.sh --with-scheduler
  ```
   该脚本会为 `modstore` 写入 drop-in（含 `MODSTORE_RUN_BACKGROUND_JOBS=0`），并安装、enable、`restart` `**modstore-scheduler**`。
3. 验证：`systemctl is-active modstore-scheduler`；`journalctl -u modstore-scheduler -f`。

### 每日摘要与其它环境变量

共享的 `[MODstore_deploy/.env](../../.env.example)` 由 API 与 scheduler 同时加载（Compose 中两者还从 compose `environment` 注入关键项）。摘要收件人与时间等见 `**.env.example` 中 `MODSTORE_DAILY_DIGEST_***`；生产建议显式设置 `MODSTORE_DAILY_DIGEST_EMAIL`。不必在 `.env` 里把 `MODSTORE_RUN_BACKGROUND_JOBS` 设为 `1` 给 API 用；Compose 已在 `**scheduler**` 服务中固化为 `1`。

调度进程启动后，可用管理端 `**email_admin**` 中与 `daily_ops_digest_email` 等效的手动触发接口验证 SMTP（见 `email_admin_api` 文档字符串）。

## 冒烟检查

远端 `smoke` 除 HTTP 探测外，还会确认 Docker Compose `**scheduler` 服务处于 running**，避免静默丢失后台定时任务。

默认检查本机端口：

```powershell
.\scripts\remote-sre.ps1 -Action smoke -SshTarget root@your-server -RemoteRepo /root/modstore-git
```

如服务器端口不同：

```powershell
.\scripts\remote-sre.ps1 `
  -Action smoke `
  -SshTarget root@your-server `
  -RemoteRepo /root/modstore-git `
  -ApiUrl http://127.0.0.1:9999 `
  -MarketUrl http://127.0.0.1:4173 `
  -PaymentUrl http://127.0.0.1:8080 `
  -PrometheusUrl http://127.0.0.1:9090
```

## 备份

```powershell
.\scripts\remote-sre.ps1 -Action backup -SshTarget root@your-server -RemoteRepo /root/modstore-git
```

备份落在远端：

```bash
/root/modstore-git/MODstore_deploy/backups/<timestamp>/
```

建议再通过对象存储、rsync 或云盘快照把备份复制到服务器外部。

## 压测

轻量冒烟：

```powershell
.\scripts\remote-sre.ps1 -Action loadtest -SshTarget root@your-server -RemoteRepo /root/modstore-git
```

阶梯压测：

```powershell
.\scripts\remote-sre.ps1 -Action loadtest -SshTarget root@your-server -RemoteRepo /root/modstore-git -K6Stage step
```

压测前后打开 Grafana `MODstore Overview`，记录 FastAPI p95、支付代理 p95、Java heap、Hikari 连接池和告警。

公开基线表与历史 k6 摘要（提交到仓库的单一事实来源）：`[../perf-benchmark-public.md](../perf-benchmark-public.md)`。

## 混沌演练 dry-run

```powershell
.\scripts\remote-sre.ps1 `
  -Action chaos-dry-run `
  -SshTarget root@your-server `
  -RemoteRepo /root/modstore-git `
  -ChaosScenario payment-restart
```

该动作只打印命令，不会真正重启或停止服务。真实演练仍需登录预发服务器后按 `chaos/README.md` 手动带 `--confirm` 执行。

## 回滚

回滚必须明确 Git ref，例如上一个提交、tag 或稳定分支：

```powershell
.\scripts\remote-sre.ps1 `
  -Action rollback `
  -SshTarget root@your-server `
  -RemoteRepo /root/modstore-git `
  -RollbackRef HEAD~1
```

回滚动作会先备份当前状态，再重建 Compose 应用栈并冒烟。支付相关回滚还必须参考 `docs/PAYMENT_GRAY_RELEASE.md`，避免订单数据源不一致。

## 端口与 Nginx

Compose 默认端口：

- Market: `4173`
- FastAPI: `8765`
- Java payment: `8080`
- Prometheus: `9090`
- Grafana: `3000`
- RabbitMQ 管理台: `15672`

公网建议只暴露 Nginx/HTTPS 入口，数据库、Redis、RabbitMQ、Prometheus、Grafana 只允许内网或 SSH 隧道访问。

### 504 Gateway Time-out（nginx）

若 HTML 报错页仍暴露 **nginx 版本号**（在未启用 `server_tokens off` 的旧配置上常见）且状态为 **504**，多为 **入口 nginx 等待 upstream（常见为 FastAPI `:8765`）超时**，与浏览器里「请求很慢」同时出现。

排查顺序：

1. **确认实际处理请求的是哪一层 nginx**（宿主机 `nginx -v` 常为 1.14.x；Docker 内 `market` 镜像为另一版本）。宿主机反代必须在 `**location /api/`**（及流式、WebSocket 路径）显式设置：
  - `proxy_read_timeout`、`proxy_send_timeout`（LLM / 工作台建议 **3600s**；WebSocket 见 `docs/nginx-https-example.conf` 中 `1d`）。
  - 流式接口建议 `proxy_buffering off;`，避免缓冲导致误判超时。
2. **直连 upstream**：在服务器上 `curl -m 5 -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/api/health`（或实际健康路径）。若此处已超时或连接拒绝，应先修 **uvicorn/systemd** 与端口，而不是只调 nginx。
3. **查看 upstream 日志**：`journalctl -u modstore -n 200` 或 Docker `docker compose logs api --tail=200`，确认是否 OOM、死锁或 LLM 上游过慢。

仓库内参考配置：`market/nginx.conf`（Compose 入口）、`docs/nginx-https-example.conf`（宿主机 HTTPS 反代示例）。修改后务必 `**nginx -t && systemctl reload nginx`**（或等价重载）。

启用仓库片段 [nginx-snippets-index.md](../../../docs/deploy/nginx-snippets-index.md) 后，默认 `**server_tokens off`** 且错误页为站内静态 HTML；若仍看到版本指纹，检查是否还有外层 CDN/旧版默认页或未 reload。

### Nginx 配置变更发布（备份 / 校验 / 回滚）

适用于宿主机 `nginx`（非仅 Compose 内 market 容器）：

1. **备份**：`cp -a /etc/nginx/sites-enabled/xiu-ci.com /root/backup/nginx-xiu-ci.conf.$(date +%Y%m%d%H%M)`（路径按实际站点文件调整）。
2. **合并**：将仓库内 `nginx-xiu-ci*.conf` / 片段与错误页同步到服务器对应路径（参见上文片段索引）。
3. **校验**：`sudo nginx -t`；非零退出则 **不要 reload**，恢复备份后再次检查。
4. **加载**：`sudo systemctl reload nginx`（或 `nginx -s reload`）。
5. **冒烟**：`curl -fsS http://127.0.0.1/nginx-health`（Compose market）、主站首页、`/api/health` 或等价探针、一条耗时不长的 API。
6. **回滚**：还原备份文件 → `nginx -t` → `reload`，再记录事故窗口。

**金丝雀**：单机单实例场景下 `**reload + 快速回滚`** 通常足够；仅当存在多台边缘 Nginx 或可切流量的负载均衡时，再评估按实例/权重渐进放量。

## 最小上线验收

- `preflight` 通过。
- `deploy` 成功完成。
- **Compose：`scheduler` 服务 running**（或 systemd：`modstore-scheduler` active）。
- `smoke` 通过。
- Grafana 无 P0/P1 告警。
- `backup` 产物已同步到服务器外部。
- 支付计划、钱包余额、订单查询至少手工验证一次。

