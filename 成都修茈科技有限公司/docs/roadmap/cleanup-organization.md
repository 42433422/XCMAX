# Folder Cleanup Organization

目标：以 `MODstore_deploy` 为主工程，减少根目录噪音，避免构建产物和密钥进入版本库。

已执行：

- 根旧 Vue 工程归档到 `_archive/cleanup-2026-04-26/root-vue-app/`。
- 根静态官网页面移动到 `site/`。
- 本地密钥移动到 `_local_secrets/`。
- zip、xcmod、payment order JSON 等归档到 `_archive/cleanup-2026-04-26/`。
- `.gitignore` 增加 `_local_secrets/`、`_archive/`、`node_modules/`、`dist/`、`**/target/`、runtime payment orders 等规则。

保留：

- `MODstore_deploy/market` 作为 MODstore 前端源码。
- `MODstore_deploy/market/dist` 作为 FastAPI 可服务的构建目录约定。
- `new/` 作为历史 `/new/` 静态快照。
- `docs/adr` 作为正式 ADR 目录。
