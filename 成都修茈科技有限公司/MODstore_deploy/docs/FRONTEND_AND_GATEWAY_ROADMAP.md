# 前端构建与 API Gateway 治理路线图

本文是计划「Python To Java Payment Migration Plan」§阶段 4 的落地说明。优先级：先收敛前端构建事实源，再延后决定 Vue/React 与独立 API Gateway。

## 1. 当前事实源（已收敛）

| 资产 | 唯一来源 | 备注 |
| --- | --- | --- |
| 市场前端源代码 | [`MODstore_deploy/market/src`](../market/src) | Vue 3 主应用 + 少量 React 19 auth islands |
| Vite 构建配置 | [`MODstore_deploy/market/vite.config.ts`](../market/vite.config.ts) | **唯一**配置；旧的 `vite.config.js` 已删除 |
| 构建产物 | [`MODstore_deploy/market/dist`](../market/dist) | FastAPI `_MARKET_DIST` 与 `/market` `/new` 静态前缀都指向此目录 |
| 部署脚本 | `npm run build`（[`package.json`](../market/package.json)） | CI 中 `VITE_PUBLIC_BASE=/market/` |

历史上根目录还存在两份独立的 `index.html` / `dist/` / `node_modules/`，已经在当前分支批量删除（见 git status）。仓库根目录除了 `MODstore_deploy/market` 之外不再有 npm 项目。

## 2. Vue / React 决策（延后）

当前是 Vue 主应用 + React 19 auth islands（`src/react/LoginPage.tsx` 等通过 Vue 包装组件挂载）。统一技术栈要回答两个问题：

1. React islands 是否会在未来扩张到非 auth 页面？
2. 我们是否能承担把 React 路由完全迁回 Vue 的工时？

在支付迁移、覆盖率门禁、服务拆分三件事稳定之前不做技术栈替换。先要做的中间态约束：

- 新页面默认 Vue 3 + Composition API，禁止再新增 React island，除非通过书面 ADR 决定。
- 共享 UI 原子（按钮、输入、表单校验）必须用 Vue 实现；React island 只能通过 `props` 接收原子级数据，不再承担状态管理。
- 后端契约（payment、wallet、refund）的 fetch 客户端必须放在 [`market/src/application`](../market/src/application)（框架无关），React/Vue 都从该层调用。`tests/test_payment_contract.py` 已经把这一层钉死。

判定何时启动统一技术栈：

- React island 数量 ≥ 6 个，或维护成本（双 lint/type 配置漂移）超过两次 Sprint 的 30%。
- 或 Vue 组件库需要做 SSR/RSC，React islands 阻碍了升级。

## 3. API Gateway（低优先级）

支付迁移的 BFF 仍由 FastAPI `modstore_server.app:app` 承担。FastAPI 同时负责：

- 鉴权代理（`api/deps._get_current_user`）。
- `PAYMENT_BACKEND=java` 时把 `/api/payment`、`/api/wallet`、`/api/refunds` 透传给 Java（[`docs/PAYMENT_CONTRACT.md`](./PAYMENT_CONTRACT.md) §6）。
- 静态市场前端挂载（`/market`、`/new`）。

引入独立 API Gateway（如 Kong、APISIX、Traefik）需要满足以下任一前置条件，否则不引入：

- Employee/Workflow/LLM 至少两个服务已经独立进程上线，FastAPI 退化成 BFF only。
- 跨服务的速率限制 / 认证缓存 / 灰度路由策略复杂到无法在 FastAPI 中安全维护。

引入时的最小开关：

- 把 `PaymentGatewayService` 重写成对 Gateway 内部 host 的转发，而不是直接对 Java host。
- `PROXY_PREFIXES` 与 `PAYMENT_ENDPOINTS` 在 Gateway 配置中等价复制；`tests/test_payment_contract.py` 仍然是事实源。
- Gateway 的鉴权策略必须沿用现有 JWT secret（`MODSTORE_JWT_SECRET`）。

## 4. 验收

- 仓库内只有一份 Vite 配置：`MODstore_deploy/market/vite.config.ts`。
- FastAPI 的 `_MARKET_DIST` 仍然指向 `market/dist`。
- 没有新引入的根目录 `index.html` / `dist/`。
- 所有 React island 在 ADR 中登记。
- API Gateway 引入时同步更新本文件 §3 验收清单。
