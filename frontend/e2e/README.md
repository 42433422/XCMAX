# Playwright E2E（FHD 前端）

## 前置条件

1. **Node**：与 `frontend/package.json` 一致（建议 Node 20+）。
2. **浏览器**：`cd frontend && npx playwright install chromium`
3. **Vite 开发服**：默认 `http://127.0.0.1:5001`（`PLAYWRIGHT_BASE_URL` 可覆盖）。
4. **可选 API**：完整登录 / 落库用例需 FastAPI `:5000` 与种子数据（CI 见 T31）。

## 运行

```bash
cd FHD/frontend
npm ci
npx playwright install chromium
# 终端 A：FastAPI :5000（种子 admin/admin123 或 E2E_USER/E2E_PASSWORD）
# 终端 B：E2E_VITE_MOCK_API=1 npm run dev -- --port 5001 --host 127.0.0.1
export E2E_FULL_STACK=1
npm run test:e2e:p0           # smoke + critical-paths(5) + plan2026-skeleton(5)
npm run test:e2e              # 全量 e2e/
npm run test:e2e:smoke        # 仅 smoke.spec.ts
```

`playwright.config.ts` 含 `global-setup`（`e2e/global-setup.ts`）→ 写入 `e2e/.auth/user.json`。

## P0 五条（`critical-paths.spec.ts`）

| # | 链路 |
|---|------|
| 1 | 登录页 / 已登录主壳 |
| 2 | Excel 上传解析（API） |
| 3 | 打印机列表 + 打印任务（API） |
| 4 | Mod 列表 + 安装（API） |
| 5 | health + 主壳串联冒烟 |

`page.request` 不经 `page.route`；本地/CI 设 **`E2E_VITE_MOCK_API=1`** 时由 [`e2e/vite-api-mock-plugin.js`](./vite-api-mock-plugin.js) 在 Vite 层返回契约 JSON。

## 用例分层（plan-2026-06 P1-3）

| 文件 | 状态 |
|------|------|
| `smoke.spec.ts` / `login-flow.spec.ts` / `critical-paths.spec.ts` 等 | 可本地跑（需登录态 + 可选 mock） |
| `plan2026-skeleton.spec.ts` | **默认 skip** — 登录 / 产品 / 对话 / 订单 / 打印 5 链（`E2E_FULL_STACK=1` 启用；T31 CI 已收集） |

计划 5 条关键链路与 [`specs/plan-2026-06.md`](../../../specs/plan-2026-06.md) T30–T33 对齐。

- 截图说明：[`docs/evidence/e2e/README.md`](../../docs/evidence/e2e/README.md)（5 张计划链路）  
- T32 冒烟单图：[`docs/screenshots/`](../../docs/screenshots/)  
- 本地截图：`node e2e/capture-plan2026-screenshots.mjs`
