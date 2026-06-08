# xiu-ci.com 与 systemd MODstore（:9999）统一为同一套 API

## 背景

公网 `https://xiu-ci.com` 的 `/api/`、`/v1/`、`/api/realtime/` 等若反代到 **Docker `modstore_deploy-api`（:8765）**，而每日摘要 / `digest_identity` 在 **宿主机 systemd `modstore.service`（:9999）** 上生成，则会出现两套库：邮件里的身份码在官网 `verify-admin-digest-code` 上 **400**。

健康检查应对齐：两处 `GET /api/health` 的 `hostname`、`git_sha` 应一致。

## 生产机已采用的做法（119 示例）

1. **Nginx**：在 `/etc/nginx/conf.d/xiu-ci.com.conf` 中，将所有 **MODstore** 相关的 `proxy_pass http://127.0.0.1:8765` 改为 `http://127.0.0.1:9999`（含 `location /api/`、`location /v1/`、`location ^~ /api/realtime/`、`location ~ ^/(api|modstore)/`、`location ^~ /api/xcmax/admin/daily-digests` 等）。**不要**改动仍指向 FHD/XCmax 的 `5099`、`5100` 段。
2. **`nginx -t && systemctl reload nginx`**。
3. **Docker scheduler**：若与宿主机 systemd 重复调度每日摘要，可停止 scheduler 容器，避免双写另一套库：
   `docker stop modstore_deploy-scheduler-1`  
   （长期方案可在 `docker-compose.yml` 中 `profiles` 或 `scale` 固定为 0，仅保留宿主机侧调度。）

变更前务必备份：`cp /etc/nginx/conf.d/xiu-ci.com.conf /etc/nginx/conf.d/xiu-ci.com.conf.bak.…`

## 回归

```bash
curl -sS https://xiu-ci.com/api/health
curl -sS http://127.0.0.1:9999/api/health
```

两者 JSON 应一致（至少 `hostname` / `git_sha`）。

随后在 `https://xiu-ci.com/market` 使用管理员 JWT 解锁：粘贴 **由当前环境发出的** 摘要邮件 / XCmax 页眉 6 位码，应返回 200。

## 参考

- 仓库示例（Flask 网关思路，端口按实际替换）：[`deploy/nginx-api-via-flask.conf.example`](../../../deploy/nginx-api-via-flask.conf.example)
- 远程运维总入口：[remote-server-operations.md](./remote-server-operations.md)
