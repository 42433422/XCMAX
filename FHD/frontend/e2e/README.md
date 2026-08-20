# Playwright E2E（P0 关键链路）

## 套件矩阵

| 套件                                  | 用例 | 条件                  |
| ------------------------------------- | ---- | --------------------- |
| `smoke.spec.ts`                       | 4    | 始终                  |
| `critical-paths.spec.ts`              | 6    | mock 或全栈           |
| `plan2026-skeleton.spec.ts`           | 5    | 需 `E2E_FULL_STACK=1` |
| `login-flow.spec.ts`                  | 2    | SLA 登录探针          |
| `sla-perf.spec.ts`                    | 3    | `sla-probe.yml`       |
| `desktop-shell.spec.ts`               | 4    | 桌面壳契约            |
| `core-business.spec.ts`               | 4    | mock 或全栈           |
| `navigation.spec.ts`                  | 2    | 始终                  |
| `im-v0-two-user.spec.ts`              | 1    | 全栈                  |
| `mod-pilot-evidence.spec.ts`          | 4    | MODstore 全栈         |
| `onboarding-empty-enterprise.spec.ts` | 2    | 1 mock + 1 full-stack |
| `ai-chat-multi-turn.spec.ts`          | 1    | mock                  |
| `mod-install-uninstall.spec.ts`       | 1    | mock                  |
| `cross-device-session.spec.ts`        | 1    | mock                  |

**合计**：14 个 spec 文件 / **40 个 test case**（≥ 40 目标达成）。
P0 mock 模式 `npm run test:e2e:p0` 仍维持稳定基线（部分新场景作为 P1/P2 补充，可逐步纳入 P0 套件）。

## 新增场景（共 8 个）

| #   | 场景                             | 优先级 | 文件                                  |
| --- | -------------------------------- | ------ | ------------------------------------- |
| 1   | 库存调拨（A→B 仓数量更新）       | P0     | `core-business.spec.ts`               |
| 2   | 订单履约（pending → shipped）    | P0     | `critical-paths.spec.ts`              |
| 3   | AI 多轮对话（context 携带）      | P0     | `ai-chat-multi-turn.spec.ts`          |
| 4   | Mod 安装/卸载（installed badge） | P1     | `mod-install-uninstall.spec.ts`       |
| 5   | Onboarding 多步串接              | P1     | `onboarding-empty-enterprise.spec.ts` |
| 6   | SLA 报表 P95/P99 字段            | P1     | `sla-perf.spec.ts`                    |
| 7   | Electron IPC invoke open-modal   | P2     | `desktop-shell.spec.ts`               |
| 8   | 跨端登录态复用（cookie 注入）    | P2     | `cross-device-session.spec.ts`        |

## 本地全栈

```bash
# 编排脚本（FastAPI :5000 + Vite :5001）
bash FHD/scripts/dev/e2e-full.sh

# 或手动
cd FHD/frontend
E2E_FULL_STACK=1 E2E_USER=xcagi-enterprise-demo E2E_PASSWORD='Demo@2026' E2E_ACCOUNT_KIND=enterprise npm run test:e2e:p0
```

## 本地 mock 模式（无需后端）

```bash
cd FHD/frontend
E2E_VITE_MOCK_API=1 npm run test:e2e:p0
```

## node_modules 归档指针

若 `node_modules` 仅为 `ARCHIVE_POINTER.md`：

```bash
rsync -a ~/XCMAX-archives/m0-frontend-nm/ FHD/frontend/.nm-e2e/
ln -sfn .nm-e2e FHD/frontend/node_modules
```

## 证据截图

全栈 P0 通过时写入 [`docs/evidence/e2e/01–06.png`](../docs/evidence/e2e/README.md)。mock smoke
默认写入被忽略的 `playwright-report/evidence/`，不会覆盖正式验收证据；也可通过
`E2E_EVIDENCE_DIR` 显式指定输出目录。

## CI

仓根 [`.github/workflows/e2e.yml`](../../../.github/workflows/e2e.yml) → [`e2e-playwright-reusable.yml`](../../../.github/workflows/e2e-playwright-reusable.yml)。
