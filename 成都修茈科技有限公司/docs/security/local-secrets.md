# 本地密钥与证书

清理后，本机密钥材料统一放在仓库根目录的 `_local_secrets/` 下，该目录已加入 `.gitignore`，不要提交。

当前约定：

- `_local_secrets/MODstore_deploy_keys/`：原 `MODstore_deploy/keys` 中的支付宝 PEM 文件。
- `_local_secrets/nginx_extract/`：原 `_nginx_extract` 中的 Nginx/TLS 证书与私钥材料。

生产环境应优先使用环境变量、服务器密钥管理或部署平台 Secret，不应依赖仓库内的私钥文件。

如果本地脚本仍需要文件路径，请在 `.env.local` 或私有启动脚本中显式指定，不要把真实路径写入公开配置。
