# Frontend TypeScript P1

目标：完成前端类型边界与 API 边界，不强制一次性迁移所有 `.vue` 页面。

已落地：

- `MODstore_deploy/market/tsconfig.json`
- `MODstore_deploy/market/env.d.ts`
- `MODstore_deploy/market/src/main.ts`
- `MODstore_deploy/market/src/infrastructure/http/client.ts`
- `MODstore_deploy/market/src/infrastructure/storage/tokenStore.ts`
- `MODstore_deploy/market/src/application/*Api.ts`
- `MODstore_deploy/market/src/domain/*/types.ts`
- `authPaths`、`refundStatus`、`workflowMermaid`、`workflowSandboxPresets` 的 TypeScript 版本

兼容策略：

- `src/api.js` 仍作为旧页面的兼容入口。
- `src/api.ts` 作为新 TypeScript facade。
- 大页面按风险分批改用 typed API。

验收：

```bash
cd MODstore_deploy/market
npm test
npm run typecheck
npm run build
```
