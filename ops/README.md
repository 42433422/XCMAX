# XCMAX 生产运维手册（单 CVM 版）

> 真相源：本目录 `ops/` 是生产运维工具的 SSOT。改这里 → 服务器上重跑 `install.sh`。
> 设计原则：**告警不依赖被监控的系统**（SMTP 直发 + GitHub 外部拨测），
> **正道比热补快**（发布链全自动），**一切异常必须自己找上门**（而非手动 SSH 巡检）。

## 0. 服务器地图（119.27.178.147，腾讯云 CVM）

| 服务 | systemd 单元 | 端口 | 代码位置 | 配置 |
|---|---|---|---|---|
| FHD 后端 | `fhd-full` | 5100 | `/opt/fhd-full` | `/root/fhd-full.env` |
| FHD 沙箱(stub) | `fhd-sandbox` | 5099 | — | 不监控 |
| MODstore API | `modstore` | 9999 | `/root/XCMAX/成都修茈科技有限公司/MODstore_deploy` | 同目录 `.env` |
| MODstore 调度器 | `modstore-scheduler` | 9990 | 同上 | 同上 |
| 支付(Java) | （或容器） | 8080 | 同目录 `java_payment_service` | — |
| Nginx | `nginx` | 80/443 | `/etc/nginx` | 公网 `xiu-ci.com` |
| 仓库 checkout | — | — | `/root/XCMAX`（git） | 官网静态/更新脚本来源 |
| 发布物落点 | — | — | `/var/www/update/releases/stable/server/` | manifest + tarball |

运维工具装在 `/usr/local/xcmax-ops`，配置 `/etc/xcmax-ops.env`，
状态 `/var/lib/xcmax-ops`，日志 `/var/log/xcmax-ops`，备份 `/var/backups/xcmax`。

## 1. 安装 / 更新（服务器上一条命令）

```bash
cd /root/XCMAX && git pull && bash ops/install.sh
```

装完自动获得（`/etc/cron.d/xcmax-ops`）：

| 任务 | 频率 | 干什么 |
|---|---|---|
| 哨兵 `xcmax_monitor.py` | 每 5 分钟 | 12 类检查，异常状态迁移时发邮件（去抖，持续故障 24h 重提） |
| 夜备 `xcmax_backup.sh` | 每天 03:30(北京) | PG dump + SQLite 快照 + 配置包，本地 7 日轮转 + 可选 COS |
| 漂移 `xcmax_drift_check.sh` | 每天 06:50(北京) | 生产树 vs 正道基线 → 热补清单告警 |
| 发布链 `fhd-auto-update.sh` | 每 5 分钟 | 消费 CI 推来的 manifest（sha256→备份→同步→健康门→失败自动回滚） |

自检失败最常见原因是 SMTP：跑 `python3 /usr/local/xcmax-ops/lib/notify.py --self-test`，
它默认回落读 MODstore `.env` 的 `MODSTORE_SMTP_*`；收不到邮件就在 `/etc/xcmax-ops.env`
里显式配 `OPS_SMTP_*`。

## 2. 告警目录与处置

邮件主题形如 `[XCMAX-CRIT] 2 项故障（1 crit）`。按检查项 id 对症：

| 检查 id | 含义 | 第一处置 |
|---|---|---|
| `svc:*` | systemd 单元挂了 | `systemctl status <unit>` → `journalctl -u <unit> -n 100` → `systemctl restart <unit>` |
| `http:fhd/modstore/scheduler` | 进程活着但接口不健康 | 看对应 journal；FHD 区分守卫墙 vs 后端：`curl -i localhost:5100/api/health` |
| `sched:runtime` | **调度 job 停摆/连败**（12 天停摆事故的自动化耳目） | `curl -s localhost:9990/api/scheduler/runtime \| python3 -m json.tool`；停摆多半是 scheduler 单元死了或 job 内部异常 |
| `journal:errors` | 错误爆发（日崩 2516 次事故的耳目） | `journalctl -u modstore-scheduler --since "1 hour ago" \| grep -B2 -A8 Traceback \| head -80` 找栈顶 |
| `journal:quota` | **LLM 配额熄火**，loop 在空转烧日志 | 平台 key 余额/额度；短期止血 `systemctl stop modstore-scheduler`（会触发 svc 告警，属预期）；充值后 start |
| `disk:root` / `mem:avail` | 水位 | `du -xh --max-depth=2 / \| sort -rh \| head`；日志/备份/docker 镜像是常客 |
| `backup:fresh` | 备份超 26h 没产出 | `tail -50 /var/log/xcmax-ops/backup.log`，手动补跑 `bash /usr/local/xcmax-ops/backup/xcmax_backup.sh` |
| `deploy:chain` | 发布链断了（manifest 与已部署 sha 长期不一致 / manifest 缺失） | `tail -50 /var/log/fhd-auto-update.log`；manifest 缺失说明 CI 的 cvm-push-release 没送达，查 GitHub Actions |
| `cert:tls` | 证书快到期 | 续签/确认自动续签任务 |
| 漂移告警 | 有人 scp 热补了生产 | 按清单把改动回灌成 PR；下次正道发布后自动归零 |

**收到 `[XCMAX-OK] N 项已恢复` 不用动**——那是好消息。

## 3. 部署正道（替代 scp 热补）

服务端交付按 [CI SSOT](../docs/CI_SSOT.md) 使用正式工作流；合入 `main` 只确认源码整合。产品 SHA 与发布控制器 SHA 分别记录，发布前取得同产品 SHA 的完整主线 CI 和有效全量安全扫描。

1. MODstore：通过正常 PR 将真实批准引用、预期生产 SHA 和 CI/扫描 run ID 固定到 `ops/releases/<产品 SHA>.json`，再从 `main` 调度 `modstore-prod-deploy.yml`。保留备份、迁移、原子切换、失败回退、异地同步和运行身份校验。
2. FHD：显式调度 `fhd-ci-cd.yml`，传入产品 SHA、扫描证据及 `push_to_cvm=true`。stable 上传使用 `FHD_PUSH_APPLY_NOW=0`；之后通过 `fhd-deploy.yml` 的 production environment 与原批准账本执行 `apply-latest`，并绑定 `action_id=release:<产品 SHA>`。
3. 上线后核对制品 manifest、API、调度器和管理台身份，完成实际业务读路径及至少 15 分钟观察。服务器发布与桌面渠道保留各自的正式验收和版本身份。

## 4. 备份与恢复演练

产物：`/var/backups/xcmax/daily/<YYYYMMDD>/`（另有 weekly×4、monthly×6）。

发布前只读检查使用 `corp-host-maintenance-preflight.yml`，归档解析复用 [PostgreSQL pg_restore](https://www.postgresql.org/docs/current/app-pgrestore.html)（[PostgreSQL License](https://www.postgresql.org/about/licence/)）。沿用已配置且已安装的客户端，容器执行锁定 immutable image ID，并记录实际版本；标准 PGDATA 声明卷仅可由精确的只读有界 tmpfs 覆盖，保留无网络、无宿主挂载、无数据库连接和资源限制。payment 专用 reader 未配置、宿主明确不支持且归档格式为 `1.15` 时，可由已核验为 PostgreSQL 16 或更新版本的通用 reader 离线执行固定 `--list`；专用配置无效不能被回退覆盖，导出端镜像与 server-major 政策不变。五项清单、哈希、归档读取和清理均成功，才确认归档完整且可读；这不等于实际数据库恢复演练或 RPO/RTO 测量。

**恢复 FHD PostgreSQL**（先停写入方）：
```bash
systemctl stop fhd-full
# DATABASE_URL 从 /root/fhd-full.env 取，去掉 +psycopg 后缀
pg_restore --clean --if-exists -d "$DATABASE_URL" /var/backups/xcmax/daily/<日期>/fhd_pg.dump
systemctl start fhd-full && curl -fsS localhost:5100/api/health
```

**恢复 MODstore SQLite**：
```bash
systemctl stop modstore modstore-scheduler
gunzip -c /var/backups/xcmax/daily/<日期>/modstore_sqlite.db.gz \
  > /root/XCMAX/成都修茈科技有限公司/MODstore_deploy/modstore.db
systemctl start modstore modstore-scheduler
```

**恢复配置**：`tar -xzf configs.tar.gz -C /`（内含 fhd-full.env、MODstore .env、nginx、systemd 单元、crontab 快照）。

**季度演练**（放日历里）：挑最近一份 `fhd_pg.dump`，`pg_restore --list` 能列目录 +
随机抽一表 `pg_restore -t <table> | head`，10 分钟完事。备份没验证过恢复 = 没有备份。

## 5. 剩余手动步骤（一次性，共约 10 分钟）

1. **SSH 加固**（Mac 上）：`bash ops/harden_ssh.sh` —— 换密钥、关密码登录（root 密码 `123` 是全仓最大单点风险）。失联兜底 = 腾讯云控制台 VNC。
2. **腾讯云 CBS 快照策略**（控制台 2 分钟）：云硬盘 → 定期快照策略 → 每日 04:00、保留 7 份、绑定系统盘。这是整机级最后防线，与逻辑备份互补。
3. **COS 异地备份**（强烈建议）：控制台建私有读写桶 → 服务器 `pip3 install coscmd && coscmd config`（子账号密钥，只授该桶）→ `/etc/xcmax-ops.env` 填 `OPS_COS_BUCKET=` → 次日看 `[XCMAX]` 邮件确认。
4. **（可选）UptimeRobot**：仓库自带 GitHub Actions 外部拨测（`ops-uptime.yml`，故障开 issue → GitHub 邮件通知）。想要短信/电话级通知再加 UptimeRobot 监控 `https://xiu-ci.com/fhd-api/api/health`。

## 6. 卸载

```bash
rm -f /etc/cron.d/xcmax-ops /etc/logrotate.d/xcmax-ops
rm -rf /usr/local/xcmax-ops
# 数据（备份/状态/日志）按需保留：/var/backups/xcmax /var/lib/xcmax-ops /var/log/xcmax-ops
```

## 7. 设计取舍备忘

- **为什么不是 Prometheus/Grafana**：单机单人运营，拉起监控栈自己也要被运维；
  哨兵是无守护依赖的 cron + stdlib python，坏不了的东西才配当耳目。规模到多机再升级。
- **为什么删了 k8s/helm/argo**：从未指向任何真实集群，几千行纯维护负担 +
  「有部署系统」的错觉。git 历史里都在（本次 PR 前的 HEAD），真上集群时再取回。
- **告警为什么走 QQ SMTP + GitHub issue 双通道**：都不依赖 FHD/MODstore 自身；
  服务器整机失联时，站外的 `ops-uptime.yml` 仍会叫。
