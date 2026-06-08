# CVM nginx 原子回滚 Runbook

> **目标**：生产异常时 **15 分钟内** 切回上一版静态/market 目录，无需重新构建。  
> **前提**：部署使用 **双目录**（`current` 符号链接或 nginx `root` 切换）。

## 目录布局（推荐）

```text
/var/www/xiuci-market/
  releases/
    20260604-1200/    # 上一版
    20260604-1430/    # 当前（故障）
  current -> releases/20260604-1430
```

nginx `root` 指向 `/var/www/xiuci-market/current`（或等价路径）。

## 回滚步骤

1. SSH 登录 CVM（与 `market/.deploy-ssh.local` 相同账号）。
2. 确认上一版 release 目录存在：

```bash
ls -la /var/www/xiuci-market/releases/
readlink -f /var/www/xiuci-market/current
```

3. 原子切换（同一文件系统内 `ln -sfn` 为原子操作）：

```bash
PREV="/var/www/xiuci-market/releases/20260604-1200"   # 替换为实际上一版
ln -sfn "$PREV" /var/www/xiuci-market/current
nginx -t && nginx -s reload
```

4. 验证（与 MODstore `post_deploy_smoke` 一致）：

```bash
curl -sS -o /dev/null -w "%{http_code}\n" https://xiu-ci.com/market/download
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:9999/api/health
```

5. 在 MODstore 管理端记录回滚事件；次日日更 PR 需人工审阅根因。

## 自动化钩子

- 部署成功后：`approval_dispatcher` → `http-probe-after-deploy` + `post_deploy_smoke`（health + `/market/download`）。
- 可选 cron：`MODSTORE_POST_DEPLOY_SMOKE_CRON_ENABLED=1` + `MODSTORE_POST_DEPLOY_SMOKE_INTERVAL_MIN=30`。

## 相关

- [RELEASE_TRAIN_DEEP_CLOSURE.md](./RELEASE_TRAIN_DEEP_CLOSURE.md)
- [FHD/docs/guides/RELEASE_GAP_CLOSURE_PLAN.md](../../../FHD/docs/guides/RELEASE_GAP_CLOSURE_PLAN.md)
