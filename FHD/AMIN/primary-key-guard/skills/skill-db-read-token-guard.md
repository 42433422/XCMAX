# ESkill: 数据库读令牌守卫

## 阶段 1 · 静态

管理 `X-FHD-Db-Read-Token` / `FHD_DB_READ_TOKEN` 的配置、验证和宽限窗口。

### 输入 Schema

```json
{
  "action": "check_status | rotate | configure_mod_mapping | disable_lock",
  "new_token": "string (轮转时必填)",
  "mod_id": "string (按 Mod 配置时必填)",
  "mod_token": "string (按 Mod 配置时必填)"
}
```

### 执行图

1. 读取后端 `db_token.py` 中 `effective_db_read_token()` 的当前状态
2. 检查前端 `dbTokenHeaders.ts` 中的 URL 匹配规则是否与后端对齐
3. 验证 localStorage `xcagi_db_read_token` 是否与后端配置匹配
4. 返回状态报告

### 受保护路径（与后端 `verify_db_read_token_header` 对齐）

- `GET /api/products/*`
- `GET /api/customers/list`
- `POST /api/sales-contract/resolve-from-text`
- `GET /api/sales-contract/template-preview`

## 阶段 2 · 动态触发条件

- 前端 403 但后端未配置读锁（误报）
- 后端配置了读锁但前端未弹出输入框
- Mod 映射令牌与全局令牌冲突

## 阶段 3 · 动态自适应

- 自动检测 `FHD_DISABLE_DB_READ_LOCK` 环境变量
- 对比前后端 URL 匹配规则差异
- 建议添加缺失的受保护路径

## 阶段 4 · 固化

- 新增的 URL 匹配规则同步到 `dbTokenHeaders.ts` 的 `READ_GUARD_PATH`
- 版本号递增
