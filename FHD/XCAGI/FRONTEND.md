# 前端源码位置

Vue/Vite 前端**唯一**维护目录为**仓库根** [`frontend/`](../frontend/)（GitHub Actions、根目录 `docker-compose.yml` 的 `frontend` 服务均使用该路径）。

- 本地开发：`cd frontend && npm run dev`（默认 Vite 端口见 `frontend/vite.config.js`，API 代理到 `127.0.0.1:5000`）。
- 一键启动：[`start-xcagi.bat`](./start-xcagi.bat) 中的 `FRONTEND_DIR` 指向 `%FHD_ROOT%\frontend`。

历史重复目录已归档至 [`.archive/xcagi-frontend-dup-2026-04/frontend`](../.archive/xcagi-frontend-dup-2026-04/frontend)。端口迁移说明见 [`docs/FRONTEND_PORT_MIGRATION.md`](../docs/FRONTEND_PORT_MIGRATION.md)。
