# Playwright E2E（P0 关键链路）

## 套件矩阵

| 套件 | 用例 | 条件 |
|------|------|------|
| `smoke.spec.ts` | 4 | 始终 |
| `critical-paths.spec.ts` | 5 | mock 或全栈 |
| `plan2026-skeleton.spec.ts` | 5 | 需 `E2E_FULL_STACK=1` |
| `login-flow.spec.ts` | 2 | SLA 登录探针 |
| `sla-perf.spec.ts` | 2 | `sla-probe.yml` |
| `desktop-shell.spec.ts` | 3 | 桌面壳契约 |

**P0 合计**：`npm run test:e2e:p0` → mock 模式 **9 passed / 5 skipped**；全栈 **14 passed**。

## 本地全栈

```bash
# 编排脚本（FastAPI :5000 + Vite :5001）
bash FHD/scripts/dev/e2e-full.sh

# 或手动
cd FHD/frontend
E2E_FULL_STACK=1 E2E_USER=admin E2E_PASSWORD=admin123 npm run test:e2e:p0
```

## node_modules 归档指针

若 `node_modules` 仅为 `ARCHIVE_POINTER.md`：

```bash
rsync -a ~/XCMAX-archives/m0-frontend-nm/ FHD/frontend/.nm-e2e/
ln -sfn .nm-e2e FHD/frontend/node_modules
```

## 证据截图

全栈 P0 通过时写入 [`docs/evidence/e2e/01–05.png`](../docs/evidence/e2e/README.md)。

## CI

仓根 [`.github/workflows/e2e.yml`](../../../.github/workflows/e2e.yml) → [`e2e-playwright-reusable.yml`](../../../.github/workflows/e2e-playwright-reusable.yml)。
