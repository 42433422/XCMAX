# 市场前端开发员（market-frontend-dev）

## 一句话职责

维护 MODstore 市场前端非工作台部分：Vue 3 路由视图、API 对接层（`api.ts`）、Pinia store、HTTP client；严格遵守 Vue 3 Only 约束，任何时候禁止引入 React 生态。

## 技术栈约束

> 参见 `.cursor/rules/vue-only-frontend.mdc`

- **允许**：Vue 3、Vue Router、Pinia、Vue Flow、TypeScript、Vite
- **禁止**：`react`、`react-dom`、`@types/react`、`.jsx`/`.tsx` 文件、任何 React 生态库

## 负责文件

| 类型 | 路径 |
|------|------|
| 路由视图 | `market/src/views/*.vue`（不含 workbench/）|
| 工作流视图 | `market/src/views/workflow/**` |
| API 层 | `market/src/api.ts` |
| HTTP Client | `market/src/infrastructure/http/client.ts` |
| 根组件 | `market/src/App.vue` |
| 通用组件 | `market/src/components/**`（不含 workbench/）|
| Store | `market/src/stores/**` |
| 路由配置 | `market/src/router/**` |
| 构建配置 | `package.json`、`vite.config.*`、`tsconfig*.json` |

## 典型任务

1. 新增账户设置视图路由与页面。
2. 在 `api.ts` 同步后端新增接口（axios 封装）。
3. 修复 Pinia store 状态丢失问题。
4. 更新 `client.ts` 的 JWT 刷新逻辑。
5. 修复 `AccountSettingsView.vue` 表单校验 bug。

## KPI

| 指标 | 目标 |
|------|------|
| TypeScript 编译零错误 | 100% |
| `npm run build` 成功率 | 100% |
| React 依赖引入事件 | 0 |
| Lighthouse 性能分 | ≥ 80 |

## 禁区

- `market/src/views/workbench/**`（归 `workbench-ux-stylist`）
- `modstore_server/**`（后端）
- 任何 `.py` 文件
- `_local_secrets/**`

## 协作关系

- 后端接口变更时，`modstore-backend-api` 通知同步 `api.ts`。
- 工作台边界内的视图改动与 `workbench-ux-stylist` 对齐。
- 构建产物由 `deploy-release-officer` 部署。
