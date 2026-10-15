# XCMAX 双活应用节点与数据库主备

生产地址：`119.27.178.147`，DR 地址：`43.138.211.142`。

目标形态不是双写数据库，而是：

- 两地 FHD/MODstore 应用常态在线；安全读请求本地处理；写请求与未复制服务固定回生产；两地共享单写状态；scheduler/payment 仅在生产运行；PostgreSQL 10/16 自动主备。这属于“应用双活、数据单主自动主备”，禁止无见证 promotion 与双写。

## 运行方式

- 生产机对 PostgreSQL 10/16 错峰强制切换并异地推送 WAL，`archive_timeout=15min`；每周生成物理基础备份；备份用专用受限 SSH 账号写入 `incoming`。温备机定期校验封存并恢复。单次 WAL 传输默认最多占用共享链路 15 分钟，发送端以确认游标推送新段，接收端保留安全窗口。PostgreSQL 10 支付温备常驻 `127.0.0.1:15432`，PostgreSQL 16 应用温备常驻 `127.0.0.1:15433`。每次生产发布按精确 Git SHA 同步制品并校验切换。入站目录保留当前与回退候选。active-peer 模式下 FHD/MODstore 常态在线，scheduler/payment 保持停机；生产单写仅通过受限 SSH 隧道对 DR 开放。当前运行角色与端口持久化到 `/etc/xcmax-dr-runtime-role.env`。正常状态下 WAL RPO 目标不超过 30 分钟。

## 启用活动应用节点

先在 DR 生成专用密钥（不会覆盖已有密钥）：

```bash
sudo /usr/local/sbin/xcmax-dr-prepare-active-peer --keygen \
  >/tmp/xcmax-dr-peer.pub
```

把该公钥安全传到生产后，在生产运行：

```bash
sudo /root/XCMAX/ops/dr/xcmax_dr_prepare_tunnel_primary.sh \
  --public-key-file /root/xcmax-dr-peer.pub
```

从可信的生产 SSH 连接记录 ed25519 主机指纹，再回 DR 激活：

```bash
sudo env OPS_DR_PRIMARY_HOSTKEY_SHA256='SHA256:...' \
  /usr/local/sbin/xcmax-dr-prepare-active-peer --activate
```

受限账号只能从 DR IP 转发以下生产 loopback 端口：HTTPS、FHD、
MODstore、PostgreSQL 10/16、Redis 和 payment API。它不能获得生产 shell。

active-peer Nginx 路由契约：

- `GET/HEAD/OPTIONS` 默认由 DR 本地 FHD/MODstore 处理；
- 非只读方法固定转发到生产应用；
- URI 中的 upload/download/file/asset/media/export 等文件型请求固定到生产；
- 客来来、sandbox、语音/实时和 `/api/xcmax/` 等未复制能力固定到生产。

先用定向解析做无流量验证：

```bash
curl -kfsSI --resolve xiu-ci.com:443:43.138.211.142 \
  https://xiu-ci.com/__dr/health
curl -kfsS --resolve xiu-ci.com:443:43.138.211.142 \
  https://xiu-ci.com/fhd-api/api/health
curl -kfsS --resolve xiu-ci.com:443:43.138.211.142 \
  https://xiu-ci.com/api/health
```

确认响应头 `X-XCMAX-DR-Mode: active-peer` 后，才可将 DNSPod/IGTM 配成
生产主地址、DR 备用地址并启用健康检查。

## 自动切换与防脑裂

`xcmax-dr-failover-guard.timer` 每分钟观察一次，但安装时
`OPS_DR_AUTO_FAILOVER_ENABLED=0`。只有以下证据同时成立才允许自动 promotion：

1. 生产 HTTPS 和 SSH 都不可达；
2. 所有权威 DNS 只返回 DR IP，证明外部流量入口已经隔离生产；
3. PostgreSQL 10/16 standby 都处于 recovery；
4. 云平台侧 fencing 已确认生产实例被隔离，并写入 root-only、短时有效的
   `/var/lib/xcmax-dr/provider-fence-proof.json`；
5. 上述证据连续满足三次。

fence proof 格式：

```json
{"primary_ip":"119.27.178.147","fenced":true,"expires_at":1785081600}
```

配置 DNSPod/IGTM 和云平台 fencing 后，才把 `/etc/xcmax-dr-auto-failover.env` 中的开关改为 `1`。自动回切默认禁止；旧主恢复后必须先确认其应用、scheduler 和数据库写入均被隔离，合并两端分叉数据，再重建为 standby。

腾讯云 fencing 已提供执行器 `xcmax-dr-tencent-fence`。在 DR 预装 `tccli`，
推荐给 DR CVM 绑定仅允许 `cvm:DescribeInstances`、`cvm:StopInstances`
的 CAM 实例角色，其中 `StopInstances` 的资源限定到生产实例
`ins-fsv07ypz`。root-only
`/etc/xcmax-dr-tencent-fence.env`：

```bash
OPS_DR_TENCENT_USE_CVM_ROLE=1
OPS_DR_PRIMARY_REGION=ap-chengdu
OPS_DR_PRIMARY_INSTANCE_ID=ins-fsv07ypz
OPS_DR_PRIMARY_IP=119.27.178.147
```

无法使用实例角色时可将 `OPS_DR_TENCENT_USE_CVM_ROLE=0`，再写入专用 CAM
子用户的 `TENCENTCLOUD_SECRET_ID` 和 `TENCENTCLOUD_SECRET_KEY`；不要复用
主账号密钥。

只有前述三轮外部证据已满足时 guard 才调用 fencing；确认实例状态为
`STOPPED`（主动关机还要求 `LatestOperationState=SUCCESS`）后才生成五分钟
有效 proof 并提升数据库。CAM 凭据未配置或权限
不足时保持 standby，不会降级为无 fencing 提升。

## 日常检查

```bash
sudo readlink -f /srv/xcmax-dr/archive/latest
sudo cat /var/lib/xcmax-dr/last_restored_snapshot
sudo systemctl status xcmax-dr-modstore
sudo systemctl status xcmax-dr-primary-tunnel
sudo systemctl status xcmax-dr-failover-guard.timer
curl -fsS http://127.0.0.1:19999/api/health
sudo /usr/local/sbin/xcmax-dr-status
sudo tail -100 /var/log/xcmax-dr/finalize.log
sudo tail -100 /var/log/xcmax-dr/restore.log
sudo tail -100 /var/log/xcmax-dr/wal-standby.log
sudo tail -100 /var/log/xcmax-dr/wal-pg16-standby.log
sudo tail -100 /var/log/xcmax-dr/release-apply.log
sudo tail -100 /var/log/xcmax-dr/storage-retention.log
```

## 灾难接管

手工接管只有确认生产机已停止写入或被隔离后才能执行，避免双主：

```bash
sudo /usr/local/sbin/xcmax-dr-promote --confirm-primary-down

curl -fsS http://127.0.0.1:15100/api/health
curl -fsS http://127.0.0.1:19999/api/health
curl -fsS http://127.0.0.1:18080/actuator/health
curl -kfsS --resolve xiu-ci.com:443:127.0.0.1 https://xiu-ci.com/__dr/health
```

四项健康检查通过后，把 DNSPod 的 `xiu-ci.com` 与 `www.xiu-ci.com` A
记录从 `119.27.178.147` 改到 `43.138.211.142`。若已启用 IGTM 与
provider fencing，则由 guard 使用短时 witness 自动执行数据库 promotion。

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

## 回退与切回

回切前必须先让 DR 节点停止接收写入，核对接管期间两节点产生的分叉数据并并回原主节点，按 `ops/dr/xcmax_dr_prepare_edge.sh` 将边缘恢复或隔离，再将 DR 重建为 standby。

每次自动恢复后，三套上一代数据库分别保留为：

- `xcagi_previous`
- `modstore_previous`
- `payment_db_previous`

切回前必须先停止 FHD、MODstore、调度器和支付服务，并确认当前库没有新业务写入。只读归档位于 `/srv/xcmax-dr/archive`，是最终恢复来源。
