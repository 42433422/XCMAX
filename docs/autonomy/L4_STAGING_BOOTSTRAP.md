# L4 Staging 环境引导步骤

> **用途**：在 CVM 119.27.178.147 上引导 staging 环境，让 autonomy watcher 真实采集 staging 信号。
> **前置**：staging 通道代码已完整，仅服务器侧未引导。

## 步骤 1：SSH 到 CVM

```bash
ssh root@119.27.178.147
```

## 步骤 2：执行 staging 引导脚本

```bash
# 脚本幂等，可重复执行
bash /opt/fhd-full/scripts/deploy/fhd-bootstrap-staging-cvm.sh
```

脚本会：
1. 从 xcagi 数据库克隆 schema 创建 xcagi_staging
2. 生成 /root/fhd-staging.env（含 7 个 Neuro Bus 开关 =1）
3. 从最新 stable tarball seed /opt/fhd-staging
4. 生成 staging manifest
5. 安装 fhd-staging.service systemd 单元
6. 配置 nginx staging vhost
7. 等待 :5101 本地健康

## 步骤 3：验证 staging 健康

```bash
curl -sf http://127.0.0.1:5101/api/health
systemctl status fhd-staging.service
```

## 步骤 4：安装 staging cron

crontab 编辑（不能复用 fhd-install-server-cron.sh，因 LOCK 硬编码）：

```bash
crontab -l > /tmp/cron.bak
echo '*/5 * * * * FHD_MANIFEST_PATH=/var/www/update/releases/staging/server/fhd-manifest.json FHD_DEPLOY_ROOT=/opt/fhd-staging FHD_SERVICE_NAME=fhd-staging.service FHD_HEALTH_PORT=5101 FHD_ENV_FILE=/root/fhd-staging.env FHD_AUTO_UPDATE_LOCK=/tmp/fhd-staging-auto-update.lock bash /opt/fhd-staging/scripts/deploy/fhd-auto-update.sh >> /var/log/fhd-staging-auto-update.log 2>&1' >> /tmp/cron.bak
crontab /tmp/cron.bak
```

## 步骤 5：复制 staging env 模板到 MODstore runtime

```bash
# 在本地 macOS
cp 成都修茈科技有限公司/MODstore_deploy/scripts/staging-autonomy.env.example \
   ~/Library/Application\ Support/XCMAX/modstore-daily.env
# 编辑填入真实 AUTONOMY_WEBHOOK_TOKEN 和 XCAGI_ADMIN_NOTIFY_USER_ID
```

## 步骤 6：验证 autonomy watcher

下次 GitHub Actions cvm-autonomy-watcher.yml 跑（每 10 分钟），观察 staging matrix 项不再 skip。

## 回滚

```bash
systemctl stop fhd-staging.service
systemctl disable fhd-staging.service
rm -rf /opt/fhd-staging /root/fhd-staging.env
crontab -l | grep -v fhd-staging | crontab -
```
