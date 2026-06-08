# Flask 路由功能评估与迁移清单

> **评估日期**: 2026-04-17  
> **目标**: 将所有 Flask 路由功能迁移到 XCAGI FastAPI

---

## 📊 路由功能总览（49个文件）

### 已评估功能分类

| 类别 | 文件数 | 状态 | 说明 |
|------|--------|------|------|
| XCAGI 已覆盖 | ~30 | ✅ | FastAPI 已有对应实现 |
| 需要迁移 | ~19 | ⏳ | XCAGI 缺少的功能 |

---

## ⏳ 需要迁移的功能清单（19个文件）

### 1. AI 助手兼容层 (ai_assistant_compat.py)

| 端点 | 方法 | 功能 | 优先级 |
|------|------|------|--------|
| `/health` | GET | 健康检查 | P1 |
| `/api/health` | GET | API健康检查 | P1 |
| `/api/generate` | POST | 生成文档 | **P0** |
| `/orders/next_number` | GET | 获取下一个订单号 | P1 |
| `/api/orders` | GET/DELETE | 订单列表/删除 | **P0** |
| `/api/orders/latest` | GET | 最新订单 | P1 |
| `/api/orders/search` | GET | 订单搜索 | P1 |

### 2. AI 分析 (ai_analyze.py)

| 端点 | 方法 | 功能 | 优先级 |
|------|------|------|--------|
| `/analyze` | POST | 数据分析 | **P0** |
| `/analyze/export/<id>` | GET | 导出分析结果 | P1 |

### 3. AI 解析 (ai_parse.py)

| 端点 | 方法 | 功能 | 优先级 |
|------|------|------|--------|
| `/parse-single` | POST | 单条解析 | **P0** |
| `/parse-products` | POST | 产品批量解析 | **P0** |

### 4. 性能监控 (performance.py)

| 端点 | 方法 | 功能 | 优先级 |
|------|------|------|--------|
| `/status` | GET | 性能状态 | P1 |
| `/health` | GET | 健康检查 | P1 |
| `/metrics/summary` | GET | 性能摘要 | P1 |
| `/metrics/prometheus` | GET | Prometheus指标 | P2 |
| `/cache/stats` | GET | 缓存统计 | P1 |
| `/cache/clear` | POST | 清除缓存 | P1 |
| `/cache/invalidate` | POST | 使缓存失效 | P1 |
| `/tasks/status` | GET | 任务状态 | P1 |
| `/alerts` | GET | 告警信息 | P2 |
| `/slow-queries` | GET | 慢查询 | P2 |

### 5. 报表 (report.py)

| 端点 | 方法 | 功能 | 优先级 |
|------|------|------|--------|
| `/sales` | GET | 销售报表 | **P0** |
| `/inventory` | GET | 库存报表 | **P0** |
| `/purchase` | GET | 采购报表 | **P0** |
| `/inventory/transactions` | GET | 库存交易报表 | P1 |
| `/dashboard` | GET | 仪表板汇总 | **P0** |
| `/export` | POST | 导出报表 | P1 |

### 6. 技能 (skills.py)

| 端点 | 方法 | 功能 | 优先级 |
|------|------|------|--------|
| `/list` | GET | 技能列表 | P1 |
| `/info/<id>` | GET | 技能详情 | P1 |
| `/execute` | POST | 执行技能 | **P0** |
| `/analyze/excel` | POST | 分析Excel | P1 |
| `/view/excel` | POST | 查看Excel | P1 |
| `/generate-label-template` | POST | 生成标签模板 | P1 |

### 7. 工具 (tools.py)

| 端点 | 方法 | 功能 | 优先级 |
|------|------|------|--------|
| `/api/database/backup` | POST | 数据库备份 | **P0** |
| `/api/database/restore` | POST | 数据库恢复 | **P0** |
| `/api/database/backups` | GET | 备份列表 | P1 |
| `/api/database/backup/<file>` | DELETE | 删除备份 | P1 |
| `/api/system/startup` | GET/POST/DELETE | 开机启动配置 | P2 |
| `/api/system/info` | GET | 系统信息 | P1 |
| `/api/system/printer` | GET | 打印机配置 | P1 |

### 8. 上下文 API (context_api.py)

| 端点 | 方法 | 功能 | 优先级 |
|------|------|------|--------|
| `/pending/<user_id>` | GET/DELETE | 待处理状态 | P1 |
| `/history/<user_id>` | GET | 聊天历史 | P1 |

### 9. 传统模式 (traditional_mode.py)

| 端点 | 方法 | 功能 | 优先级 |
|------|------|------|--------|
| `/list` | GET | 文件列表 | P1 |
| `/read` | GET | 读取文件 | P1 |
| `/write` | POST | 写入文件 | P1 |
| `/mkdir` | POST | 创建目录 | P2 |
| `/rename` | POST | 重命名 | P2 |
| `/delete` | POST | 删除 | P2 |
| `/upload` | POST | 文件上传 | P1 |

### 10. 上传 (upload.py)

| 端点 | 方法 | 功能 | 优先级 |
|------|------|------|--------|
| `/temp` | POST | 临时上传 | P1 |
| `/temp/<filename>` | DELETE | 删除临时文件 | P1 |
| `/config` | GET | 上传配置 | P2 |

### 11. 状态 (state.py)

| 端点 | 方法 | 功能 | 优先级 |
|------|------|------|--------|
| `/client-mods-off` | GET/POST | 客户端Mods状态 | P1 |

### 12. 指标 (metrics.py)

| 端点 | 方法 | 功能 | 优先级 |
|------|------|------|--------|
| `/metrics` | GET | Prometheus指标 | P2 |

### 13. 模板 (templates.py)

| 端点 | 方法 | 功能 | 优先级 |
|------|------|------|--------|
| `/extract-grid` | POST | 提取网格 | **P0** |
| `/validate` | POST | 验证模板 | P1 |
| `/preview` | GET | 预览模板 | P1 |

---

## ✅ XCAGI 已覆盖的功能（无需迁移）

以下功能 XCAGI FastAPI 已有实现：

- `ai_chat.py` → `XCAGI/app/fastapi_routes/ai_chat.py` ✅
- `auth.py` → `XCAGI/app/fastapi_routes/auth.py` ✅
- `conversations.py` → `XCAGI/app/fastapi_routes/conversations.py` ✅
- `customers.py` → `XCAGI/app/fastapi_routes/customers.py` ✅
- `distillation.py` → `XCAGI/app/fastapi_routes/distillation.py` ✅
- `excel_*.py` (3个) → `XCAGI/app/fastapi_routes/excel.py` ✅
- `health.py` → `XCAGI/app/fastapi_routes/health.py` ✅
- `intent.py` / `intent_packages.py` → `XCAGI/app/fastapi_routes/intent.py` ✅
- `inventory.py` → `XCAGI/app/fastapi_routes/inventory.py` ✅
- `materials.py` → `XCAGI/app/fastapi_routes/materials.py` ✅
- `miniprogram_api.py` → `XCAGI/app/fastapi_routes/miniprogram.py` ✅
- `mods.py` → `XCAGI/app/fastapi_routes/mods.py` ✅
- `mp_*.py` (10个) → `XCAGI/app/fastapi_routes/miniprogram.py` ✅
- `ocr.py` → `XCAGI/app/fastapi_routes/ocr.py` ✅
- `print.py` → `XCAGI/app/fastapi_routes/print.py` ✅
- `products.py` → `XCAGI/app/fastapi_routes/products.py` ✅
- `purchase.py` → `XCAGI/app/fastapi_routes/purchase.py` ✅
- `shipment.py` → `XCAGI/app/fastapi_routes/shipment/` ✅
- `system.py` → `XCAGI/app/fastapi_routes/system.py` ✅
- `wechat.py` / `wechat_contacts.py` / `wechat_miniprogram.py` → `XCAGI/app/fastapi_routes/wechat.py` / `wechat_contacts.py` ✅
- `frontend.py` → 静态文件服务，XCAGI 已覆盖 ✅

---

## 📋 迁移计划

### Phase 1: P0 核心功能（优先完成）

1. ai_assistant_compat: `/api/generate`, `/api/orders`
2. ai_analyze: `/analyze`
3. ai_parse: `/parse-single`, `/parse-products`
4. report: `/sales`, `/inventory`, `/purchase`, `/dashboard`
5. tools: `/api/database/backup`, `/api/database/restore`
6. templates: `/extract-grid`

### Phase 2: P1 重要功能

1. performance: 性能监控相关
2. skills: 技能执行
3. traditional_mode: 传统模式文件操作
4. context_api: 上下文管理
5. 其他报表和工具功能

### Phase 3: P2 可选功能

1. metrics: Prometheus 指标
2. system: 开机启动配置
3. 其他低频使用功能

---

## 🎯 迁移策略

1. **逐一迁移**: 按优先级逐个文件迁移
2. **保持兼容**: API 路径和响应格式保持一致
3. **添加日志**: 迁移后的路由添加日志便于调试
4. **快速注册**: 在 `__init__.py` 中注册新路由
5. **逐步弃用**: Flask 路由添加更多弃用警告

---

**评估完成时间**: 2026-04-17  
**预计迁移时间**: 2-3 天  
**状态**: 准备开始迁移
