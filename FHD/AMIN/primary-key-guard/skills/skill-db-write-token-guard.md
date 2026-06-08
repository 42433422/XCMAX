# ESkill: 数据库写令牌守卫

## 阶段 1 · 静态

管理 `X-FHD-Db-Write-Token` / `FHD_DB_WRITE_TOKEN` 的弹窗确认和按 Mod 隔离。

### 输入 Schema

```json
{
  "action": "check_status | rotate | configure_mod_mapping",
  "new_token": "string (轮转时必填)",
  "mod_id": "string (按 Mod 配置时必填)",
  "mod_token": "string (按 Mod 配置时必填)"
}
```

### 执行图

1. 读取后端 `configured_db_write_token()` 状态
2. 检查前端 `GlobalWriteTokenPrompt.vue` 的弹窗触发逻辑
3. 验证 `xcagi_db_write_token` localStorage 键
4. 检查 `xcagi_db_tokens_by_mod` 中的 Mod 隔离映射
5. 返回状态报告

### 受保护路径（与后端 `verify_db_write_token_header` 对齐）

- `POST /api/products/update|add|delete|batch-delete`
- `POST /api/tools/execute`
- `POST /api/customers/import|batch-delete`
- `POST /api/customers`（创建）
- `PUT|PATCH|DELETE /api/customers/:id`

### 安全约束

- 写令牌**每次写入操作须弹窗确认**，不自动携带
- 确认后通过 `armNextPlannerChatDbWriteToken()` 仅对下一次请求生效
- `consumePlannerChatDbWriteTokenArm()` 在请求后立即清除

## 阶段 2 · 动态触发条件

- 写入操作 403 但弹窗未触发
- Mod 隔离映射中存在冲突令牌
- Planner/Chat 流返回 `requires_token=DB_WRITE_TOKEN`

## 阶段 3 · 动态自适应

- 自动检测 `XCAGI_PROMPT_DB_WRITE_TOKEN_EVENT` 事件是否正常派发
- 对比前后端写入路径匹配规则
- 建议添加缺失的受保护路径

## 阶段 4 · 固化

- 新增的 URL 匹配规则同步到 `dbTokenHeaders.ts` 的 `urlNeedsDbWriteToken()`
- 版本号递增
