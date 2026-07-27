# XCMAX 温备机

当前温备地址：`43.138.211.142`（广州）。生产地址仍为 `119.27.178.147`，域名流量没有切换。

## 运行方式

- 生产机对 PostgreSQL 10 支付库和 PostgreSQL 16 应用库错峰强制切换并异地推送 WAL，`archive_timeout=15min`。
- 每周分别生成 PostgreSQL 10/16 物理基础备份；每天 03:30 的三库逻辑备份继续保留为跨版本回退。
- 备份用专用受限 SSH 账号写入 `incoming`；该账号不能执行远程命令，也不能读取归档。
- 温备机每 10 分钟校验并封存一次完整快照，每 15 分钟检测新快照并恢复。
- PostgreSQL 10 支付温备常驻 `127.0.0.1:15432`，PostgreSQL 16 应用温备常驻 `127.0.0.1:15433`；PostgreSQL 16 逻辑恢复实例保留在 `127.0.0.1:5432`。
- 每次生产发布按精确 Git SHA 将 FHD/MODstore 制品同步到 `runtime-releases`，温备端校验哈希后切换代码。
- 恢复先写入 `*_next`，校验成功后再切换；上一代保留为 `*_previous`。
- PostgreSQL、Redis 和无后台任务的 MODstore API 常驻，但只监听 `127.0.0.1`。
- FHD、调度器、支付服务已验证可启动，默认停机，避免双主任务和外发副作用。

正常状态下 WAL RPO 目标不超过 30 分钟；日级逻辑备份仍提供不依赖 PostgreSQL 10 的恢复路径。公网接管和 PostgreSQL promotion 保持人工确认，防止误切和双主。

## 日常检查

```bash
sudo readlink -f /srv/xcmax-dr/archive/latest
sudo cat /var/lib/xcmax-dr/last_restored_snapshot
sudo systemctl status xcmax-dr-modstore
curl -fsS http://127.0.0.1:19999/api/health
sudo /usr/local/sbin/xcmax-dr-status
sudo tail -100 /var/log/xcmax-dr/finalize.log
sudo tail -100 /var/log/xcmax-dr/restore.log
sudo tail -100 /var/log/xcmax-dr/wal-standby.log
sudo tail -100 /var/log/xcmax-dr/wal-pg16-standby.log
sudo tail -100 /var/log/xcmax-dr/release-apply.log
```

## 灾难接管

只有确认生产机已停止写入或不可恢复后才能执行，避免双主：

```bash
sudo /usr/local/sbin/xcmax-dr-promote --confirm-primary-down

curl -fsS http://127.0.0.1:15100/api/health
curl -fsS http://127.0.0.1:19999/api/health
curl -fsS http://127.0.0.1:18080/actuator/health
curl -kfsS --resolve xiu-ci.com:443:127.0.0.1 https://xiu-ci.com/__dr/health
```

四项健康检查通过后，把 DNSPod 的 `xiu-ci.com` 与 `www.xiu-ci.com` A 记录从 `119.27.178.147` 改到 `43.138.211.142`。DNS 和数据库 promotion 不自动执行。

## 公网切换演练

生产仍运行时只能用只读演练模式，Nginx 会拒绝除 GET/HEAD/OPTIONS 外的请求：

```bash
sudo /usr/local/sbin/xcmax-dr-prepare-edge --drill
curl -kfsSI --resolve xiu-ci.com:443:43.138.211.142 https://xiu-ci.com/__dr/health
```

确认 `X-XCMAX-DR: 43.138.211.142`、证书 SAN 和健康检查后，短暂切换 DNS A 记录，使用公共 DNS 和 HTTPS 再验证，然后立即回切生产地址。记录 DNS 生效、首个成功请求和回切完成时间。

接管后如需开机自启：

```bash
sudo systemctl enable xcmax-dr-fhd xcmax-dr-payment xcmax-dr-scheduler
```

## 回退

每次自动恢复后，三套上一代数据库分别保留为：

- `xcagi_previous`
- `modstore_previous`
- `payment_db_previous`

切回前必须先停止 FHD、MODstore、调度器和支付服务，并确认当前库没有新业务写入。只读归档位于 `/srv/xcmax-dr/archive`，是最终恢复来源。
