# 前端源码位置

Vue/Vite 源码维护在 [`FHD/frontend`](../frontend)。从 `FHD/` 执行 `npm --prefix frontend run dev`；端口和 API 代理以启动环境与 [`vite.config.js`](../frontend/vite.config.js) 为准。

静态资源从 `frontend/public` 进入 `templates/vue-dist`；需要保留的旧页面兼容资源也在该维护源中。`XCAGI/package.json` 的测试和检查命令委派到这里。

历史重复目录已归档，恢复位置见根 [`ARCHIVE_POINTER.md`](../../ARCHIVE_POINTER.md)。
