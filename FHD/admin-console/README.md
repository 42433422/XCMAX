# XCMAX 管理端（admin-console）

平台运维台独立前端，与 `frontend/`（企业/宿主 SPA）分离构建与发布。

| 项 | 说明 |
|----|------|
| 源码 | `admin-console/src`（运维视图、编制图、微信绑定等） |
| 共用 | `frontend/src`（布局、登录、Mod 路由、stores） |
| 开发 | `cd admin-console && npm run dev` → 默认 **:5011**，代理后端 `VITE_API_BASE` |
| 后端 | **必须网页模式**（`XCAGI_DESKTOP_MODE=0`，如 `python run.py`）；desktop 进程会拒登 admin |
| 一键 | `bash scripts/dev/start-enterprise-dev.sh` 会另起管理 API **:42422** 供本前端使用 |
| 构建 | `npm run build` → `FHD/templates/admin-vue-dist/`（Vite 配置：`frontend/adminConsole.vite.config.js`） |
| 访问 | 开发：**http://127.0.0.1:5011/admin/login**；构建产物示例：**http://127.0.0.1:5003/admin/** |

**产物分类（发版 SSOT）**：`templates/admin-vue-dist/` 与 `templates/vue-dist/` 同为 **CI/本地构建产物**，已 gitignore，发版前由 `npm run build` 生成；`.codex-artifacts/` 为 Agent 本地 smoke 验证目录，勿提交。

企业端 `frontend` 为通用 SKU，不含运维顶栏与太阳鸟默认 Mod；访问 `/xcmax-admin` → `/admin/`，`/taiyangniao-pro` → `/sunbird/`。

## 构建顺序（发版）

```bash
cd FHD/frontend && npm run build:full
cd FHD/admin-console && npm run build
```

依赖：使用 `frontend/node_modules`（admin-console 未单独安装时可先在 frontend 执行 `npm install`）。
