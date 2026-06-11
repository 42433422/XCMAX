# XCAGI 版本更新日志

> 从 v1.0 到 v10.0 的演进历程

---

## Unreleased（v10 线内迭代 · 技术债路线图 2026-06-07）

### AIOPEN 开放智控 — Qclaw龙虾生态 toA 升级（2026-06-11 · v10 线内迭代）
- **feat(aiopen)**：「Qclaw龙虾生态」更名升级为「AIOPEN 开放智控」（我是 AI 的工具）：面向外部 AI Agent 的 MCP + REST 开放平台与虚拟光标操控
- **feat(backend)**：`app/application/aiopen/`（`AIOPEN_STATE` SSOT、工具注册表、API Key 鉴权）+ `app/fastapi_routes/ai_open.py`（`/api/aiopen/manifest|invoke|mcp|keys|panel|whitelist|config|control`）；MCP 端点为手写轻量 JSON-RPC 2.0（initialize / tools/list / tools/call / ping），零新增依赖
- **feat(backend)**：`app/infrastructure/aiopen/cursor_hub.py` + `WS /api/aiopen/ws`：虚拟光标 screen 会话池，ui_snapshot / ui_navigate / ui_click / ui_type / ui_scroll 经 hub 下发并按 id 等待前端回执（10s 超时）
- **feat(frontend)**：`AIOpenPanel.vue` 控制台（接入信息 + Key 管理 + 工具目录/白名单 + 虚拟光标会话 + OpenClaw 联调原样迁入）；`VirtualCursorOverlay.vue` + `useAiOpenCursor.ts` 全局虚拟光标（动画移动 / 点击波纹 /「AI 操控中」徽标，真实派发 DOM 事件）
- **compat**：旧 `/api/ai/qclaw/*` URL 全部保留并共享新状态（`_QCLOW_RUNTIME_STATE` 即 `AIOPEN_STATE` 别名）；`is_qclaw_source` 增加 `aiopen` 别名；LAN/订阅门禁放行对外端点（安全由 `X-AIOPEN-Key` 承担）
- **docs**：`docs/aiopen.md` 接入指南（Cursor/Claude mcp.json、curl、虚拟光标指令协议）

### 移动端体验 P1（Android + Web · 2026-06-11 · v10 线内迭代）
- **fix(mobile-android,frontend)**：移除微信/抖音第三方登录占位入口（保留手机/企业账号/密码/扫码）
- **feat(frontend)**：`LoginView` 6 格 OTP 分格（`OtpCells`）
- **feat(mobile-android)**：`MarketListScreen` 简化 Mod 市场卡片（图标 + 名称 + 简介 +「使用」）
- **feat(frontend)**：`ModStore` 窄屏紧凑卡片；`DiscoverView` + `MobileBottomNav`（对话/发现/市场/我的）
- **feat(motion)**：Android `WeFadeTransition` / `WeMotion`；Web 路由 250ms fade + 按钮 active scale 0.98；`ChatView` 加载 spinner
- **fix(mobile-android)**：`HOME_HUB` / 未知深链重定向至 `CHAT`
### Android 移动端体验 P0（对标豆包/Kimi · 2026-06-11 · v10 线内迭代）
- **feat(mobile-android)**：登录手机号 Tab 默认 + 6 格 OTP 分格输入（`WeOtpCells`）；登录/发码加载态
- **feat(mobile-android)**：对话页 Kimi 风空态（欢迎语 + 3 推荐问题单列 chips）；工具栏收纳为「模式 + 联网 + 更多」BottomSheet
- **feat(mobile-android)**：4 Tab 切换 250ms 淡入淡出；流式回复 `CircularProgressIndicator`；统一 12dp 圆角 / 16dp 间距 tokens
- **note**：冷启动/登录后首屏已为 `Routes.CHAT`（无营销 Hero）；Web SPA 默认 `/` → `ChatView`

### Android 企业版微信风重构（2026-06-10 · v10 线内迭代）
- **feat(mobile-android)**：4 Tab 架构（对话 · 工作 · 发现 · 我的）；对话页 DeepSeek 式空态 + 模式胶囊 + 底部输入条
- **feat(mobile-android)**：浅色微信风主题（白底 + 灰分组 + GPT 灰点缀），跟随系统深色
- **feat(mobile-android)**：`WorkScreen` / `DiscoverScreen` 分组列表；`WeUi` 补充底栏、角标、输入条组件
- **feat(audit)**：`surface_audit_pages.json` 增加 `work` / `discover` 路由

### 日更闭环断点修复（BK→R / DRPROBE / 截图依赖 · 2026-06-10 · v10 线内迭代）
- **feat(backup)**：`daily_backup_job` 成功/失败派发 `backup.completed` / `backup.failed`；启动时 `register_backup_event_subscribers`
- **feat(dr)**：`dr_recovery_probe_job` 守卫生效时每 30min 重试（默认 ×8），成功 `backup.dr_guard.cleared`、超限 `backup.dr_guard.escalated`
- **feat(backup)**：`ondemand_backup` 按需快照；`auto_rollback` 回滚前自动抓取
- **feat(audit)**：`surface_audit_deps` 截图前自动拉起 FHD :5000、Vite :5001、MODstore :8788、Playwright（`MODSTORE_SURFACE_AUDIT_AUTO_START=0` 可关）
- **ops(closure)**：`.env.daily-closure` 模板 + 生产 `patch_prod_daily_closure.sh` / `dedupe_env_file.py`；`run_modstore_daily_local.sh` 加载生产同步 env

### 自进化闭环补强（MODstore · 2026-06-10 · v10 线内迭代）
- **feat(orchestrator)**：编排层 `ok` 收紧为 handler 输出验证；失败写入 `EmployeeExecutionMetric`
- **feat(ci)**：`cr_narrow_ci` 窄验证（py_compile + 可选 ruff + pytest 子集）；自动审批前门禁；失败喂 `evolution-engine`
- **feat(signals)**：`evolution_signal_collector` 注入 vibe 预备（pytest / incident / post_deploy_smoke）
- **feat(rollout)**：`line_rollout_policy` P-S 灰度 primary + CR 日预算 + 通过率门禁
- **feat(evolution)**：`prompt_evolution_ab` 影子 A/B 回放 + prompt override 自动应用/还原
- **feat(cursor)**：`cursor_delegate_handler` P0/P1 接 Cursor SDK / Webhook 真执行

### 表面巡检截图链路修复（SW / SS / SA · 2026-06-10 · v10 线内迭代）
- **fix(audit)**：`run_surface_audit.mjs` P-S 共享上下文 `console_errors` 跨页累积修复——每页只归属本页新增错误，不再滚雪球误报
- **fix(audit)**：`surface_audit_service._node_env` P-W 分支 `setdefault` 失效修复——P-W 刷新此前会打到本地 5000/5176 而非 xiu-ci.com；显式进程环境仍可覆盖
- **feat(audit)**：远程导航 `gotoWithRetry`（domcontentloaded 失败降级 commit 重试一次）+ 导航失败时兜底截当前屏；`analyzePage` 区分「导航异常」与控制台错误
- **perf(audit)**：`waitForCjkFonts` 每页等待收紧（networkidle ≤10s、字体轮询 ≤5s、固定等待 1.2s）；P-W 默认总超时 600s→1200s——此前全量 60+ 页必超时（实测端到端 686s 完成 58 页、仅 1 页网络抖动失败）
- **fix(dashboard)**：`emp-wf-surface-audit.js` `openGallery` 回退分支死代码修复——fetch 后等待 `MonAiBiz` 挂载（≤3s）再开画廊
- **test(audit)**：`test_surface_audit_service.py` 断言对齐现行 `surface_audit_pages.json`（P-W 49 页 / P-App 6 原生屏）；`test_surface_audit_demo_market_login.py` 导入路径改 `app.fastapi_routes.market_account`

### 官网 / MODstore 生产修复（2026-06-10 · v10 线内迭代）
- **fix(site)**：`ensure_market_dist` 并入 `main`；`modstore.service` 示例与 `align_modstore_systemd_to_deploy.sh` 默认路径对齐 `/root/XCMAX/…/MODstore_deploy`
- **fix(market)**：补入库 `providerCredential.ts`，修复 `main` 上 `npm run build` 缺文件

### 部署工程化（2026-06-08 · v10 线内迭代）
- **Phase 2 compose 双模**：CI `docker-build-fhd-api` 构建 `xcagi-fhd-api` 推 GHCR（`sha-<git_sha>` 标签）；manifest v2 含 `image` / `image_digest`；`fhd-apply-release-compose.sh` + `docker-compose.fhd-prod.yml`（digest 钉扎、5100→5000）；`fhd-auto-update.sh` 按 `deploy_mode` 路由
- **tarball 拉取式发布链**（Phase 1 默认）：`fhd-pack-release.sh` → `fhd-push-release.sh` → 服务器 `fhd-auto-update.sh` cron → `fhd-apply-release.sh`（健康检查 + 自动回滚）
- **fix(ci)**：移除 PyPI 不存在的 `types-python-dotenv`；bump `python-dotenv`/`gevent`/`gunicorn` 过 safety；arch baseline +45；npm cache 路径 `FHD/frontend/package-lock.json`
- 打包前强制 `verify_version_anchors.py`；制品含 `git_sha` + `sha256` manifest
- 替代生产机 `git_auto_update.sh`：`fhd-install-server-cron.sh` 幂等安装 cron
- CI `pack-verify` job：锚点校验 + 打 server tarball + Actions artifact（不含生产 SSH key）
- 发布 tag 统一为 `FHD/v10.*`；runbook 见 [`docs/CI_SSOT.md`](../../docs/CI_SSOT.md)
- **fix(db)**：`sqlalchemy.inspect(engine)` 支持 `_EngineProxy`，修复生产 tarball 启动 `NoInspectionAvailable`
- **fix(deploy)**：Mod 分库无 CREATEDB 权限时不阻塞主库启动；补全 `app/services/contract_lifecycle.py`；apply 回滚不再覆盖 deploy 脚本

### 仓根 SSOT（2026-06-08）
- Git 起源迁至 [`42433422/XCMAX`](https://github.com/42433422/XCMAX) 根仓；`FHD/`、`MODstore_deploy/` 为子路径
- CI 调度统一在根 `.github/workflows/`（见 [`docs/CI_SSOT.md`](../../docs/CI_SSOT.md)）
- `WechatDecrypt` 去 gitlink，纳入普通文件；子仓 `.git` 备份于 `~/XCMAX-archives/nested-git-backup-20260608/`

### 尽调治理（2026-06-08 · v10 线内迭代）
- **许可证**：`LICENSE` 全文对齐 **Apache-2.0**；README / LICENSING / 商业文档社区版表述一致
- **安全红线**：`git rm --cached` MODstore `payment_orders/order_*.json`（10 个）；`.gitignore` 补 `payment_orders/`、`.env.fhd-docker`；[`SECURITY.md`](SECURITY.md) 增密钥轮换 / 历史扫描 / 投资前 gitleaks 指引
- **覆盖率诚实口径**：`full_app` **60.63%**（SSOT）；CI 窄包 **70%**；修正 CLAIMED / 周报误报 ≥88%
- **口径对齐（2026-06-10）**：Android **实验骨架**（非签约级）；`*_v2` **23 个保留**（禁止宣称已清零）；README / VERSION / W24 周报同步；Android Kotlin 编译修复（Routes / MobileTokens / ServerRouter / 审批详情）

### 仓卫生 / 安全（2026-06-08 · v10 线内迭代）
- 自 Git 索引移除 `frontend/.nm-e2e/` 依赖缓存（~11k 文件）；`.gitignore` 已覆盖 `.nm-*` / chroma / `.der`
- 非 example 的 `.env*`、`secret.yaml`、chroma/`.der` 出仓；补 `START_HERE.md`、`MIGRATION_v2_DROP_PLAN.md`、`XCAGI/k8s/secret.yaml.example`
- 轻量 smoke CI：`FHD/.github/workflows/test.yml` → 根 `fhd-test.yml`（Ruff + pytest 路由烟测 + 前端 lint/Vitest smoke + 仓卫生守卫）
- 恢复只读校验 `scripts/dev/verify_version_anchors.py`（v10 锚点 `10.0.0`）

### 技术债（记录，非本批大规模重构）
- 遗留 `*_v2` 应用服务与占位实现：见 [`docs/MIGRATION_v2_DROP_PLAN.md`](docs/MIGRATION_v2_DROP_PLAN.md)
- 宽泛 `except Exception`、自动生成桩代码：优先在新改动中收紧；存量按模块逐步替换

### 行业引导 / Mod SSOT（Phase 2）
- 行业包中性 mod id：`attendance-industry` / `coating-industry`（`industry_baseline.json` 仅改 `mod_id`）
- 客户品牌迁入 `config/customer_delivery.json`；legacy 别名见 `config/industry_mod_aliases.json`
- `FHD/mods/attendance-industry/` 自 export 迁入；`coating-industry` 占位 stub
- `mod_manager.resolve_mod_directory` 支持 legacy → 中性目录解析

### 桌面（企业版）
- 修复企业版 macOS 桌面打不开：`legacy_vo.py` 改用标准 `import` 替代 PyInstaller 下失效的 `importlib` 按路径加载 `value_objects.py`，后端可正常监听 5000 并出窗
- 修复 macOS 白屏：默认桌面端口改 `17500`（避开系统隔空播放占用的 5000）；出窗前须 `/api/health` 返回 uvicorn，不再仅凭 TCP 误判 AirTunes 空 403
- 修复桌面端前端 chunk 404 / CSS MIME 报错：Electron 缓存键纳入 `index-*.js` hash；本机任意端口注销 Service Worker
- 修复 macOS 桌面顶栏异常：登录页不再挂载 Legacy 浮层；全屏恢复后窗口拉回工作区；Electron 壳标记 `xcagi-electron-mac` 稳定 top-bar 布局
- 修复 macOS 桌面登录页顶栏大图：桌面壳隐藏 `xc-logo-text` 角标，窄屏 Web 改用小图标 `xc-logo-base` 并加 inline 尺寸兜底
- 智能对话悬浮窗：入口与标题栏改为纯文字「智能对话」，移除宽幅 `brand-xc-logo` 图（避免拖至顶栏后撑满）
- 修复 macOS 系统菜单栏大图：`Tray` 不再注册到菜单栏右侧（与 Cursor 一致，仅左上角「XCAGI」文字应用菜单 + Dock）
- 恢复登录页右下角品牌角标（`login-panel-logo` 64px），桌面壳不再误隐藏

### ⑤ 可观测性 / K8s
- k6 SSOT 同步脚本 `scripts/observability/sync_k6_configmap.sh` + `k8s/monitoring/k6-configmap.yaml`
- Prometheus/Loki PVC 化、Promtail DaemonSet、镜像 pin、`STAGING_RUNBOOK.md`
- Loki boltdb → TSDB（schema v13）
- Helm Chart 脚手架 `helm/xcagi/` + `helm_lint.sh`

### ② 前端类型
- `api/core.ts` 默认泛型 `unknown`；`auth.ts` 缩 `any`

### ① 兼容层
- `COMPAT_LAYER_INVENTORY.md`；`app_service_pair_registry` 补登 order/purchase/inventory

### ④ 测试
- `tests/fixtures/app_factory.py`、`tests/README.md`；`collect_ignore` → 显式 skip 片段
- 视图 Vitest：`LoginView.test.ts`、`SettingsView.test.ts`
- 管理端侧栏：`ADMIN_OPERATOR_AUX_MENU_ITEMS` 恢复「内部客服」等运维入口（企业 trailing 仍为空）
- 管理端导航：侧栏走宿主 route（`HostModBridgeView`），不再误跳 `/mod/*`；Mod routes glob 含 `mods-admin-runtime/`
- 后端 stub：`app/services/wechat_group_customer_bridge.py`；ERP Mod 补 `wechat_contacts/decrypt_status`
- 登录 500：`User.mfa_enabled` 与 SQLite 表对齐，企业账号 JIT 建本地用户不再触发 NOT NULL 错误
- **登录体系四线升级（v10 线内）**：市场代理 `XCAGI_MARKET_HTTP_TIMEOUT/RETRIES`；Web 手机验证码 + PC 扫码 + OIDC SSO；`enterprise_login_flow` 统一后置；`Tenant`/`tenant_context` 登录绑定 `tenant_id`；Android `login-with-phone-code` / `auth/qr/confirm` / `auth/oidc/exchange`
- 企业 dev：`VITE_XCAGI_PRODUCT_SKU=enterprise` 时 Vite 用 generic 空 mod glob，不再误扫 `mods-admin-runtime/`；管理端仍走 `adminConsole.vite.config.js` full
- 企业桌面与网页对齐：安装包前端改 `generic` + bake `VITE_XCAGI_PRODUCT_SKU=enterprise`；Electron 企业 SKU 不再 `?shell=1`，后端 `XCAGI_PLATFORM_SHELL=0`

### ③ ORM
- `app/db/mixins.py`；customer/purchase_unit/product/shipment 试点
- Alembic `2026_06_07_audit_timestamp_backfill`；移除全库 `sqlite_autoincrement`

### 工具链
- Ruff `ANN201` 已评估，待测试收口后分批启用（避免全库 CI 红）

---

## 版本总览

| 版本 | 状态 | 核心升级 |
|------|------|----------|
| **v1.0** | 稳定 | Excel 解析 + 标签打印 |
| **v2.0** | 稳定 | Vue 3 + AI 对话 + OCR |
| **v3.0** | 稳定 | 混合意图引擎 + TTS + 任务 Agent |
| **v4.0** | 稳定 | AI 员工定位 + 全自动流程 + 多模态交互 |
| **v5.0** | 稳定 | Neuro-DDD 架构 + 小程序 + 性能监控 + 审批流 |
| **v6.0** | 稳定 | **商业模式明确 + 三层收入 + Mod 生态** |
| **v7.0** | 稳定 | **Windows/macOS 桌面版 + Web 版并行交付 + 自动更新** |
| **v8.0** | 稳定 | **跨行业 UI 适配 + Mod 制作端行业选择 + 平台壳 V8** |
| **v10.0** | 🚀 当前最新 | **版本锁死 + 工程纪律整固 + Flask 遗留清除 + DI 类型安全** |

---

## v10.0.0 (2026-06-07) - 版本锁死 + 工程纪律整固

### 🔒 版本统一

- **全仓版本锁死为 `10.0.0`**：消除 FHD 主线 (8.0.0) 与 XCAGI 子树 (10.0.0) 的版本分裂，8 个锚点文件统一对齐。
- **Mod 依赖基线**：`app/infrastructure/mods/manifest.py` 从 `8.0.0` 升级到 `10.0.0`，与所有 Mod manifest 的 `xcagi >= 10.0.0` 声明对齐。
- **修复不一致版本**：`factory.py` 默认版本从 `9.0.0` 改为 `10.0.0`；`setup.iss` 从 `3.0.0` 改为 `10.0.0`；`release/VERSION` 从 `0.0.1` 改为 `10.0.0`。

### 🧹 Flask 遗留清除

- **全仓 `FLASK_ENV` → `XCAGI_ENV`**：Docker、docker-compose、K8s、打包脚本、部署文档共 16 个文件完成替换。
- **全仓 `FLASK_DEBUG` → `XCAGI_DEBUG`**：开发环境配置完成替换。
- **Docker 端口统一**：`5000` → `8000`（FastAPI/Uvicorn 标准端口）。
- **gunicorn worker 修正**：添加 `-k uvicorn.workers.UvicornWorker`，与 FastAPI ASGI 框架匹配。

### 🛡️ 安全与质量修复

- **`datetime.utcnow` 废弃修复**：4 个文件共 11 处替换为 `utc_now_naive()`（基于 `datetime.now(UTC)`）。
- **DI 容器类型安全**：`ServiceContainer` 所有 property 返回类型从 `Any` 改为具体类型，使用 `TYPE_CHECKING` 避免循环导入。
- **模型循环依赖修复**：`ai.py` 末尾 `E402` import 替换为 `TYPE_CHECKING` 块。
- **session.py 线程安全**：查询缓存添加 `threading.Lock`、TTL 过期检查、SHA256 替代 MD5。
- **ruff BLE001 收紧**：从 25 个目录豁免缩减到仅 2 个（legacy + traditional_mode_fs）。

### 📦 工具链集成

- **pre-commit 增强**：新增 `black`（代码格式化）、`isort`（导入排序）、`mypy`（类型检查）钩子。
- **SECURITY.md 更新**：支持版本表更新到 10.0.x，安全特性描述与实际代码对齐。

---

## v8.0.0 (2026-05-21) - 跨行业适配

- **行业预设**：宿主与 Mod 制作端共用 `industryPresets`（通用、涂料、考勤、烤禽、批发等），菜单/欢迎语/快捷按钮随所选行业切换。
- **Mod 源码库**：新建 Mod 与制作页可指定目标行业，写入 `manifest.industry` 与 `config/industry_card.json`。
- **版本锚点**：前后端与桌面壳统一为 `8.0.0`；Mod 依赖基线 `>=8.0.0`。

---

## Unreleased

### 生产化与部署一致性（v10 线内迭代 · 2026-06-07）

- **Gunicorn SSOT**：`gunicorn_config.py` 统一 `uvicorn.workers.UvicornWorker`；Dockerfile/compose 不再 CLI 覆盖。
- **端口 5000**：根 `docker-compose.yml` 修复 `8000` 映射/探针；dev `EXPOSE` 与文档脚本对齐 5000。
- **Compose 安全**：生产 compose 强制 `SECRET_KEY` / `POSTGRES_PASSWORD` / `REDIS_PASSWORD`；Grafana 密码可配置；新增 `.env.production.example`。
- **桌面构建**：`desktop/package.json` 锁定 electron/typescript 等依赖版本 + `package-lock.json`。
- **static/ 迁移**：`index.html` 默认停载 legacy JS；删除已 Vue 替代的 static 模块；`App.vue` 拆为 `StartupSplash` / `LegacyFloatPanels` / `AppGlobalProviders`。
- **路由下沉**：`domains/db` → `infrastructure/persistence/compat_db`；`approval` / `excel_templates` / `inventory` HTTP 薄层 + 应用服务。
- **NeuroBus**：可选 `XCAGI_NEURO_BUS_REDIS_PUBSUB` Redis Pub/Sub 跨进程桥。
- **前端覆盖率**：Vitest gate 50%（聚焦已单测模块）；补 `useAppShellBridge` / `StartupSplash` 等单测。
- **K8s 可观测性**：`ServiceMonitor` / `PrometheusRule` CRD + `xcagi-slo.json` dashboard。
- **文档**：关键指南对齐 v10.0.0；`scripts/dev/verify_doc_versions.py`。

### 技术债清偿（v10 线内迭代 · 2026-06-07）

- **路由 SSOT**：`fastapi_routes/__init__.py` 拆分为 `mounts/*` + `RouteRegistry`；删除 `aibiz_terminal` 双注册；`xcagi_compat` 为唯一 compat 层（legacy_gap 仅 `XCAGI_REGISTER_LEGACY_ROUTES=1` 时可选挂载）。
- **Redis 安全**：`redis_cache.py` 移除 pickle；分布式锁改 token + Lua compare-and-del；Redis 不可用时锁返回 false。
- **K8s 安全基线**：`deployment.yaml` 修复 YAML 结构并加 SecurityContext；新增 `pdb.yaml` / `networkpolicy.yaml`；`secret.yaml.example` 替代明文 Secret 入 kustomize。
- **查询缓存**：新增 `app/db/session_cache.py` `ThreadSafeLRUCache`；`session.py` 支持 `XCAGI_QUERY_CACHE_BACKEND=redis`。
- **依赖 SSOT**：`requirements.txt` 仅生产运行时；ML 依赖迁至 `requirements-ml.txt`；测试依赖仅 `[dev]` extra。
- **质量门禁**：CI mypy 硬失败；后端 coverage **M3 `fail_under=70`**（M2 55% 已过渡）；前端 vitest 40% + `vue-tsc`；Codecov 失败阻断。
- **API 信封**：`app/` 与 `mods/` JSON 响应 `"ok"` 全量迁移为 `"success"`；`response_envelope.py` SSOT + `read_success()` 兼容旧客户端。
- **前端**：生产构建默认禁用 legacy `chat.js`；`vite.config.js` 拆至 `frontend/vite/` 子模块。
- **部署**：`deploy.yml` / `deploy.sh` 支持 `rolling|blue-green|canary` 策略；删除遗留 `app/fastapi_app.py` 单体文件。

### Mod SSOT（v10 线内迭代）

- 约定 **`FHD/mods/` 为唯一编辑源**，`FHD/XCAGI/mods/` 为导出副本；新增 `scripts/dev/mods_ssot.py`（`sync` / `check`）与 `scripts/dev/sync-mods-to-xcagi.sh`；更新 `MOD_AUTHORING_GUIDE` 与 `FEATURE_MAP`。
- 管理端「员工工作流管理」：`modsForWorkflowUi` 修复 admin SPA 误报「未加载工作流员工 Mod」；`OtherToolsView` 展示已安装员工开关列表。

### 工程质量（v10 线内迭代）

- **K8s**：`FHD/k8s/deployment.yaml` 与 `Dockerfile` 监听端口统一为 **5000**，与 Service `targetPort`、gunicorn 一致，修复探针与流量错位导致的 NotReady。
- **前端**：`App.vue` 拆分为 `useAppBoot` / `useStartupSplash` / `useStartupAuth` / `useAppProMode` / `useAppShellBridge`，`window` 桥接集中管理；补 `startupRedirect`、`useStartupSplash`、`useAppProMode` 单测。
- **CI/CD**：`ci-cd.yml` 增加 Ruff、前端 ESLint、Trivy 镜像扫描、requirements lock 校验；安全扫描改为阻塞；tag 发版串联 `deploy.yml`。
- **依赖**：`pyproject.toml` 声明 `server-api` / `ml` / `dev` extras；新增 `deploy/requirements-server-api.lock.txt`、`deploy/requirements-dev.txt`。

### 管理端路由（v10 线内迭代）

- 修复 admin-console 启动时 platform shell 过滤掉 `xcmax-admin` 等运维路由，导致 `No match for xcmax-admin` 与侧栏点击无响应；管理端 bootstrap 强制关闭壳模式，`resolveInitialRoutes` 在 admin SPA 下保留全量路由。
- 补全管理端缺失模块 `personnelModApi`、`modstoreDutyRosterIds`，修复 `XCmaxAdminView` 动态加载 500。
- 管理端（admin-console）跳过局域网密钥弹窗：路由守卫不再拦截 `hostAdmin` 页，且不挂载 `GlobalLanGateModal`。
- 管理端跳过开屏动画与 startup 音效请求，修复 `startup-enter.mp3` 在 `:5011` 上 404；开屏资源路径统一带 `BASE_URL`。
- 恢复 `ops_closure_status` / `duty_roster` 与 `config/duty_roster.json`，修复 `/api/xcmax/ops/duty-health`、`closure-status` 500。
- FastAPI 挂载 `/xcmax-dashboard` 全景 HTML；LAN 静态前缀与 `X-Frame-Options: SAMEORIGIN` 放行 iframe 嵌入。
- 品牌 logo 缺失时侧栏/悬浮窗回退 `vite.svg`；管理端将 `/mod/xcagi-planner-bridge/*` 重定向至宿主路由。
- 修复管理端「服务器功能模块」等运维页点击后仍显示智能对话：运维五页改同步 import（`adminHostRoutes.ts`）、管理端禁用 keep-alive、侧栏 routeNameMap 补全、`document.title` 改在 afterEach 设置。
- 管理端侧栏移除冗余「同时完成时间架构」入口（保留 `automation-policy` 内嵌）；`modsForUi` / bootstrap 清除太阳鸟 active mod，顶栏与侧栏底不再展示「普通版·太阳鸟pro」及 Mod chip。

### AI 业务数据 Tab（v10 线内迭代）

- 注册 `aibiz_terminal_api` 路由（`/api/xcmax/aibiz/web-terminal|desk-terminal|app-terminal|surface-image|surface-page`），修复全景仪表盘 `:8765` 直连 FHD `:5100` 时的 404。
- CORS 默认白名单增加 `:8765`（全景仪表盘）、`:5100/:5101`（FHD 开发端口）。
- 修复 `aibiz_web_terminal_service` 错误 import 路径（`market_account` 模块）。
- `market_account._proxy_json` 本地 MODstore 请求禁用系统代理（`trust_env=False`），避免 admin 登录 502。
- 修复 `prometheus.local.yml` 误建为目录导致 Docker Prometheus 无法启动；恢复 `serve_static_cached.py` 的 `/prometheus` `/metrics` `/grafana` 反代。
- 恢复 `operations_line_bridge.compute_operations_health`；`xcmax_admin` 本地 MODstore 读 daily-digests / artifacts / action-items（admin 服务账号，无需 FHD 登录）。
- `surface-image`：今日 JSON 缺 `screenshot_saved` 时，按 page id 回退至 `data/surface_audit/png/<lane>/<date>/` 历史 PNG，修复 Web 终端轮播破图。
- 运维终端：`xcagiDashboardEmbed` 改为 `/xcmax-dashboard/XCAGI-Full-Pipeline.html?embed=shell#aibiz`；新增 `FHD/scripts/dev/deploy_xcagi_dashboard_server.sh` 部署全景静态 + nginx 到公网 CVM。
- 运维终端：移除 SSH/密码提示条（`AdminOpsTerminalView` · `ops-ssh-bar`）。

### 🧹 技术债务清理 — Legacy 与 Archive 代码分期拆除

- **Phase 0（已完成）** 基础设施 + 修复幽灵引用
  - 修复 `app/fastapi_routes/xcagi_compat.py` 对不存在的 `app.legacy.product_name_resolve`
    的惰性 import 分支，改为返回 501。
  - 新增 `app/legacy/_deprecation.py`：`emit_legacy_usage` + Prometheus counter
    `fhd_legacy_module_usage_total` + JSONL 日志 `logs/legacy_usage.log`。
  - `app/legacy/__init__.py` 增加 `__getattr__` 钩子，首次属性访问触发遥测。
  - `archive_gap_batch1/2.py` 启动阶段输出承载路由数的 `[legacy-cleanup]` 日志。
  - 新增 `scripts/dev/legacy_usage_report.py`：解析 JSONL 出报告，支持 `--since` / `--json`。
  - 新增 `docs/reports/LEGACY_CLEANUP_TRACKING.md` 跟踪看板。
- **Phase 1（已完成）** 零引用 legacy 文件删除
  - 删除 `app/legacy/_fix_thinking.py`、`ai_model_registry.py`、`chat_idempotency.py`、
    `http_rate_limit.py`、`http_request_context.py`、`llm_circuit_breaker.py`、
    `torch_runtime_env.py`、`template_api.py`（共 8 个，全部确认零引用）。
- **Phase 2（已完成）** `archive_*` 命名工程上全部清除 + 按业务域拆分
  - 新增 `app/fastapi_routes/ai_intent.py`（intent/chat-unified/test）、
    `ai_kitten.py`（Kitten 分析 13 条路由）、`ai_qclaw.py`（Qclaw 7 条路由 + `_QCLOW_RUNTIME_STATE` 权威位置）、
    `spa_fallback.py`（Vue SPA history fallback）。
  - `app/utils/openapi_path.py`：`url_rule_to_openapi_path` / `normalize_path_template`
    搬出 archive_explicit_proxy。
  - 删除 `app/fastapi_routes/archive_explicit_proxy.py`（工具函数已搬走）；
  - 重命名 `app/routes/archive_templates_compat.py` → `app/routes/document_templates_compat.py`；
  - 重命名 `app/services/archive_templates_legacy.py` → `app/services/document_templates_service.py`；
  - 重命名 `app/fastapi_routes/archive_gap_batch1/2.py` → `app/fastapi_routes/legacy_gaps_batch1/2.py`，
    router tag 同步更新为 `legacy-gaps-batch1/2`；
  - 调用方同步更新：`scripts/route_inventory_diff.py`、`scripts/check_openapi_consistency.py`、
    `scripts/dev/smoke_all.py`、`tests/test_routes/test_ai_chat.py`、`app/fastapi_app.py`、
    `app/routes/wechat_miniprogram.py`、`app/services/tools_execution_service.py`、
    `app/routes/template_grid_core.py`。
  - **总路由数从 536 → 536**，前端 URL 契约零变化。
- **Phase 3 / 4 / 5（已完成）** 按分层建立适配层 facade，xcagi_compat 不再直接依赖 `app.legacy.*` 枢纽
  - `app/infrastructure/workspace.py`、`app/infrastructure/request_context/client_mods.py`、
    `app/domain/ai/tier.py`、`app/domain/ai/tools_directory.py`、
    `app/domain/context/session_context.py`、`app/application/workflow/legacy_chat_adapter.py`、
    `app/application/tools/__init__.py`（含 `handle_price_list_export` lazy 转发）、
    `app/infrastructure/db/sync_engine.py`、`app/infrastructure/auth/db_token.py`、
    `app/infrastructure/llm/client.py`。
  - `app/legacy/request_active_mod_ctx.py` 直接删除（其余 5 处引用切到 `app.request_active_mod_ctx`）。
  - `app/services/archive_tools_legacy.py` → `app/services/tools_execution_service.py`
    （最后一个 `archive_*` 命名运行时模块消失）。
  - 路由与脚本调用点同步切到新位置，`app/legacy/*` 残留文件转为 shim 留待 Phase 6 后续批次删除。
- **Phase 6（已完成）** 看守规则 + 发布说明
  - 新增 `.cursor/rules/no-legacy-archive-names.mdc`：在 Cursor 中硬性禁止再添加
    `app/legacy/*` 新模块、`archive_*` 前缀文件、`from app.legacy.*` import 等。
- **终态吸收（已完成）** 实现搬入目标层 + 目录整除
  - 所有 legacy 枢纽与基础设施的实现 **真正从 `app/legacy/` 搬到目标层**：
    `app/application/tools/workflow.py`（吸收 `tools.py`）、
    `app/application/workflow/legacy_chat_adapter.py`（吸收 `planner.py`）、
    `app/domain/context/session_context.py`（吸收 `runtime_context.py`）、
    `app/infrastructure/db/sync_engine.py`（吸收 `database.py` + `mod_database_url.py`）、
    `app/infrastructure/auth/db_token.py`（吸收 `db_read_auth.py` + `db_write_auth.py`）、
    `app/infrastructure/llm/client.py`（吸收 `llm_config.py`）、
    `app/infrastructure/documents/{template_registry,sales_contract_excel,price_list_export}.py`、
    `app/infrastructure/products/{db_read,customer_matching}.py`、
    `app/infrastructure/excel/{schema_service,text_to_pandas}.py`、
    `app/infrastructure/attendance/{dingtalk_convert,workspace_paths}.py`、
    `app/infrastructure/workspace.py`、`app/infrastructure/request_context/client_mods.py`、
    `app/infrastructure/db/schema_auto_init.py`（修复 `parents[1]/scripts` 的路径漂移）、
    `app/domain/ai/{tier,tools_directory}.py`、`app/application/excel_imports.py`。
  - **删除整个 `app/legacy/` 目录**（24 个 shim + `__init__.py` + `_deprecation.py`）。
  - **删除整个 `tests/backend_legacy/` 目录**（35 个测试文件，其验证对象已随 legacy 一同下线）。
  - 本次清理的详细进度与完整度量见 `docs/reports/LEGACY_CLEANUP_TRACKING.md`。

### 🩺 API 文档 / 路由一致性守护

- **新增** `scripts/check_openapi_consistency.py`：对 FastAPI 运行时路由与
  `/openapi.json` 双向 diff，分级（error/warn/info）输出，支持 `--md-out` /
  `--json-out` / `--ignore-regex` / `--strict`。
- **新增** `tests/test_openapi_consistency.py`：将 error 级发现纳入 pytest，
  作为 CI 守门员，并单独覆盖 "`app.openapi()` 能否无 PydanticUserError 地生成
  schema" 的回归场景。
- **新增** `docs/guides/OPENAPI_CONSISTENCY.md` 使用指南 & 修复套路。
- **修复** `app/neuro_bus/route_event_publisher.py::publish_route_event`：
  在 `from __future__ import annotations` 语义下，装饰器把 BaseModel 参数退化
  为 Query 导致 OpenAPI 生成抛 `PydanticUserError` 的问题。方法是在包装时用
  `typing.get_type_hints()` 预解析并回写到 wrapper 与原函数的 `__annotations__`。
- **修复** 4 处 `(method, path)` 跨模块重复注册（隐藏兼容 stub，不改变运行时
  行为）：
  - `/api/system/industries`、`/api/system/industry` GET/POST —
    `app/fastapi_routes/xcagi_compat.py` 中的兜底 stub 改为
    `include_in_schema=False`，业务实现保留在 `system_routes.py`。
  - `/api/health` — `ai_assistant.py::compat_health` 改为
    `include_in_schema=False`，文档版本由 `fastapi_routes/__init__.py` 提供。
  - `/api/lan/admin/settings` GET/POST/PUT — `lan_admin_routes.py` 中的
    被覆盖版本改为 `include_in_schema=False`，保留 `lan_settings_routes.py`
    中带 `LanSettingsView` 响应模型的规范实现。
- **效果**：`error=0`（之前 OpenAPI 根本生成失败）、FastAPI
  `Duplicate Operation ID` 警告全部消除。

---

## v7.0.0 (2026-04-29) - 🖥️ 桌面化时代

### 🎯 重大定位升级

**从「Web 企业 AI 员工平台」升级为「桌面版 + Web 版并行的企业 AI 员工平台」**

- **桌面版**：新增 [desktop/](desktop/) Electron 壳，启动本地 FastAPI 子进程，Windows / macOS 双平台交付。
- **Web 版保留**：Docker Compose / Nginx / 局域网部署路径不下线，继续服务企业自托管和开发调试。
- **混合模式**：本地处理 Excel、出货、打印、OCR 与核心业务；云端继续承载 Token 钱包、Mod 商店和重型 AI。
- **自动更新**：接入 electron-updater 自建 update server 模板，支持差量包、通道、灰度、强制升级和失败回滚设计。

### 🆕 新增核心能力

| 能力 | 说明 |
|------|------|
| Windows / macOS 桌面壳 | `desktop/main.ts` 管理窗口、托盘、菜单、后端子进程、自动更新入口 |
| 桌面运行时 | `app/desktop_runtime/` 提供 userData 路径、SQLite 默认、内存缓存、线程队列、模型下载、数据迁移入口 |
| 桌面 API | `/api/desktop/status`、`/api/desktop/models`、`/api/desktop/models/download` |
| 桌面运行时页面 | `frontend/src/views/DesktopRuntimeView.vue`，web 与桌面共用 |
| 打包脚本 | `scripts/package/build-backend.*`、`build-installer.*`、`release-web.ps1` |
| CI 发布 | `.github/workflows/release-desktop.yml` 与 `release-web.yml` |
| update server 模板 | `update-server/` 提供 Nginx 与 latest.yml/latest-mac.yml 模板 |

### 🔧 技术升级

```bash
# Windows 桌面安装包
powershell -ExecutionPolicy Bypass -File scripts/package/build-installer.ps1 -Version 7.0.0

# macOS 桌面安装包
bash scripts/package/build-installer.sh 7.0.0

# Web 版继续走 Docker
docker-compose pull && docker-compose up -d
```

### ⚠️ 注意事项

- 桌面安装包正式发布前必须准备 Windows 代码签名证书与 Apple Developer ID；无证书构建可用于内部验证，但会触发系统信任提示。
- AI 大模型不放进安装包，仍按需下载到系统 userData 目录。
- `XCAGI_DESKTOP_MODE=1` 才会启用 SQLite / 内存缓存 / 本地线程队列；默认 web 模式保持 PostgreSQL + Redis + Celery。

---

## v6.0.0 (2026-04-17) - 💰 商业时代

### 🎯 重大定位升级

**从「AI 单据智能处理系统」升级为「企业 AI 员工平台」**

- 💰 **商业模式明确** - 本地部署 + Mod 商店 + Token 付费
- 🏪 **员工商店** - 第三方/官方行业 Mod 付费下载平台
- 🔑 **认证钱包** - AI 能力按量计费，持续性收入
- 🔄 **生态飞轮** - Mod 越多 → 用户越多 → Token 消耗越多 → 开发者越多

### 🆕 新增核心能力

| 能力 | 说明 | 重要性 |
|------|------|--------|
| **三层收入结构** | 本地部署授权 + Mod 商店分成 + Token 消耗 | ⭐⭐⭐⭐⭐ |
| **Mod 生态系统** | 热插拔、行业配置覆盖、Manifest 清单 | ⭐⭐⭐⭐⭐ |
| **Token 认证钱包** | 按量计费、套餐管理、用量监控 | ⭐⭐⭐⭐⭐ |
| **防绕过机制** | 核心 AI 云端化、License 验证、签名校验 | ⭐⭐⭐⭐ |
| **开发者激励计划** | 70% 分成、新人奖励、畅销奖励 | ⭐⭐⭐⭐ |
| **客户成功体系** | 标杆客户、ROI 证明、NPS 评分 | ⭐⭐⭐⭐ |

### 💰 商业模式

**类比**: VSCode + App Store + OpenAI

| 模式 | 对标 | 说明 |
|------|------|------|
| 本地部署 | VSCode | 免费/低价获客，降低入门门槛 |
| Mod 商店 | App Store | 第三方插件付费下载，平台抽成 30% |
| Token 付费 | OpenAI | AI 调用按量计费，持续性收入 |

### 📊 定价策略（参考）

| 版本 | 价格 | 包含内容 |
|------|------|---------|
| **社区版** | 免费 | Apache-2.0 协议，功能受限 |
| **标准版** | ¥10,000–30,000/年 | 完整功能，单实例 |
| **企业版** | ¥50,000–100,000/年 | 多实例、优先支持、定制开发 |

| Token 套餐 | 价格 | 包含调用次数 |
|-----------|------|------------|
| **基础包** | ¥999/月 | 10,000 次 |
| **专业包** | ¥2,999/月 | 50,000 次 |
| **企业包** | ¥9,999/月 | 200,000 次 |

### 🏪 Mod 生态

**已有 Mod**:

- `sz-qsm-pro` - 奇士美 PRO 行业定制版（¥1,999）
- `taiyangniao-pro` - 太阳鸟 PRO 相关扩展（¥1,499）

**开发者分成**: 70% 开发者 / 30% 平台

### ⚡ 性能提升（目标取向，非第三方审计 SLA）

| 指标 | v5.0 | v6.0 | 提升 |
|------|------|------|------|
| 前端加载时间 | ~0.8s | ~0.6s | ⬆️ **25%** |
| 意图识别准确率 | ~99% | ~99.5% | ⬆️ **0.5%** |
| 可用性 | 99.5% | 99.9% | ⬆️ **0.4%** |
| 并发能力 | 1000 QPS | 2000 QPS | ⬆️ **100%** |

### 🔧 技术升级

| 组件 | v5.0 | v6.0 | 改进 |
|------|------|------|------|
| 商业模式 | 未明确 | **三层收入** | 可持续变现 |
| Mod 系统 | 基础 | **完整生态** | 开发者激励 |
| Token 计费 | 无 | **认证钱包** | 持续性收入 |
| 文档体系 | 分散 | **统一规范** | 开发者友好 |
| 目录结构 | `backend/` + `app/` 并存 | **仅 `app/`**（2026-04-20 全量迁移） | 单一落点 |

### 📚 新增 / 更新文档

- 💰 [`BUSINESS_MODEL.md`](BUSINESS_MODEL.md) — 三层收入结构详解（如提供）
- 🏗️ [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — Neuro-DDD 架构详解
- 🗺️ [`docs/FEATURE_MAP.md`](docs/FEATURE_MAP.md) — 功能边界与目录职责（必读）
- 🧭 [`docs/MIGRATION_REGISTRY.md`](docs/MIGRATION_REGISTRY.md) — 迁移总登记册

### ⚠️ 破坏性变更

- 新增环境变量：`TOKEN_WALLET_ENABLED`、`MOD_STORE_ENABLED`
- Mod Manifest 格式升级（v2）
- API 鉴权增强（Token 签名验证）
- 旧 `backend/` Python 包已全量下线；历史备份见 `.archive/legacy-backend-2026-04-final/`
- HTTP 入口统一为 `XCAGI/run.py` 端口 `5000`，`backend.http_app:8000` 已删除

---

## v5.0.0 (2026-04-05) - 🧠 Neuro-DDD 时代

### 🎯 重大定位升级

**从「AI 员工」升级为「基于 Neuro-DDD 架构的企业 AI 员工平台」**

- 🧠 **Neuro-DDD 架构** - 神经领域驱动设计，12 个神经域（含 `ShipmentNeuroDomain`）
- 🚌 **NeuroBus** - 8 大可靠性机制（去重、限流、熔断、追踪、SLA 等）
- ⚡ **神经反射弧** - <1ms 超快响应
- 📱 **小程序支持** - 微信小程序完整 CRM 功能

### 🆕 新增核心能力

| 能力 | 说明 | 重要性 |
|------|------|--------|
| **Neuro-DDD 架构** | 12 个神经域自治协同（含 `ShipmentNeuroDomain` 出货域） | ⭐⭐⭐⭐⭐ |
| **NeuroBus 8 大机制** | 去重、追踪、限流、熔断、SLA 等 | ⭐⭐⭐⭐⭐ |
| **神经反射弧** | <1ms 规则匹配快速响应 | ⭐⭐⭐⭐ |
| **潜意识/显意识双模** | <10ms / <200ms 双模处理 | ⭐⭐⭐⭐ |
| **小程序 API** | 微信小程序完整功能 | ⭐⭐⭐⭐ |
| **审批流** | 多级审批流程支持 | ⭐⭐⭐⭐ |
| **FastAPI 主入口** | `XCAGI/run.py` → `app.fastapi_app:get_fastapi_app`；Flask 已拆除 | ⭐⭐⭐⭐⭐ |

### 📊 性能指标

| 指标 | v4.0 | v5.0 | 提升 |
|------|------|------|------|
| 前端加载时间 | ~1.0s | ~0.8s | ⬆️ **20%** |
| AI 员工响应 | 毫秒级 | <1ms 反射弧 | ⬆️ **100 倍** |
| 可用性 | 99% | 99.5% | ⬆️ **0.5%** |

---

## v4.0.0 (2026-03-25) - 🤖 AI 员工时代

### 🎯 重大定位升级

**从「智能单据处理系统」升级为「基于 AI 的单据智能处理 AI 员工」**

- 🤖 **AI 员工定位** - 不再是被动工具，而是能主动决策、自主学习的 AI 员工
- 🔄 **全自动化流程** - 业务流程自动执行，真正解放双手
- 💬 **多模态交互** - TTS 语音 + 自然语言 + 微信消息
- 🏢 **行业智能适配** - 多行业模板支持

### 🆕 新增核心能力

| 能力 | 说明 | 重要性 |
|------|------|--------|
| **AI 智能决策** | 混合意图识别引擎 v2，准确率 99%+ | ⭐⭐⭐ |
| **全自动化处理** | 单据自动识别、业务流程自动执行 | ⭐⭐⭐ |
| **多模态交互** | TTS 语音合成、自然语言对话 | ⭐⭐⭐ |
| **行业智能适配** | 多行业模板、灵活配置 | ⭐⭐ |

### 🏢 适用行业扩展

- 🏭 **制造业** - 生产单据、物料标签、出货管理
- 🚚 **物流行业** - 快递单据、货物追踪、签收确认
- 🛒 **零售业** - 进货单、商品标签、库存管理
- 📦 **批发行业** - 批发单据、订单管理、价格体系
- 🛍️ **电商行业** - 订单处理、发货单、退货管理

---

## v3.0.0 (2026-03-15) - 🎯 混合智能时代

### 🆕 新增功能

| 功能 | 说明 | 重要性 |
|------|------|--------|
| **混合意图识别引擎** | 规则 + RASA NLU + BERT 三重保障 | ⭐⭐⭐ |
| **TTS 语音合成** | Edge TTS 多音色、语速/音调可调 | ⭐⭐⭐ |
| **任务自动化 Agent** | 复杂任务自动执行 | ⭐⭐⭐ |
| **微信生态集成** | 消息处理、联系人同步、消息解析 | ⭐⭐ |
| **BERT 本地推理** | 蒸馏模型离线可用 | ⭐⭐⭐ |
| **Alembic 迁移** | 数据库版本自动管理 | ⭐⭐ |
| **DDD 架构** | 领域驱动设计 | ⭐⭐ |

### 🔧 技术升级

| 类别 | v2.0 | v3.0 |
|------|------|------|
| Flask | 2.0+ | 3.0+ |
| ORM | 基础 | SQLAlchemy 2.0+ |
| 数据库迁移 | 手动 | Alembic 自动 |
| 前端状态管理 | - | Pinia 3.0+ |
| 构建工具 | 基础 | Vite 4.4+ |
| 意图识别 | 云端 API | 混合离线可用 |
| 架构模式 | 简单分层 | DDD 领域驱动 |

---

## v2.0.0 (2026-03-01) - 🌐 Web 智能化时代

### 🆕 新增功能

| 功能 | 说明 |
|------|------|
| Vue 3 前端 | 全新现代化 Web 界面 |
| AI 对话 | DeepSeek AI 模型集成 |
| OCR 识别 | 文字自动识别 |
| 多客户隔离 | 数据隔离管理 |
| 价格体系 | 价格管理功能 |
| RESTful API | 完整 API 接口 |
| Swagger 文档 | API 文档自动生成 |
| Redis 缓存 | 数据缓存加速 |
| Celery 队列 | 异步任务处理 |

### 🔧 技术升级

| 类别 | v1.0 | v2.0 |
|------|------|------|
| 界面 | 命令行 | Vue 3 Web |
| AI 能力 | 无 | DeepSeek API |
| 架构 | 单文件 | 模块化 |
| 文档 | 无 | Swagger |

---

## v1.0.0 (2026-02-15) - 📊 基础工具时代

### 🆕 核心功能

| 功能 | 说明 |
|------|------|
| Excel 解析 | 自动识别出货单/收货单 |
| 标签打印 | TSC 打印机支持 |
| 数据管理 | 基础 CRUD 操作 |
| 单据处理 | 出货/收货记录管理 |

### 🔧 技术栈

```
Python + openpyxl + SQLite + TSC 打印机
```

---

## 功能对比总览

| 功能 | v1.0 | v2.0 | v3.0 | v4.0 | v5.0 | v6.0 | v7.0 | v8.0 | v10.0 |
|------|:----:|:----:|:----:|:----:|:----:|:----:|:----:|:----:|:-----:|
| Excel 解析 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 标签打印 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Vue Web 界面 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| AI 对话 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| OCR 识别 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 多客户隔离 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 价格管理 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Redis 缓存 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Celery 队列 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| RESTful API | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Swagger / OpenAPI | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **混合意图引擎** | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **TTS 语音合成** | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **任务 Agent** | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **微信集成** | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **DDD 架构** | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **BERT 本地推理** | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Alembic 迁移** | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **AI 员工定位** | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **全自动流程** | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **多模态交互** | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **行业适配** | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Neuro-DDD / NeuroBus** | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **神经反射弧 (<1ms)** | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **FastAPI 唯一入口** | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **小程序 API** | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **审批流** | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Mod 商店 / 员工商店** | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| **Token 认证钱包** | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| **三层收入结构** | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| **桌面安装包（Electron）** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| **自动更新** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| **跨行业 UI 适配** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **Mod 制作端行业选择** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **版本锁死 + 锚点对齐** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **Flask 遗留清除** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |

---

## 技术栈演进

### v1.0

```
Python + openpyxl + SQLite + TSC 打印机
```

### v2.0

```
Python + Flask + Vue 3 + DeepSeek API + OCR + Redis + Celery
```

### v3.0

```
Python + Flask 3.0 + Vue 3.3 + Pinia + SQLAlchemy 2.0 + Alembic
    + DeepSeek AI + RASA NLU + BERT + PyTorch + Transformers
    + Edge TTS + Celery + Redis + DDD 架构
```

### v4.0

```
Python + Flask 3.0 + Vue 3.4 + Pinia + SQLAlchemy 2.0 + Alembic
    + DeepSeek AI + RASA NLU + BERT + PyTorch + Transformers
    + Edge TTS + Celery + Redis 7.0 + DDD 架构
    + PostgreSQL 16 + pgvector 向量搜索
    + Prometheus + Grafana + Loki 全链路监控
    + Kubernetes 容器编排
    + AI 员工核心 + 全自动流程 + 多模态交互 + 行业智能适配
```

### v5.0

```
Python 3.11 + FastAPI 0.110 + Uvicorn + Vue 3.4 + Vite 6 + TypeScript 5
    + SQLAlchemy 2 + Alembic + PostgreSQL 16 + pgvector
    + Neuro-DDD 分层 + NeuroBus 8 大机制 + 12 神经域
    + DeepSeek / BERT / PaddleOCR / EasyOCR
    + MODstore / Mod Manager + 微信小程序 + 审批流
```

### v6.0

```
v5.0 技术栈
    + Mod 商店 / 员工商店 / Manifest v2
    + Token 认证钱包（按量计费、套餐管理、用量监控）
    + 开发者分成（70/30）+ License / API 签名校验
    + 本地部署 + SaaS Token 的混合部署形态
```

---

## 升级路径

### v1.0 → v2.0

```bash
pip install -r requirements.txt
python run.py
```

### v2.0 → v3.0

```bash
pip install -r requirements.txt
alembic upgrade head
python run.py
celery -A celery_app worker --loglevel=info   # 可选
```

### v3.0 → v4.0

```bash
git pull origin main
pip install -r requirements.txt
alembic upgrade head
# .env：AI_EMPLOYEE_MODE=true / INDUSTRY_TYPE=manufacturing
docker-compose restart
```

### v4.0 → v5.0

```bash
git pull origin main
pip install -r requirements.txt
alembic upgrade head
# HTTP 入口改为 XCAGI/run.py（端口 5000），Flask 入口已拆除
cd XCAGI && python run.py
```

### v5.0 → v6.0

```bash
git pull origin main
pip install -r requirements.txt
alembic upgrade head
# .env 新增：
#   TOKEN_WALLET_ENABLED=true
#   MOD_STORE_ENABLED=true
# Mod Manifest 升级到 v2（模板见 docs/guides/MOD_AUTHORING_GUIDE.md）
cd XCAGI && python run.py
```

---

## 未来展望

### v7.0

- [x] Windows/macOS 桌面安装包
- [x] 自动更新

### v8.0

- [x] 跨行业 UI 适配 + 行业预设
- [x] Mod 制作端行业选择

### v10.0（当前）

- [x] 版本锁死 10.0.0 + 全仓锚点对齐
- [x] Flask 遗留清除（FLASK_ENV/FLASK_DEBUG）
- [x] DI 类型安全 + datetime.utcnow 修复
- [x] pre-commit 工具链增强（black/isort/mypy）
- [ ] 测试覆盖率提升至 70%
- [ ] P0 技术债清偿（app_factory 拆分、依赖分类）
- [ ] 移动端 App 支持
- [ ] 多语言支持（国际化）

---

## 许可证

本项目社区版采用 **Apache License 2.0** 开源许可证（2026-06 由 AGPL-3.0 对齐；历史 commit 仍可能标注旧协议，以 HEAD [`LICENSE`](LICENSE) 为准）。

---

> 🚀 **从 v1 到 v10，XCAGI 完成了从「工具」→「智能系统」→「AI 员工」→「企业 AI 员工平台」→「版本锁死 + 工程纪律整固」的六次跨越**
>
> - **v1**: 自动化工具 - 替代手工操作
> - **v2**: 智能系统 - 引入 AI 能力
> - **v3**: 混合智能 - 离线可用、多引擎协同
> - **v4**: AI 员工 - 主动决策、自主学习、全自动化
> - **v5**: Neuro-DDD 平台 - 神经域 + FastAPI + Mod 生态（基础）
> - **v6**: 企业 AI 员工平台 - 三层收入 + Mod 商店 + Token 钱包
> - **v7**: 桌面化时代 - Windows/macOS 安装包 + 自动更新
> - **v8**: 跨行业适配 - 行业预设 + Mod 制作端行业选择
> - **v10**: 工程纪律整固 - 版本锁死 + Flask 清除 + DI 类型安全 + 工具链增强

*最后更新：2026-06-07*
