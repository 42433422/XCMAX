# ESkill: 修茈市场访问令牌守卫

## 阶段 1 · 静态

管理 `xcagi_market_access_token` / `LS_MARKET_ACCESS_TOKEN` 的存储和 API 鉴权。

### 输入 Schema

```json
{
  "action": "check_status | set_token | clear_token | verify_api_access",
  "token": "string (设置时必填)"
}
```

### 执行图

1. 检查 localStorage `xcagi_market_access_token` 是否存在
2. 验证令牌格式（JWT 三段式或 Bearer 前缀）
3. 调用 `/api/market/account-overview` 验证令牌有效性
4. 检查 `modstoreBridge.ts` 中的 API 路由选择逻辑
5. 返回状态报告

### API 路由选择逻辑

- 有 `VITE_MODSTORE_API_ORIGIN` → 直连修茈远程 API
- 无远程基址 → 走本地后端同源代理 `apiFetch('/api/employees/')`
- 鉴权头：`Authorization: Bearer <token>`

## 阶段 2 · 动态触发条件

- 令牌过期（JWT exp 字段）
- API 返回 401
- CORS 错误（远程 API 未配置跨域）

## 阶段 3 · 动态自适应

- 自动检测 JWT 过期时间并提前告警
- 建议切换到本地后端代理模式
- 生成 CORS 配置建议

## 阶段 4 · 固化

- 新增的 API 端点鉴权逻辑同步到 `modstoreBridge.ts`
- 版本号递增
