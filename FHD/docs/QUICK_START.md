# XCAGI v10.0 快速开始（可交付宿主）

> 约 5 分钟跑通：**独立宿主 + 装 MOD 变系统**。主入口 `XCAGI/run.py`。
> 桌面壳默认端口 `17500`，Web/源码直连默认 `5000`。

---

## 产品模型（1 分钟理解）

1. 你拿到的是 **XCAGI 宿主**（空壳 + 通用能力），不是某一家客户的成品 ERP。
2. 从 **扩展市场** 安装平台 MOD 后，这一份软件才变成「出货系统 / 涂料 ERP / …」。
3. 数据在**客户自己的机器**上，不由供应商代管。

---

## 前置条件

- **Python** 3.11+（代码使用 `str | None` 等 3.10+ 语法，3.9 无法导入）
- **Node.js** 22.12+（`FHD/desktop/package.json` 的 `engines` 要求；低于此版本 Electron 安装脚本会报 `ERR_REQUIRE_ESM`）
- **操作系统**：Windows 10/11、Linux macOS

---

## 方式 A：桌面安装包（推荐客户）

1. 运行供应商提供的 **XCAGI Setup 1.0.0.0**（generic 壳）。
2. 首次启动：若提示装 Mod 包，在 **扩展市场** 点 **一键装齐通用包**。
3. 验证：浏览器或壳内打开 → **智能对话** 可用；`GET http://127.0.0.1:17500/api/platform-shell/deliverable-status` 中 `"deliverable": true`。

详见 [security/LOCAL_DATA_POLICY.md](security/LOCAL_DATA_POLICY.md)。

---

## 方式 B：源码 / 开发机

### 1. 克隆与依赖

```bash
git clone https://github.com/42433422/XCMAX.git
cd XCMAX/FHD
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 启动（按场景选择）

**桌面交付验收（SQLite，无需 Docker/PostgreSQL）：**

```bat
start-desktop-sqlite.bat
```

或 `start-dev.bat`（默认同样走 `xcagi-backend-desktop.cmd`）。

**Web / PostgreSQL 开发：**

```bash
alembic upgrade head   # 首次需迁移
cd XCAGI
start-xcagi.bat        # 或 xcagi-backend.cmd，读取 .env 中的 DATABASE_URL
```

桌面模式默认 SQLite，可跳过 `alembic` 与 PostgreSQL。详见 [desktop_platform_parity_ssot.md](desktop_platform_parity_ssot.md)。

### 3. 验证

- 桌面（Electron 壳）：`GET http://127.0.0.1:17500/api/desktop/status` → `storageMode: local_sqlite`
- 桌面（源码直跑 `python run.py`，默认 5000）：`GET http://127.0.0.1:5000/api/desktop/status`
- 通用：打开 **http://127.0.0.1:5000/** ，API 文档 **/docs**

### 4. 前端（可选，开发）

```bash
cd frontend
npm install
npm run build:full   # 桌面/企业：含 Mod 路由与业务页
npm run dev          # 或跑 Vite dev server
```

> **必须区分构建模式**：`npm run build`（= `--mode generic`）会产出「干净通用宿主」，
> `modRouteGlob.generic.ts` / `modPhysicalViewGlob.generic.ts` 都是空对象，
> **所有 Mod 路由与业务页不会进 bundle**，界面表现为「没有找到这个页面」和空壳页。
> 桌面/企业开发一律用 `build:full`（配 `VITE_XCAGI_PRODUCT_SKU=enterprise`）。

---

## 方式 C：桌面壳（Electron）开发态

改完前端或桌面壳后，在本机跑真实 Electron 窗口。与方式 B 的区别：
后端由 Electron 主进程拉起（含迁移与健康检查），前端用 `templates/vue-dist` 产物供后端挂载。

### 1. 构建前端

```bash
cd FHD/frontend
VITE_XCAGI_PRODUCT_SKU=enterprise VITE_XCAGI_EDITION=full npm run build:full
```

产物落在 `FHD/templates/vue-dist/`，后端从此目录提供页面。

### 2. 编译桌面壳

```bash
cd FHD/desktop
npm install     # 首次
npm run build   # tsc -> dist/
```

### 3. 启动

```bash
cd FHD/desktop
PYTHON=<python3.11+ 解释器路径> \
XCAGI_PRODUCT_SKU=enterprise \
XCAGI_DESKTOP_USER_DATA_DIR="<数据目录>" \
./node_modules/.bin/electron .
```

- **前后端 SKU 必须一致**：`XCAGI_PRODUCT_SKU=enterprise` 对应 full 前端；不一致会触发路由守卫误跳
- 默认端口 **17500**（不是 Web 端的 5000），可用 `XCAGI_DESKTOP_PORT` 覆盖
- 数据目录默认 macOS `~/Library/Application Support/XCAGI`、Windows `%APPDATA%\XCAGI`
- Electron 主进程会自动 spawn 后端：`python XCAGI/run.py --desktop --headless --port <端口> --data-dir <数据目录>`

### 4. 验证

```bash
curl --noproxy '*' http://127.0.0.1:17500/api/ping
curl --noproxy '*' http://127.0.0.1:17500/api/desktop/status   # storageMode: local_sqlite
```

后端自身启动约 2–3 秒（`routes_ready` 埋点）；窗口到可交互还要等登录时的市场权益同步。

### 本机已知问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `electron` 安装报 `ERR_REQUIRE_ESM` | Node < 22.12 | 升级 Node，或复用已有 `node_modules/electron/dist` |
| 启动后报「找不到后端程序：.../resources/backend/xcagi-backend」 | 某些 Electron 版本在 `electron .` 开发态仍报 `isPackaged=true`，走了打包后端路径 | 用 `-r` 注入 shim 把 `app.isPackaged` 还原为 `false`（与 `desktop/e2e/patch-backend.cjs` 同法） |
| 后端 `TypeError: unsupported operand type(s) for \|` | 用了系统 Python 3.9 | 用 3.11+ 解释器，经 `PYTHON=` 注入 |
| `curl 127.0.0.1` 超时 / 502 | 本机 HTTP 代理拦截回环请求 | 加 `--noproxy '*'` |
| Mod 全部消失、页面「没有找到这个页面」 | 前端用了 generic 构建 | 改用 `build:full` + `XCAGI_PRODUCT_SKU=enterprise` |

---

## 首次使用流程（界面）

generic 构建首次打开会进入 **首次设置**（`/onboarding`）：

1. 认识宿主 → 2. 宿主包就绪（一键装齐）→ 3. 行业定型（可跳过）→ 4. 智能对话  

详见 **[DELIVERABLE_PRODUCT.md](DELIVERABLE_PRODUCT.md)**。

## 装齐通用 Mod 包（命令行）

```bash
curl -X POST "http://127.0.0.1:5000/api/mod-store/bootstrap-edition-pack?edition=generic"
```

或在 UI：**首次设置** / **扩展市场** → **一键装齐通用包**。

---

## 发版 / 验收（供应商）

```powershell
powershell -File scripts/dev/adcdfg_acceptance.ps1
powershell -File scripts/dev/deliverable_smoke.ps1
powershell -File scripts/package/build-all-skus.ps1 -Version 1.0.0.0
```

完整清单：[DELIVERABLE_PRODUCT.md](DELIVERABLE_PRODUCT.md)

---

## 相关文档

- [DELIVERABLE_PRODUCT.md](DELIVERABLE_PRODUCT.md) — 交付物与验收
- [guides/PLATFORM_SHELL.md](guides/PLATFORM_SHELL.md) — 宿主壳与 edition
- [guides/ADCDFG_COMPLETION_PLAN.md](guides/ADCDFG_COMPLETION_PLAN.md) — 收口计划
- [ARCHITECTURE.md](ARCHITECTURE.md) — 架构
