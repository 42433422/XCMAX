# XCMAX 管理端（admin-console）

平台运维台独立前端，与 `frontend/`（企业/宿主 SPA）分离构建与发布。

| 项 | 说明 |
|----|------|
| 源码 | `admin-console/src`（运维视图、编制图、微信绑定等） |
| 共用 | `frontend/src`（布局、登录、Mod 路由、stores） |
| 开发 | `cd admin-console && npm run dev` → 默认 **:5011**，代理后端 `VITE_API_BASE` |
| 构建 | `npm run build` → `FHD/templates/admin-vue-dist/`（Vite 配置：`frontend/adminConsole.vite.config.js`） |
| 访问 | **http://127.0.0.1:5003/admin/**（需先构建；管理员账号） |

企业端 `frontend` 为通用 SKU，不含运维顶栏与太阳鸟默认 Mod；访问 `/xcmax-admin` → `/admin/`，`/taiyangniao-pro` → `/sunbird/`。

## 构建顺序（发版）

```bash
cd FHD/frontend && npm run build:full
cd FHD/admin-console && npm run build
```

依赖：使用 `frontend/node_modules`（admin-console 未单独安装时可先在 frontend 执行 `npm install`）。
