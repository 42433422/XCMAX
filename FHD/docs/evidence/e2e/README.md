# E2E P0 证据截图

| 文件 | 链路 | spec |
|------|------|------|
| `01-login.png` | 登录 | `critical-paths.spec.ts` #01 |
| `02-order.png` | 订单 | `critical-paths.spec.ts` #02 |
| `03-shipment.png` | 发货 | `critical-paths.spec.ts` #03 |
| `04-ocr.png` | OCR | `critical-paths.spec.ts` #04 |
| `05-mod.png` | Mod | `critical-paths.spec.ts` #05 |

生成：`E2E_FULL_STACK=1 npm run test:e2e:p0`（见 [`frontend/e2e/README.md`](../../frontend/e2e/README.md)）。

CI artifact：`playwright-report-*`（14 天保留）。
