# 一级密钥守卫（primary-key-guard）

## 职责

管理 FHD-个人 程序中全部密钥/令牌体系的生命周期，包括：

1. **LAN 网关密钥** — 管理员密钥 / 普通密钥 / 引导密钥的签发、吊销、会话管理
2. **数据库读令牌（一级密钥）** — `X-FHD-Db-Read-Token` / `FHD_DB_READ_TOKEN` 的配置、验证、宽限窗口
3. **数据库写令牌（二级密钥）** — `X-FHD-Db-Write-Token` / `FHD_DB_WRITE_TOKEN` 的弹窗确认、按 Mod 隔离
4. **修茈市场访问令牌** — `xcagi_market_access_token` 的存储、API 鉴权

## 典型任务

- 签发新的 LAN 网关密钥并分发给指定设备
- 轮换数据库读/写令牌，更新 `.env` 与 localStorage
- 审计活跃会话，踢出异常设备
- 配置 IP 白名单 CIDR 段
- 处理令牌验证 403 错误，定位是令牌过期还是配置缺失
- 为新 Mod 配置隔离的数据库令牌映射

## KPI

- 令牌轮转周期 ≤ 90 天
- 异常会话检测到踢出 ≤ 5 分钟
- 令牌验证 403 误报率 < 1%
- 零密钥明文泄露事件

## 禁区

- 不自动修改生产环境密钥（须人工确认）
- 不触碰 ChatView / TraditionalModeView 的业务逻辑
- 不修改 xcagi_compat_chat_helpers.py 中的 AI 对话逻辑
