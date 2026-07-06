# XCAGI 全项目生产级升级打磨方案 — 2026-07

> 范围：**后端同源、前端差异化**的四端交付栈 —— FastAPI 后端（`FHD/app/`）、Vue SPA（`FHD/frontend/`）、Electron 桌面（`FHD/desktop/`）、双移动端（`FHD/mobile-android/`、`FHD/mobile-ios/`）。
> 原则：**保留产品定位与核心架构**（Neuro-DDD + FastAPI 单体 + Mod 生态 + 差异化客户端），只做加固、调优、完善，不推倒重来。
> 版本口径：**v10 全线锁定**，本方案所有工作均为 **v10 线内迭代**，任何锚点保持 `10.0.0`（[`FHD/VERSION.md`](../FHD/VERSION.md)）。
> 状态标记：✅ 本轮已落地（含测试证据） · 🔜 P1（下一轮承接） · 📋 P2（规划中）

---

## 0. 体检结论（2026-07-06 实测）

| 端 | 成熟度 | 主要生产风险 |
|----|--------|--------------|
| **后端** (~1051 py) | 高：DDD 四层落地、限流/CSRF/CSP/审计齐备、Alembic baseline 已 squash | 巨型文件（4 个 >2600 行）、`services/` 遗留双轨、OIDC 弱回退密钥、无响应压缩 |
| **前端** (171 vue) | 高：TS strict、ESLint 9、Vitest+Playwright、多 edition 构建 | `SettingsView.vue` 4113 行等巨型 SFC、`no-console: off` |
| **桌面** | 高：contextIsolation+sandbox、Ed25519 签名更新、回滚 | `openExternal` 无 scheme 白名单 |
| **Android** | 高：Compose 双 SKU、CI 绿、密码已 Keystore 加密 | WebView token 注入判定可被子串绕过（**凭证泄漏级**）、token 明文 DataStore |
| **iOS** | 中：44 Swift 文件、宣称对齐 20+ 屏 | 无 XCTest、版本锚点 1.0.0 与全线不一致、真机未验收 |

---

## 1. 本轮已落地（P0 安全 + 性能加固）✅

### 1.1 Android：WebView 凭证注入判定重写（凭证泄漏修复）

**问题**：`WebViewTokenScript.kt` 旧实现用子串匹配决定是否向页面注入登录凭证：

- `url.contains("xiu-ci.com")` → `https://evil.com/?xiu-ci.com` 可骗取 MODstore access/refresh token；
- `lower.contains("10.")` → `http://evil.com/10.html` 可骗取 FHD session cookie。

**修复**（`feature/web/UrlHostPolicy.kt`，纯 JVM 可单测）：

- market token：必须 **HTTPS + host 精确等于 `xiu-ci.com` 或其子域**；
- FHD session：必须 **http + host 为字面 loopback / RFC1918 私网 IPv4 / localhost**（严格 IPv4 八位组解析，`192.168.evil.com` 不再放行）；
- `ModWebViewScreen` / `DesktopToolWebView` 加载前强制 `isTrustedWebViewUrl()` 白名单（这两个容器会附带 `Authorization` 头），不信任 host 显示阻断提示；
- `WebViewUrlPolicy.isAllowed` 委托同一策略，顺带补全 10/8 与 172.16/12 网段。

**证据**：`UrlHostPolicyTest.kt`（JUnit，12 用例）+ kotlinc 独立运行 29 断言全 PASS（见 PR artifact）。

### 1.2 后端：OIDC state 弱回退密钥移除

**问题**：`oidc_provider._secret_key()` 在 SECRET_KEY 缺失/过短时回退硬编码 `"xcagi-dev-oidc-state-key"`——任何人可伪造 OIDC state 的 HMAC 签名（登录 CSRF / open-redirect 面）。

**修复**：与 `mobile_jwt.py` 同模式——进程级 `secrets.token_urlsafe(48)` 随机回退 + 一次性告警日志；生产仍由 `factory.py` 强制 SECRET_KEY。state TTL 仅 600s，重启损失可忽略。

### 1.3 后端：选择性 GZip 响应压缩（`app/middleware/conditional_gzip.py`）

**问题**：全站无响应压缩（Starlette 原生 `GZipMiddleware` 会逐块压缩流式响应，SSE 事件滞留压缩器缓冲导致 AI 对话流卡顿，因此一直没敢开）。大 JSON 接口（openapi.json 528KB、订单/产品列表）在 LAN/WAN 明文全量传输。

**修复**：自研 `ConditionalGZipMiddleware` —— 仅压缩**单块完整响应**（首个 body 即 `more_body=False`），流式/SSE 一律原样透传零缓冲；仅压缩 json/text/js/css/svg/xml；跳过已编码与 <1KB 响应；自动补 `Vary: Accept-Encoding`。注册于中间件洋葱最内层。

**证据**：9 个单测（压缩矩阵 + SSE 透传 + 多块流不缓冲）+ 全应用冒烟（openapi.json 压缩生效、/health 小响应不压缩、identity 客户端不压缩）。

### 1.4 桌面：`shell.openExternal` scheme 白名单

**问题**：`setWindowOpenHandler` 把所有非本机 URL 直接 `shell.openExternal(url)`——渲染进程一旦被 XSS，`window.open('file://...')` / `ms-msdt:` 等可触发本地文件浏览或任意协议处理器。

**修复**：新增 `isSafeExternalUrl()`（仅 http/https/mailto），拒绝时告警日志。8 个新 vitest 用例覆盖 file:/smb:/javascript:/自定义协议。

### 1.5 iOS：版本锚点对齐

`project.yml` 的 `MARKETING_VERSION` 从 `1.0.0` 对齐为 `10.0.0`（CI 脚本本就注入 10.0.0，本地 xcodegen 生成的工程此前不一致；v10 锁定规则要求全锚点恒 `10.0.0`）。

---

## 2. P1 路线图（下一轮承接）🔜

| # | 项 | 内容 | 验收 |
|---|----|------|------|
| P1-1 | **Android token 落盘加密** | `SessionStore` 中 `fhd_access/refresh`、`market_token`、`relay_session_token` 复用现有 `CredentialCipher`（AndroidKeyStore AES/GCM，已用于密码），读取兼容历史明文 | 新装/升级双路径单测；抓取 DataStore 文件确认密文 |
| P1-2 | **巨型路由/服务文件拆分** | `mobile_api_extensions.py`（4282 行）按域拆到 `fastapi_routes/domains/mobile/*`；`ai_chat_app_service.py`（3913 行）、`ai_group_chat_service.py`（3969 行）提取编排子模块。**URL 契约与对外行为不变**（遵守 `no-legacy-archive-names.mdc`） | `pytest tests/test_routes -q` 全绿；OpenAPI diff 为空 |
| P1-3 | **前端巨型 SFC 拆分** | `SettingsView.vue`（4113 行）按 Tab 拆子组件；`TopAssistantFloat.vue`、`ModStore.vue` 同法 | `vue-tsc` + vitest + Playwright smoke 全绿 |
| P1-4 | **生产构建剔除调试输出** | `vite/build.js` 增加 `esbuild.pure: ['console.log','console.debug']`（46 处残留一次性静默，dev 不受影响） | 构建产物 grep 无 console.log |
| P1-5 | **CSP connect-src 收紧** | `security_headers.py` 中 `connect-src 'self' ws: wss:` 的裸 `ws:` 允许连任意 WebSocket；改为按部署拓扑注入白名单（desktop=self，域名部署=self + 显式域） | LAN/桌面/云三拓扑回归 |
| P1-6 | **iOS XCTest 起步** | 为 `APIClient`、`SessionManager`、`APIEndpoints` 建纯逻辑 XCTest target（无 UI），接入 `release-ios.yml` | mac CI 跑绿 |

## 3. P2 规划 📋

- **services/ → application/ 迁移收尾**：126 个遗留服务文件按 `docs/MIGRATION_REGISTRY.md` 分批迁移，每批带 characterization test；
- **DB 双轨 schema 收敛**：Alembic 为唯一真源，`init_db.ensure_*` 运行时补齐逐步退化为断言 + 告警；
- **可观测性**：为 SSE 首字节（已有 `chat_stream_first_byte_seconds`）补 P95 告警规则；移动 API 加 per-domain SLI；
- **Android instrumented smoke**：Maestro surface-audit 纳入 nightly CI；
- **压测基线**：`/api/ai/chat/stream` 并发槽位与 `GlobalRateLimit` 配额的容量口径写入 `docs/reports/capacity-planning.md`。

---

## 4. 质量门禁（发版前必绿）

```bash
# 后端
cd FHD && python -m pytest tests/ -m 'not coverage_ramp' -q
# 前端
cd FHD/frontend && npm run type-check && npm run lint && npm run test
# 桌面
cd FHD/desktop && npx tsc --noEmit && npx vitest run
# Android
cd FHD/mobile-android && ./gradlew testEnterpriseDebugUnitTest lintEnterpriseDebug
# 版本锚点
python FHD/scripts/dev/verify_version_anchors.py
```

安全红线（增量）：

1. 任何向 WebView / 外部浏览器传递凭证或 URL 的代码，必须走 `UrlHostPolicy` / `isSafeExternalUrl` 白名单，禁止子串匹配；
2. 任何 HMAC/JWT 签名密钥禁止硬编码回退，缺配置时用进程级 `secrets.token_urlsafe` 并告警；
3. 新增流式端点必须验证经过 `ConditionalGZipMiddleware` 后仍逐块透传（复用 `test_streaming_multi_chunk_passthrough_unbuffered` 模式）。
