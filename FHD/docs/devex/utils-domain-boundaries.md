# app/utils 职责域边界规划（P2-2 整改）

> 目的：把 `app/utils/` 中 47 个职责泛化、低内聚的模块按职责域重组为带边界的子包，
> 杜绝"工具缝合怪"继续膨胀。本文档是归类清单 + 目标包结构的唯一真相源，
> 与 `scripts/dev/guard_utils_boundary.py` 的 `DOMAIN_TARGETS` / `CROSS_CUTTING` 保持一致。

## 1. 背景

`app/utils/` 曾同时放置 46 个 `.py` 工具模块（不含 `__init__.py`），横跨重试/Excel/安全/日志/
性能/设备/异步任务等多个相互独立的责任域。整改分阶段迁移，每阶段只迁移低风险职责域，
并保持 `app/utils/__init__.py` 的懒加载（`_EXPORTS` + `__getattr__`）契约不变——
**import `app.utils.operational_errors` 不得拉入 `tenacity`**。

## 2. 目标包结构

```
app/utils/
├── __init__.py            # 懒加载导出（_EXPORTS + __getattr__），符号名不变
├── <cross_cutting 白名单暂留根命名空间>
├── excel/                 # Excel 读写 / 模板分析 / 模板导出
├── resilience/            # 重试 / 熔断 / 限流 / 请求去重
├── security/              # 密码 / 安全文件名 / 安全中间件 / 路径安全 / 代理环境
├── logging/               # 日志 / 审计
├── performance/           # 性能配置 / 监控 / 查询优化 / 缓存
├── path_io/               # 路径 / 打印 / 上传 / 头像存储 / 外部 SQLite
├── device_system/         # 设备标识 / 系统服务 / 端口 / 移动端 API
└── async_task/            # 异步任务 / 任务上下文
```

## 3. 归类清单（46 个模块）

### 3.1 已迁移（Stage 2 完成）

| 模块 | 职责域 | 目标包路径 | 状态 |
|------|--------|-----------|------|
| `excel_utils.py` | excel | `app/utils/excel/excel_utils.py` | ✅ 已迁移 |
| `excel_template_analyzer.py` | excel | `app/utils/excel/excel_template_analyzer.py` | ✅ 已迁移 |
| `template_export_utils.py` | excel | `app/utils/excel/template_export_utils.py` | ✅ 已迁移 |
| `retry.py` | resilience | `app/utils/resilience/retry.py` | ✅ 已迁移 |
| `circuit_breaker.py` | resilience | `app/utils/resilience/circuit_breaker.py` | ✅ 已迁移 |
| `rate_limiter.py` | resilience | `app/utils/resilience/rate_limiter.py` | ✅ 已迁移 |
| `request_deduplicator.py` | resilience | `app/utils/resilience/request_deduplicator.py` | ✅ 已迁移 |

### 3.2 待迁移（后续 Stage）

| 模块 | 职责域 | 目标包路径 | 状态 |
|------|--------|-----------|------|
| `password_hash.py` | security | `app/utils/security/password_hash.py` | ⏳ 待迁移 |
| `secure_filename.py` | security | `app/utils/security/secure_filename.py` | ⏳ 待迁移 |
| `security_middleware.py` | security | `app/utils/security/security_middleware.py` | ⏳ 待迁移 |
| `safe_download_path.py` | security | `app/utils/security/safe_download_path.py` | ⏳ 待迁移（兼涉 path_io，归 security 为主） |
| `proxy_env.py` | security | `app/utils/security/proxy_env.py` | ⏳ 待迁移 |
| `logger.py` | logging | `app/utils/logging/logger.py` | ⏳ 待迁移 |
| `logging_utils.py` | logging | `app/utils/logging/logging_utils.py` | ⏳ 待迁移 |
| `audit_events.py` | logging | `app/utils/logging/audit_events.py` | ⏳ 待迁移 |
| `audit_logger.py` | logging | `app/utils/logging/audit_logger.py` | ⏳ 待迁移 |
| `performance_config.py` | performance | `app/utils/performance/performance_config.py` | ⏳ 待迁移 |
| `performance_initializer.py` | performance | `app/utils/performance/performance_initializer.py` | ⏳ 待迁移 |
| `performance_monitor.py` | performance | `app/utils/performance/performance_monitor.py` | ⏳ 待迁移 |
| `query_optimizer.py` | performance | `app/utils/performance/query_optimizer.py` | ⏳ 待迁移 |
| `cache_manager.py` | performance | `app/utils/performance/cache_manager.py` | ⏳ 待迁移 |
| `redis_cache.py` | performance | `app/utils/performance/redis_cache.py` | ⏳ 待迁移 |
| `path_utils.py` | path_io | `app/utils/path_io/path_utils.py` | ⏳ 待迁移 |
| `print_utils.py` | path_io | `app/utils/path_io/print_utils.py` | ⏳ 待迁移 |
| `printer_automation.py` | path_io | `app/utils/path_io/printer_automation.py` | ⏳ 待迁移 |
| `upload_helpers.py` | path_io | `app/utils/path_io/upload_helpers.py` | ⏳ 待迁移 |
| `user_avatar_storage.py` | path_io | `app/utils/path_io/user_avatar_storage.py` | ⏳ 待迁移 |
| `external_sqlite.py` | path_io | `app/utils/path_io/external_sqlite.py` | ⏳ 待迁移 |
| `device_identity.py` | device_system | `app/utils/device_system/device_identity.py` | ⏳ 待迁移 |
| `system_service.py` | device_system | `app/utils/device_system/system_service.py` | ⏳ 待迁移 |
| `listen_port.py` | device_system | `app/utils/device_system/listen_port.py` | ⏳ 待迁移 |
| `mobile_api.py` | device_system | `app/utils/device_system/mobile_api.py` | ⏳ 待迁移 |
| `async_tasks.py` | async_task | `app/utils/async_task/async_tasks.py` | ⏳ 待迁移 |
| `task_context.py` | async_task | `app/utils/async_task/task_context.py` | ⏳ 待迁移 |

### 3.3 暂留根命名空间（cross_cutting 白名单，不改动）

以下模块横向横切、无单一责任域归属，暂留根命名空间，由 `guard_utils_boundary.py` 白名单放行：

| 模块 | 说明 |
|------|------|
| `ai_helpers.py` | AI 常量/路由辅助 |
| `decorators.py` | 通用装饰器 |
| `deployment.py` | 部署环境/开关 |
| `distillation_paths.py` | 蒸馏路径常量 |
| `error_handling.py` | 通用错误处理 |
| `json_safe.py` | JSON 安全序列化 |
| `metrics.py` | Prometheus 指标 |
| `no_email.py` | 空邮件哨兵 |
| `openapi_path.py` | OpenAPI 路径常量 |
| `operational_errors.py` | 可恢复错误集合（懒加载契约关键依赖） |
| `time.py` | 时间工具 |
| `user_memory.py` | 用户记忆辅助 |

## 4. 懒加载契约（CRITICAL 约束）

`app/utils/__init__.py` 用 `_EXPORTS` + `__getattr__` 做懒加载，docstring 明确要求
**import `app.utils.operational_errors` 不得拉入 `tenacity`**。

Stage 2 中，`_EXPORTS` 指向 `retry` / `circuit_breaker` 的条目已更新为新路径：

- `app.utils.retry` → `app.utils.resilience.retry`
- `app.utils.circuit_breaker` → `app.utils.resilience.circuit_breaker`

`__getattr__` 的 fallback（`import_module(f"{__name__}.{name}")`）逻辑保持不变；
`from app.utils import rate_limiter` 这类裸子模块访问已同步改为
`from app.utils.resilience import rate_limiter`（测试文件已相应更新）。

**注意**：迁移其余职责域时，凡 `_EXPORTS` 中出现的模块路径都必须同步指向新子包路径，
且不要改动 `__all__` 的导出符号名（外部按符号名引用）。

## 5. 防腐化守卫

`scripts/dev/guard_utils_boundary.py` 扫描 `app/utils/*.py`（仅根目录，排除 `__init__.py`）：

- `--report`：输出每个文件的职责域归属清单。
- 默认：对不在 `CROSS_CUTTING` 白名单的根模块输出 `::warning::`，退出码 0。
- `--check`：存在违规（未迁移职责域模块或无边界新通用模块）时以非零退出码失败。

> Stage 2 上线后，`--check` 会因 27 个"待迁移"职责域模块仍留在根目录而失败，
> 属预期行为；待后续 Stage 迁移完成后自然通过。CI 接入由后续 Task 处理。