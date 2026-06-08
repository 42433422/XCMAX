# 部署用 SSH 私钥（勿提交 Git）

将本机私钥复制到此目录（权限 `chmod 600`）：

- `id_ed25519` — OpenSSH 私钥
- 或 `424334.pem` — 腾讯云 CVM 下载的 PEM

然后执行：

```bash
cd ../
./scripts/sync-market-dist-key.sh
```

或在 `.deploy-ssh.local` 中设置 `DEPLOY_SSH_KEY=/绝对路径/私钥`。
