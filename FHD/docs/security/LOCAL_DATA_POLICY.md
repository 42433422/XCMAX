# 本地数据安全策略（Wave 0 SSOT）

> v10 线内迭代 · 桌面私有化与 Web 企业版共用原则  
> 关联：[SECURITY.md](../../SECURITY.md) · [ENTERPRISE_AUDIT.md](../ENTERPRISE_AUDIT.md) · [CUSTOMER_SUPPORT.md](../customer/CUSTOMER_SUPPORT.md)

## 1. 数据分类

| 数据类 | 典型路径 | 敏感级别 |
|--------|----------|----------|
| SQLite 业务库 | `{userData}/data/xcagi.db` | 高 |
| 数据库备份 | `{userData}/backups/*.db` | 高 |
| 上传临时文件 | `uploads/temp/`、`workspace/uploads/chat/` | 中 |
| 教程样本 | `workspace/uploads/tutorial/` | 低 |
| 后端日志 | `{userData}/logs/xcagi.log` | 中（可能含 PII） |
| 更新日志 | `{userData}/logs/updater-events.jsonl` | 低 |
| 模型文件 | `{userData}/models/` | 中 |
| 诊断包 ZIP | 用户下载目录 | 中（已脱敏日志） |
| 微信/企业数据 | Mod 域 SQLite / 缓存 | 高 |

## 2. 授权

| 操作 | 要求 |
|------|------|
| 读取/导出诊断包 | **已登录会话**（`GET /api/desktop/support-bundle`） |
| 上传临时文件 | **已登录会话**（`POST/DELETE /api/upload/temp`） |
| 办公文件上传 | **已登录会话**（platform-shell office/chat upload） |
| 模型下载/安装 | **已登录会话**（desktop models API） |
| 冷启探测 | **无需登录**（`GET /api/desktop/status`） |
| GDPR 导出/擦除 | 已登录 + 账户校验（现有 `/api/gdpr/*`） |

桌面 Electron 导出诊断包时，主进程须携带浏览器会话 Cookie（见 `desktop/main.ts`）。

## 3. 脱敏

- **诊断包**：`app/security/log_redaction.py` 对日志 tail 脱敏 Bearer/JWT/Cookie/API key/邮箱/手机号后再写入 ZIP。
- **诊断包 manifest**：不含数据库正文；`databaseUrl` 使用 `redact_database_url()`。
- **企业审计 JSONL**：刻意不记录 chat body（见 ENTERPRISE_AUDIT.md）。
- **HTTP trace**：Neuro 中间件脱敏 Authorization/Cookie 头。

## 4. 清理策略

| 数据 | 策略 | 工具 |
|------|------|------|
| uploads/temp | **7 天** TTL | `scripts/desktop/purge_local_temp_data.py` |
| workspace/uploads/chat | **7 天** TTL | 同上 |
| workspace/uploads/tutorial | **7 天** TTL（教程样本） | 同上 |
| logs | RotatingFileHandler 10MB × 5 | 内置 |
| backups/*.db | 建议保留 **30 天**（手动/运维） | 文档约定 |
| 模型 cache | 按 manifest 版本；卸载时可删 `{userData}/models` | 用户操作 |
| 微信/企业缓存 | Mod 卸载或 GDPR erase | Mod + `/api/gdpr/erase` |

Wave 0 **不**在 Electron 冷启时自动 purge，避免误删；运维/用户可手动执行 purge 脚本。

## 5. 端点矩阵（Wave 0 收口）

| 端点 | 鉴权 |
|------|------|
| `GET /api/desktop/status` | 开放（冷启） |
| `GET /api/desktop/support-bundle` | 登录 |
| `POST /api/desktop/models/download` | 登录 |
| `POST /api/desktop/models/install-manifest` | 登录 |
| `POST /api/upload/temp` | 登录 |
| `DELETE /api/upload/temp/{filename}` | 登录 + `secure_filename` |
| `POST /api/platform-shell/office-sample-upload` | 登录 |
| `POST /api/platform-shell/chat-office-file-upload` | 登录 |

## 6. 变更记录

- **2026-07-05**：Wave 0 首版 — schema/registry SSOT、诊断包鉴权与日志脱敏、上传鉴权、purge CLI。
