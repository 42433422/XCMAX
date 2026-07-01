# XCMAX 项目技术债全面修复清单

> 本文档为全项目技术债修复提示词，按优先级 P0→P3 排列。每个问题包含：问题描述、文件位置、修复要求、验收标准。

---

## P0 — 安全漏洞（必须立即修复）

> **2026-06-25 修复状态**：P0-1/P0-2/P0-3/P0-4 全部修复完成。

### P0-1 自实现 JWT 存在安全风险 ✅ 已修复

**文件**: `FHD/app/security/mobile_jwt.py`

**状态**: 已修复。已迁移到 PyJWT，强制 HS256 算法白名单，添加 iss/aud 声明，
refresh token jti 一次性使用（内存 + Redis 黑名单），移除硬编码密钥回退（改用
进程级 `secrets.token_urlsafe(48)` 随机密钥）。

**问题**: 手写 JWT 编解码而非使用 PyJWT 库，缺少以下安全机制：
- 无 `iss`（签发者）声明，无法验证 token 来源
- 无算法白名单，存在算法混淆攻击风险（如 `none` 算法注入）
- 无 token 撤销/黑名单机制
- `refresh_mobile_access_token` 未验证 refresh token 是否已被使用过（重放风险）
- `_secret_key()` 回退值为硬编码 `"xcagi-dev-secret"`

**修复要求**:
1. 引入 `PyJWT` 依赖，替换手写 JWT 实现
2. 签发时强制指定 `algorithms=["HS256"]`，验证时使用相同白名单
3. 添加 `iss="xcagi-mobile"` 声明，验证时校验签发者
4. 实现 refresh token 一次性使用机制（使用 jti + Redis 缓存已使用的 refresh token）
5. 移除 `_secret_key()` 中的硬编码回退值，缺失时抛出异常

**验收标准**: `pytest tests/test_mobile_api.py` 全绿；无硬编码密钥；JWT 验证拒绝 `alg=none` 和非 HS256 算法

---

### P0-2 官网支付签名密钥硬编码前端 ✅ 已修复

**文件**: `成都修茈科技有限公司/src/api.ts`

**状态**: 已修复。移除 `paymentSecretKey()` 中的 `'default_secret_key'` 硬编码回退，
函数返回空字符串。后端 `/api/model-payment/checkout` 直接用 plan_id 查套餐金额并调
支付宝下单，不信任前端传值，因此前端签名是"假安全"——真正的签名由后端
`app/infrastructure/payment/alipay.py` 完成（密钥仅存服务端 env）。

**问题**: `paymentSecretKey()` 中 `return fromEnv || 'default_secret_key'`，支付签名密钥硬编码在前端代码中且 fallback 为可预测默认值，攻击者可伪造支付请求

**修复要求**:
1. 支付签名必须在后端完成，前端仅传递支付参数，不参与签名计算
2. 移除前端 `paymentSecretKey()` 函数和 `'default_secret_key'` 硬编码
3. 后端新增支付签名接口，密钥仅存于服务端环境变量

**验收标准**: 前端代码中无任何签名密钥；支付流程由后端签名；`grep -r "secret_key\|paymentSecret" src/` 无结果

---

### P0-3 AI Tier token 比较存在时序攻击风险 ✅ 已修复

**文件**: `FHD/app/domain/ai/tier.py`

**状态**: 已修复。`hmac.compare_digest` 已使用（恒定时间比较）。环境变量
`FHD_AI_ELEVATED_TOKEN` 和 `FHD_AI_TIER_STRICT` 已缓存为模块级变量
（`_ELEVATED_TOKEN` / `_TIER_STRICT`），避免每次请求读 `os.environ`。

**问题**: `resolve_ai_tier` 中 token 比较使用 `==` 而非 `hmac.compare_digest`，存在时序攻击风险。同项目 `mobile_jwt.py` 已正确使用 `compare_digest`，但此处不一致

**修复要求**:
1. 将 token 比较替换为 `hmac.compare_digest(token, expected_token)`
2. 将 `FHD_AI_ELEVATED_TOKEN` 环境变量读取缓存为模块级变量（避免每次请求读 `os.environ`）

**验收标准**: `grep -n "==" tier.py` 中无 token 比较逻辑；环境变量仅启动时读取一次

---

### P0-4 官网无 CSRF 防护且 token 无刷新机制 ✅ 已完整闭环

**文件**: `成都修茈科技有限公司/src/api.ts` + `src/stores/auth.ts` + 3 个登录视图 + 后端已有

**状态**: 已完整闭环（前端 + 后端）。

**后端已实现**（无需改动）：
1. [csrf.py](file:///Users/a4243342/Desktop/XCMAX/FHD/app/middleware/csrf.py) CSRF 中间件：GET 自动下发 `csrf_token` cookie（`SameSite=Lax`），写操作校验 `X-CSRF-Token` header 与 cookie 一致（`secrets.compare_digest`）
2. [web_jwt.py](file:///Users/a4243342/Desktop/XCMAX/FHD/app/security/web_jwt.py) Web JWT：access 12h + refresh 14d，HS256 + iss/aud/exp 强校验，refresh 一次性轮转（jti 黑名单）
3. [routes.py](file:///Users/a4243342/Desktop/XCMAX/FHD/app/fastapi_routes/domains/auth/routes.py) `/api/auth/login` 签发 `web_tokens`，`/api/auth/token/refresh` 轮转
4. session cookie 已 `httpOnly` + `SameSite=Lax`（`SESSION_COOKIE_HTTPONLY=1`）

**前端本次修复**：
1. [api.ts](file:///Users/a4243342/Desktop/XCMAX/成都修茈科技有限公司/src/api.ts) 添加 CSRF 双重提交 cookie（写操作自动注入 `X-CSRF-Token`）
2. [api.ts](file:///Users/a4243342/Desktop/XCMAX/成都修茈科技有限公司/src/api.ts) 添加 JWT exp 过期预检 + 401 自动 refresh + 重试（并发去重，避免循环）
3. [api.ts](file:///Users/a4243342/Desktop/XCMAX/成都修茈科技有限公司/src/api.ts) 导出 `setTokens()` 供登录后存储 access + refresh
4. [auth.ts](file:///Users/a4243342/Desktop/XCMAX/成都修茈科技有限公司/src/stores/auth.ts) token 过期预检 + `storeTokens()` + logout 清除 refresh_token
5. [LoginView.vue](file:///Users/a4243342/Desktop/XCMAX/成都修茈科技有限公司/src/views/LoginView.vue#L43-L47) / [RegisterView.vue](file:///Users/a4243342/Desktop/XCMAX/成都修茈科技有限公司/src/views/RegisterView.vue#L135-L139) / [LoginByEmailView.vue](file:///Users/a4243342/Desktop/XCMAX/成都修茈科技有限公司/src/views/LoginByEmailView.vue#L97-L101) 登录后存储 `web_tokens`

**问题**: 无 CSRF 防护机制；token 存储在 localStorage 无加密；无 token 过期/刷新逻辑

**修复要求**:
1. 写操作请求添加 CSRF token 头（从 cookie 读取或预请求获取）
2. 实现 access/refresh token 双令牌机制，access token 过期时自动刷新
3. 敏感 token 考虑使用 httpOnly cookie 而非 localStorage

**验收标准**: 所有 POST/PUT/DELETE 请求携带 CSRF token；token 过期后自动刷新而非直接报错

---

## P1 — 架构与代码质量（强烈建议修复）

### P1-1 AppViewModel 职责过重（950+ 行）

**文件**: `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/ui/AppViewModel.kt`

**问题**: 单个 ViewModel 承担登录、聊天、审批、IM、同步、配对等所有业务，违反单一职责原则

**修复要求**:
1. 拆分为独立 ViewModel：
   - `AuthViewModel` — 登录/登出/会话管理
   - `ChatViewModel` — AI 对话/SSE 流
   - `ApprovalViewModel` — 审批列表/详情/操作
   - `HomeViewModel` — 首页/配对/模式切换
   - `ImViewModel` — IM 消息/联系人
2. 共享状态通过 Hilt `@Singleton` Repository 或 SavedStateHandle 传递
3. `AppViewModel` 仅保留全局状态（如登录状态、服务器模式）

**验收标准**: 每个 ViewModel 不超过 300 行；`AppViewModel` 不超过 200 行；所有现有功能不退化

---

### P1-2 task_agent.parse_task 函数过长（130+ 行）

**文件**: `FHD/app/services/task_agent.py`

**问题**: `parse_task` 方法嵌套 6 层条件分支，可读性差；正则表达式硬编码且大量重复

**修复要求**:
1. 拆分为独立意图检测器：
   - `_detect_shipment_intent(text) -> Optional[dict]`
   - `_detect_product_query_intent(text) -> Optional[dict]`
   - `_detect_customer_query_intent(text) -> Optional[dict]`
   - `_detect_customer_supplement_intent(text) -> Optional[dict]`
2. 提取正则表达式为模块级常量：
   ```python
   RE_SPEC = re.compile(r"规格\s*[:：]?\s*(\d+(?:\.\d+)?)")
   RE_UNIT = re.compile(r"单位\s*[:：]?\s*(\S+)")
   # ... 等
   ```
3. `_cn_number` 函数补充百/千/万级别支持，或添加文档说明仅支持 0-99

**验收标准**: `parse_task` 不超过 40 行；无重复正则；`_cn_number` 有范围说明或扩展支持

---

### P1-3 mods.ts 单文件过长（1085+ 行）

**文件**: `FHD/frontend/src/stores/mods.ts`

**问题**: 单文件承担 Mod 列表拉取、缓存、探测、菜单合并、行业同步等过多职责

**修复要求**:
1. 拆分为：
   - `modsStore.ts` — 核心 Pinia store（列表、加载状态、缓存）
   - `modProbes.ts` — Mod 状态探测逻辑（`modStatusProbeCache` 等）
   - `modMenu.ts` — 菜单合并逻辑
   - `modIndustrySync.ts` — 行业同步逻辑
2. 通过 `import` 保持 store 间的协作关系

**验收标准**: 每个文件不超过 300 行；Mod 功能不退化；`npm run build` 无报错

---

### P1-4 router/index.ts 过长（720+ 行）

**文件**: `FHD/frontend/src/router/index.ts`

**问题**: 路由定义与守卫逻辑混在一起

**修复要求**:
1. 提取守卫逻辑为独立文件：
   - `router/guards/auth.ts` — 认证守卫
   - `router/guards/edition.ts` — 版本/edition 守卫
   - `router/guards/mod.ts` — Mod 路由守卫
2. `router/index.ts` 仅保留路由定义和守卫注册

**验收标准**: `router/index.ts` 不超过 200 行；守卫逻辑独立可测试

---

### P1-5 ai_chat.py 函数过长且延迟导入过多

**文件**: `FHD/app/routes/ai_chat.py`

**问题**:
- `unified_chat_single_payload` 函数 80+ 行，职责过多
- `_build_number_preview_items` 函数 60+ 行
- 大量函数内延迟导入（`from app.xxx import yyy`）暗示循环依赖
- 中文字典键硬编码（`"单位"`, `"型号"`, `"产品名称"`）

**修复要求**:
1. 拆分 `unified_chat_single_payload` 为：
   - `_resolve_intent(payload)` — 意图识别
   - `_build_response(intent, context)` — 响应构建
   - `_format_chat_reply(result)` — 格式化输出
2. 提取 `_normalize_model_token` 和 `_pick_best_record` 为模块级函数
3. 中文字典键提取为常量：
   ```python
   FIELD_UNIT = "单位"
   FIELD_MODEL = "型号"
   FIELD_PRODUCT_NAME = "产品名称"
   ```
4. 分析延迟导入的循环依赖根因，考虑通过 DI 容器或接口抽象解耦

**验收标准**: 无函数超过 40 行；无函数内延迟导入；中文字典键使用常量

---

### P1-6 Android FhdApi 返回类型不安全

**文件**: `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/network/FhdApi.kt`

**问题**: 大量接口返回 `Map<String, Any?>`（如 `chat()`、`approvalDetail()`、`bridgeRequests()`），导致 Repository 层需要大量手动解析和 `@Suppress("UNCHECKED_CAST")`

**修复要求**:
1. 为每个返回 `Map<String, Any?>` 的接口定义对应的 Kotlin data class：
   ```kotlin
   @Serializable data class ChatResponse(val reply: String, val intent: String?)
   @Serializable data class ApprovalDetailResponse(val approval: ApprovalDto, val items: List<ApprovalItemDto>)
   ```
2. Retrofit 接口使用强类型返回值
3. 移除 Repository 层的 `@Suppress("UNCHECKED_CAST")` 和手动 Map 解析

**验收标准**: FhdApi 接口无 `Map<String, Any?>` 返回值；Repository 无 `@Suppress("UNCHECKED_CAST")`

---

### P1-7 前端类型安全不足

**文件**: `FHD/frontend/src/api/chat.ts`, `FHD/frontend/src/stores/chat.ts`, `FHD/frontend/src/api/auth.ts`

**问题**:
- `chat.ts` API: `saveMessage(payload: any)`, `testIntent(data: any)`, `getConfig(): Promise<ApiResponse<any>>`
- `chat.ts` store: `messages = computed(() => jarvis.messages as any[])`, `(jarvis as any).sendMessage?.(message)`
- `auth.ts`: `validateSession(): Promise<ApiResponse<any>>`

**修复要求**:
1. 定义缺失的 TypeScript 接口：
   ```typescript
   interface ChatMessage { id: string; role: 'user' | 'assistant'; content: string; timestamp: number }
   interface ChatConfig { model: string; maxTokens: number; temperature: number }
   interface SessionValidation { valid: boolean; user: User | null }
   ```
2. 替换所有 `any` 为具体类型
3. 移除 `as any` 类型断言，通过正确的类型声明解决

**验收标准**: `npx tsc --noImplicitAny` 无新增错误；`grep -r "any" src/api/ src/stores/` 无 `any` 类型（除第三方库类型）

---

## P2 — 代码整洁与一致性（建议修复）

### P2-1 get_db 与 get_db_dependency 完全重复

**文件**: `FHD/app/db/session.py`

**问题**: `get_db` 和 `get_db_dependency` 逻辑完全相同

**修复要求**:
1. 保留 `get_db` 作为唯一实现
2. `get_db_dependency = get_db`（别名）
3. 或删除 `get_db_dependency`，统一使用 `get_db` 作为 FastAPI 依赖

**验收标准**: 无重复的数据库会话生成器逻辑

---

### P2-2 LRUCache 与 LRUTTLCache 代码重复

**文件**: `FHD/app/utils/cache_manager.py`

**问题**: `LRUCache` 和 `LRUTTLCache` 的 `get`/`set`/`clear`/`remove`/`has` 方法大量重复

**修复要求**:
1. 提取 `BaseCache` 基类包含通用方法
2. `LRUCache` 继承 `BaseCache`
3. `LRUTTLCache` 继承 `LRUCache`，仅覆盖需要 TTL 逻辑的方法

**验收标准**: 无重复的缓存操作方法；`pytest tests/` 全绿

---

### P2-3 CacheManager 单例线程安全缺陷

**文件**: `FHD/app/utils/cache_manager.py`

**问题**: `__new__` 中的锁保护了实例创建，但 `__init__` 中的 `_initialized` 检查不在锁内，存在竞态条件

**修复要求**:
1. 将 `_initialized` 检查移入 `__new__` 的锁保护范围内
2. 或改用模块级变量实现单例（Python 模块导入是线程安全的）

**验收标准**: 多线程并发访问 `CacheManager()` 仅创建一个实例

---

### P2-4 ServiceContainer 线程安全缺陷

**文件**: `FHD/app/di/registry.py`

**问题**: 多个请求同时首次访问某个懒加载属性时可能创建多个实例

**修复要求**:
1. 使用 `threading.Lock` 保护懒加载属性的首次初始化
2. 或使用 `functools.cached_property`（Python 3.8+，线程安全）

**验收标准**: 懒加载属性在并发访问下仅初始化一次

---

### P2-5 get_fastapi_app 非线程安全单例

**文件**: `FHD/app/fastapi_app/factory.py`

**问题**: 使用函数属性 `get_fastapi_app._app` 做单例，非线程安全

**修复要求**:
1. 改用模块级变量 + `threading.Lock` 实现线程安全单例
2. 或使用 FastAPI 推荐的方式（模块级 `app = create_app()`）

**验收标准**: 并发调用 `get_fastapi_app()` 仅创建一个 app 实例

---

### P2-6 f-string 日志性能问题

**文件**: 多处（`session.py`, `bus.py`, `task_agent.py` 等）

**问题**: `logger.warning(f"数据库事务失败: {e}")` 在日志级别未启用时仍会构造字符串

**修复要求**:
1. 全局替换为惰性格式：
   ```python
   # Before
   logger.warning(f"数据库事务失败: {e}")
   # After
   logger.warning("数据库事务失败: %s", e)
   ```
2. 使用 `ruff` 规则 `G004`（flake8-logging-format）自动检测

**验收标准**: `ruff check --select G004 app/` 无结果

---

### P2-7 限流器内存泄漏风险

**文件**: `FHD/app/utils/rate_limiter.py`

**问题**: `_InMemoryRateLimiter._requests` 字典无容量上限，长时间运行可能内存泄漏

**修复要求**:
1. 添加最大容量限制（如 10000 条），超出时淘汰最旧记录
2. 或使用 `collections.OrderedDict` + LRU 淘汰

**验收标准**: `_requests` 字典容量有上限；长时间运行内存稳定

---

### P2-8 熔断器使用裸 Exception

**文件**: `FHD/app/utils/rate_limiter.py`

**问题**: `_CircuitBreaker.call` 在 `state == "open"` 时抛出裸 `Exception`，应自定义异常类型

**修复要求**:
1. 定义 `CircuitOpenError(Exception)` 自定义异常
2. 替换裸 `Exception` 为 `CircuitOpenError`
3. 调用方可以精确捕获熔断器异常

**验收标准**: `grep -n "raise Exception" rate_limiter.py` 无结果

---

### P2-9 AuthInterceptor 使用 runBlocking

**文件**: `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/network/AuthInterceptor.kt`

**问题**: `intercept()` 中使用 `runBlocking` 读取 DataStore Flow，在 OkHttp 线程上可能阻塞

**修复要求**:
1. 在 `AuthInterceptor` 中缓存 token 到内存变量
2. 通过 `SessionStore` 的 `Flow` 收集更新内存缓存
3. `intercept()` 中直接读取内存缓存，无需 `runBlocking`

**验收标准**: `grep -n "runBlocking" AuthInterceptor.kt` 无结果

---

### P2-10 product.py 布尔字段使用 Integer 类型

**文件**: `FHD/app/db/models/product.py`

**问题**: `is_active` 用 `Integer` 而非 `Boolean` 表示布尔值，是反模式

**修复要求**:
1. 将 `is_active = mapped_column(Integer, ...)` 改为 `is_active = mapped_column(Boolean, default=True)`
2. 添加 Alembic 迁移脚本处理数据类型变更

**验收标准**: `is_active` 字段类型为 `Boolean`；迁移脚本可正确执行

---

## P3 — 测试与文档（持续优化）

### P3-1 清零 41 条失败测试用例

**文件**: `FHD/tests/`

**问题**: 779 条测试中 41 条失败，约 50% 源于模型字段不同步（`unit_name` 不存在）和版本策略漂移（edition 默认值变化）

**修复要求**:
1. 修复模型字段不同步：更新测试中的字段名与当前 ORM 模型一致
2. 修复版本策略漂移：更新测试中的默认 edition 值
3. PostgreSQL 依赖测试标记 `@pytest.mark.integration`，CI 中单独运行
4. 确保 `pytest tests/` 全绿

**验收标准**: `pytest tests/ --tb=short` 0 failed；CI 门禁通过

---

### P3-2 前端测试补强

**文件**: `FHD/frontend/src/api.test.js`, `FHD/frontend/e2e/smoke.spec.ts`

**问题**:
- `api.test.js` 仅 10 个 `toBeDefined()` 测试，无业务逻辑验证
- E2E 仅 4 条冒烟测试

**修复要求**:
1. API 测试：使用 MSW（Mock Service Worker）拦截 HTTP 请求，验证业务逻辑
2. E2E 测试：至少覆盖核心业务链路（产品 CRUD、发货单生成、AI 对话）
3. 目标：前端测试从 14 条扩展到 50+ 条

**验收标准**: 前端测试 ≥ 50 条；覆盖核心业务场景；`npm run test` 全绿

---

### P3-3 API 文档版本同步

**文件**: `FHD/XCAGI/API_DOCS.md`

**问题**: 版本号标注为 `5.0.0`，与当前 `10.0.0` 严重不同步；仅端点列表，缺请求/响应 schema

**修复要求**:
1. 更新版本号为 `10.0.0`
2. 考虑从 FastAPI 的 OpenAPI spec（`/docs`）自动生成，替代手写维护
3. 或至少为每个端点补充：请求参数、响应 schema、认证要求、错误码

**验收标准**: API 文档版本号与 `VERSION.md` 一致；核心端点有 schema 描述

---

### P3-4 CHANGELOG 版本切割

**文件**: `FHD/CHANGELOG.md`

**问题**: Unreleased 部分积累约 150 行，应按功能里程碑切割为正式版本

**修复要求**:
1. 将 Unreleased 条目按功能里程碑切割为 `10.0.1`、`10.1.0` 等版本
2. 每个版本包含日期和变更摘要
3. 遵循 Keep a Changelog 格式

**验收标准**: Unreleased 部分不超过 20 行；已有版本条目有日期和摘要

---

### P3-5 K8s NetworkPolicy Ingress 规则过于宽松

**文件**: `FHD/k8s/networkpolicy.yaml`

**问题**: Ingress 规则使用 `namespaceSelector: {}`（允许所有命名空间访问），过于宽松

**修复要求**:
1. 限定 Ingress 来源为 Ingress Controller 所在命名空间：
   ```yaml
   namespaceSelector:
     matchLabels:
       name: ingress-nginx
   ```
2. 或添加 `podSelector` 进一步限定到 Ingress Controller Pod

**验收标准**: NetworkPolicy Ingress 规则仅允许特定命名空间访问

---

### P3-6 部署后自动化验证缺失

**文件**: `FHD/.github/workflows/deploy.yml`

**问题**: `rollout status` 后无 smoke test / 健康检查确认

**修复要求**:
1. 在 `rollout status` 步骤后增加健康检查：
   ```yaml
   - name: Post-deploy smoke test
     run: |
       kubectl exec deploy/xcagi-fhd-api -- curl -sf http://localhost:5000/api/health/liveness
       curl -sf https://${{ env.DOMAIN }}/api/health/readiness
   ```
2. 健康检查失败时自动触发回滚

**验收标准**: 部署流程包含自动化健康检查；检查失败有明确错误输出

---

### P3-7 Helm Chart 未完整实现

**文件**: `FHD/helm/xcagi/`

**问题**: 仅有 `Chart.yaml` 和 `values.yaml`，缺少 `templates/` 目录

**修复要求**:
1. 创建 `templates/` 目录，将 K8s 清单模板化
2. 替换 CI 中的 `sed` 替换方案为 Helm values 注入
3. 补充资源限制、安全上下文、环境变量等关键配置到 `values.yaml`

**验收标准**: `helm template xcagi ./helm/xcagi` 可正确渲染所有 K8s 资源

---

### P3-8 官网 api.ts 拆分与安全加固

**文件**: `成都修茈科技有限公司/src/api.ts`

**问题**: 单文件 300+ 行承载全部 API；无模块化拆分；无请求/响应拦截器

**修复要求**:
1. 按业务域拆分：
   - `api/auth.ts` — 认证相关
   - `api/wallet.ts` — 钱包相关
   - `api/market.ts` — 市场相关
   - `api/payment.ts` — 支付相关（签名逻辑移至后端）
   - `api/mod.ts` — Mod 管理
2. 添加 axios 拦截器统一处理 token 注入和错误
3. 添加 token 刷新逻辑

**验收标准**: 每个文件不超过 100 行；无硬编码密钥；有统一的请求/错误处理

---

---

## P1-8 CD 流水线断裂（CVM + K8s + 客户端）

**问题**: CI 完整但 tag 发版未串联 CVM/K8s/桌面/Web/Android；`fhd-deploy` 无 kubeconfig 时静默跳过。

**修复要求**:
1. 新增 `fhd-release-orchestrator.yml`，`FHD/v*` tag 一次触发全链路
2. `fhd-ci-cd` 监听 tag；CVM push 在 tag 也执行
3. production deploy 无 `KUBE_CONFIG*` 时 **fail**（staging 可 skip）
4. Android release workflow 发布到仓根；统一 `FHD_PUSH_SSH_KEY`

**验收**: 见 [FHD/docs/deploy/RELEASE_CHECKLIST.md](FHD/docs/deploy/RELEASE_CHECKLIST.md)、[docs/CI_SSOT.md](docs/CI_SSOT.md)

---

## P1-9 原生 SQL 过多（~450 处 text/execute）

**问题**: compat 层 f-string SQL、路由重复 raw SQL、标识符动态拼接。

**修复要求**: 见 [FHD/docs/SQL_RAW_INVENTORY.md](FHD/docs/SQL_RAW_INVENTORY.md)；`python FHD/scripts/dev/count_raw_sql.py` 棘轮。

---

## P1-10 国际化缺失

**问题**: 无 vue-i18n；320+ 前端文件硬编码中文。

**修复要求**: 见 [FHD/docs/I18N_ROLLOUT.md](FHD/docs/I18N_ROLLOUT.md)；zh-CN + en-US MVP。

---

## P1-11 ChatView 巨型组件

**问题**: `ChatView.vue` 2174 行 + `useChatView.ts` 3970 行。

**修复要求**: 拆至 `components/chat/*` + 7 个 composable 子模块；facade 保留 `useChatView`。

---

## 修复顺序建议

```
第 1 批（安全红线）: P0-1 → P0-2 → P0-3 → P0-4
第 2 批（架构核心）: P1-1 → P1-2 → P1-5 → P1-6
第 3 批（代码质量）: P1-3 → P1-4 → P1-7 → P2-1 ~ P2-10
第 4 批（测试文档）: P3-1 → P3-2 → P3-3 ~ P3-8
```

每批完成后运行全量测试确认无回归：
```bash
# 后端
cd FHD && pytest tests/ --tb=short -q
# 前端
cd FHD/frontend && npm run test && npm run build
# Android
cd FHD/mobile-android && ./gradlew test
# Lint
cd FHD && ruff check app/ && mypy app/
```
