# XCMAX 管理端（admin-console）

平台运维台独立前端，与 `frontend/`（企业/宿主 SPA）分离构建与发布。

| 项 | 说明 |
|----|------|
| 源码 | `admin-console/src`（运维视图、编制图、微信绑定等） |
| 共用 | `frontend/src`（布局、登录、Mod 路由、stores） |
| 开发 | `cd admin-console && npm run dev` → 默认 **:5011**，代理后端 `VITE_API_BASE` |
| 后端 | **必须网页模式**（`XCAGI_DESKTOP_MODE=0`，如 `python run.py`）；desktop 进程会拒登 admin |
| 一键 | `bash scripts/dev/start-enterprise-dev.sh`：企业 `:5000/:5001` + 管理 API **:42422** + 管理 Vite **:5011** |
| 构建 | `npm run build` → `FHD/templates/admin-vue-dist/`（Vite 配置：`frontend/adminConsole.vite.config.js`） |
| 访问 | 开发：**http://127.0.0.1:5011/admin/login**；构建产物示例：**http://127.0.0.1:5003/admin/** |

## 端口 SSOT

| 进程 | 端口 | 模式 |
|------|------|------|
| 企业 API | `:5000` | desktop（`run_fastapi.py --desktop`） |
| 企业 Vite | `:5001` | `frontend/`，`VITE_API_BASE=http://127.0.0.1:5000` |
| 管理 API | `:42422` | **web**（`run.py`，`XCAGI_DESKTOP_MODE=0`） |
| 管理 Vite | `:5011` | `admin-console/`，`VITE_API_BASE=http://127.0.0.1:42422` |

管理端 Vite **禁止** 指向 desktop `:5000`（会返回 `ADMIN_DESKTOP_FORBIDDEN`）。

## 本机代理 502（P1）

现象：浏览器打开 `http://127.0.0.1:5011` → **502**，但 `curl --noproxy '*' http://127.0.0.1:5011/...` → 200。

原因：系统 / Clash 设了 `http_proxy=http://127.0.0.1:7890`，浏览器把 **localhost 也送进代理**。

修复（任选）：

1. Clash「绕过 / Bypass」加入：`localhost,127.0.0.1,::1`
2. macOS「系统设置 → 网络 → 详情 → 代理 → 忽略这些主机与域」加入同上
3. 用仓库启动器开 Cursor（带 Chromium bypass）：
   `bash FHD/scripts/launchers/start-cursor-with-proxy.sh`
4. 开发脚本已 `source ensure_dev_proxy_bypass.sh`（仅保 curl/Vite 子进程；**不替代**系统代理 bypass）

## 控制台噪音（P2）

| 日志 | 说明 |
|------|------|
| `preload-browserView.js` 加载失败 | **Cursor IDE** 内置 BrowserView 资源，仓库 `frontend/src` / `admin-console` **无引用**，可忽略 |
| `[getThemeColors] … exportedColors` | 多为 Element Plus / 扩展主题解析内部警告，业务源码无该符号；主题异常再查 |
| `net::ERR_ABORTED`（本机端口） | 与上方代理 502 同源，修好 bypass 后应消失 |

**产物分类（发版 SSOT）**：`templates/admin-vue-dist/` 与 `templates/vue-dist/` 同为 **CI/本地构建产物**，已 gitignore，发版前由 `npm run build` 生成；`.codex-artifacts/` 为 Agent 本地 smoke 验证目录，勿提交。

企业端 `frontend` 为通用 SKU，不含运维顶栏与太阳鸟默认 Mod；访问 `/xcmax-admin` → `/admin/`，`/taiyangniao-pro` → `/sunbird/`。

## 构建顺序（发版）

```bash
cd FHD/frontend && npm run build:full
cd FHD/admin-console && npm run build
```

依赖：使用 `frontend/node_modules`（admin-console 未单独安装时可先在 frontend 执行 `npm install`）。
