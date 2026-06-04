## M0 验收记录（2026-06-05）

| 项 | 结果 |
|----|------|
| Playwright | `npm run test:e2e:p0` → **14 passed**（约 37s，mock API，无 :5000 依赖） |
| 截图 | 本目录 `01-login-shell.png` … `05-order-print.png`（`capture-plan2026-screenshots.mjs`） |
| 登录态 | `frontend/e2e/.auth/user.json`（global-setup，不入库） |

---

# E2E 关键链路截图（M0 / T32）

与 [`specs/plan-2026-06.md`](../../../../specs/plan-2026-06.md) T30–T33 对齐的 **5 条计划链路**（`plan2026-skeleton.spec.ts`）：

| # | 场景 | 建议文件名 | 对应用例 |
|---|------|------------|----------|
| 1 | 登录后主壳 | `01-login-shell.png` | Plan 2026-06 — login |
| 2 | 产品列表 | `02-product-list.png` | Plan 2026-06 — product |
| 3 | 副窗 / 对话 | `03-assistant-float.png` | Plan 2026-06 — chat / assistant |
| 4 | 订单列表 | `04-order-list.png` | Plan 2026-06 — order |
| 5 | 订单 / 打印 | `05-order-print.png` | Plan 2026-06 — print |

**P0 契约五条**（`critical-paths.spec.ts`，CI 必跑）：登录、Excel 上传、打印 API、Mod 安装、串联冒烟 — 截图可选存入 `p0-*.png`。

---

## 前置条件

1. Vite `http://127.0.0.1:5001`（**M0 推荐** `E2E_VITE_MOCK_API=1`，无需 FastAPI）
2. 可选 FastAPI `http://127.0.0.1:5000`（全栈 / 非 mock：`admin` / `admin123` 或 `E2E_USER` / `E2E_PASSWORD`）
3. Vite `http://127.0.0.1:5001`，建议 `E2E_VITE_MOCK_API=1`（`page.request` 契约 mock，见 [`frontend/e2e/vite-api-mock-plugin.js`](../../../frontend/e2e/vite-api-mock-plugin.js)）
4. `cd FHD/frontend && npm ci && npx playwright install chromium`

---

## 一键跑 P0 + 写登录态

```bash
cd FHD/frontend
export E2E_VITE_MOCK_API=1
export E2E_FULL_STACK=1
export PLAYWRIGHT_BASE_URL=http://127.0.0.1:5001
# 终端 A：仓根或 FHD 下启动 API + 前端（示例）
#   cd FHD && uvicorn app.fastapi_app:app --port 5000 &
#   E2E_VITE_MOCK_API=1 npm run dev -- --port 5001 --host 127.0.0.1

npm run test:e2e:p0
```

`global-setup` 会生成 `frontend/e2e/.auth/user.json`（已 gitignore）。

---


## 推荐流程（P0 绿 + 五张截图）

1. **终端 A** 启动 Vite（与 CI 一致，契约 mock 可不启 :5000）：

```bash
cd FHD/frontend
export E2E_VITE_MOCK_API=1
npm run dev -- --port 5001 --host 127.0.0.1
```

2. **终端 B** 跑 P0 并写入登录态：

```bash
cd FHD/frontend
export E2E_VITE_MOCK_API=1 E2E_FULL_STACK=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5001
npm run test:e2e:p0
```

期望：**14 passed**（`critical-paths` 5 + `plan2026-skeleton` 5 + `smoke` 4）。

3. **仍在终端 B** 生成计划链路截图（复用 `e2e/.auth/user.json`）：

```bash
export PLAYWRIGHT_BASE_URL=http://127.0.0.1:5001
node e2e/capture-plan2026-screenshots.mjs
ls -la ../docs/evidence/e2e/0*.png
```

4. 将本 README 与 PNG 一并纳入 PR；`user.json` 与 `test-results/` **勿提交**。

> 若需真实 Postgres / 落库链路，在终端 A 另启 `uvicorn` :5000 并去掉 `E2E_VITE_MOCK_API`（见 CI `e2e-playwright-reusable.yml`）。

## 生成 5 张截图（本地）

### 方式 A：Playwright CLI（推荐）

在 P0 全绿后，用已登录的 storageState 逐页截图：

```bash
cd FHD/frontend
mkdir -p ../docs/evidence/e2e

node e2e/capture-plan2026-screenshots.mjs
```

脚本依赖 `e2e/.auth/user.json`（先跑过一次 `npm run test:e2e:p0` 或 `npx playwright test --global-setup` 等价的 global-setup）。

### 方式 B：CI Artifact

1. GitHub Actions → workflow **e2e** 或 **e2e (FHD)** → 成功 run  
2. 下载 `playwright-report-<run_id>`  
3. 从 `test-results/` 或 `FHD/docs/screenshots/v10-e2e-smoke-ci.png` 复制代表性 PNG 到本目录并按上表重命名  

### 方式 C：失败截图

默认 `screenshot: 'only-on-failure'`。失败时在 `frontend/test-results/` 下查找 `*.png`，**勿**将失败图当作验收证据入仓。

---

## 相关路径

| 用途 | 路径 |
|------|------|
| 用例说明 | [`frontend/e2e/README.md`](../../../frontend/e2e/README.md) |
| CI | [`.github/workflows/e2e-playwright-reusable.yml`](../../../.github/workflows/e2e-playwright-reusable.yml)、仓根 `.github/workflows/e2e.yml` |
| 冒烟单图（T32 兼容） | [`docs/screenshots/`](../../screenshots/) |
