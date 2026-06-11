# Nginx 与静态目录约定

当前仓库存在三类前端/静态目录，部署时不要混用：

- `MODstore_deploy/market/dist/`：MODstore SPA 的生产构建目录，由 `MODstore_deploy/modstore_server/app.py` 按 `/market` 与兼容 `/new` 路由服务。
- `site/`：根目录静态官网页面归档位置，例如 `about.html`、`contact.html`、`cases.html`。
- `new/`：历史线上 `/new/` 静态快照；若 Nginx 仍直接 alias 该目录，移动前需要同步更新 Nginx 配置。

推荐生产配置以 `MODstore_deploy/docs/nginx-https-example.conf` 为准，将 `/market/` 指向实际部署机上的 market 构建产物目录。

根目录的旧 Vue 工程已经归档到 `_archive/cleanup-2026-04-26/root-vue-app/`，不再作为 MODstore 主前端。
