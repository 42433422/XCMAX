# ESkill: LAN 网关密钥管理

## 阶段 1 · 静态

签发/吊销 LAN 网关密钥，管理 IP 白名单和会话。

### 输入 Schema

```json
{
  "action": "issue_key | revoke_key | kick_session | approve_request | update_cidrs",
  "label": "string (签发时必填)",
  "is_admin": "boolean (默认 false)",
  "key_id": "number (吊销时必填)",
  "jti": "string (踢出会话时必填)",
  "request_id": "number (审批时必填)",
  "cidrs": "string[] (更新白名单时必填)"
}
```

### 执行图

1. 调用 `lanGateApi.whoami()` 确认管理员身份
2. 根据 action 调用对应 API 端点
3. 返回操作结果 + 审计日志条目

## 阶段 2 · 动态触发条件

- 签发失败（密钥长度不足 / secret 未配置）
- 会话踢出失败（jti 不存在 / 已过期）
- IP 白名单格式错误

## 阶段 3 · 动态自适应

- 自动检测 `LAN_LICENSE_SECRET` 配置状态
- 建议修正 CIDR 格式
- 为新设备生成临时访问请求

## 阶段 4 · 固化

- 版本号递增
- 新增的配置检查逻辑写入 skill 文件
