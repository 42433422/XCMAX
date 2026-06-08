# 一级密钥守卫 Runbook

## 日常巡检

### 1. 活跃会话审计

```bash
curl -s -H "Cookie: $(cat ~/.lan_cookie)" http://localhost:5000/api/lan/admin/sessions?active_only=true | jq '.data[] | {jti, ip, issued_at, expires_at}'
```

- 检查是否有异常 IP 的活跃会话
- 检查过期未清理的会话

### 2. 密钥状态检查

```bash
curl -s -H "Cookie: $(cat ~/.lan_cookie)" http://localhost:5000/api/lan/admin/keys | jq '.data[] | {id, label, is_admin, revoked_at}'
```

- 确认已吊销密钥数量
- 确认管理员密钥数量 ≤ 3

### 3. 数据库令牌配置检查

```bash
# 检查读令牌是否配置
grep FHD_DB_READ_TOKEN /path/to/.env
# 检查写令牌是否配置
grep FHD_DB_WRITE_TOKEN /path/to/.env
# 检查按 Mod 映射
grep FHD_DB_READ_TOKEN_BY_MODS /path/to/.env
```

### 4. 修茈市场 Token 有效性

- 前端 localStorage 中 `xcagi_market_access_token` 是否存在
- 调用 `/api/market/account-overview` 验证是否 200

## 异常处置

### 令牌验证 403

1. 确认后端 `.env` 中 `FHD_DB_READ_TOKEN` 是否已配置
2. 确认前端 localStorage `xcagi_db_read_token` 值是否匹配
3. 检查是否有活跃 Mod 覆盖了令牌映射
4. 临时禁用读锁：`FHD_DISABLE_DB_READ_LOCK=1`

### LAN 网关无法激活

1. 确认 `LAN_LICENSE_SECRET` 是否已设置且长度 ≥ 16
2. 确认 `LAN_ADMIN_BOOTSTRAP_KEY` 是否已设置
3. 检查 IP 是否在 `ALLOWED_CIDRS` 范围内
4. 查看审计日志：`/api/lan/admin/audit`

### 密钥轮转

1. 生成新令牌：`python -c "import secrets; print(secrets.token_urlsafe(32))"`
2. 更新 `.env` 中的 `FHD_DB_READ_TOKEN` / `FHD_DB_WRITE_TOKEN`
3. 重启后端服务
4. 通知所有用户重新输入令牌

## ESkill 动态记录

| 日期 | 触发 | 动作 | 结果 |
|------|------|------|------|
| — | — | — | — |
