# XCAGI 版本更新日志

> 从 v1.0 到 v10.0 的演进历程

---

## 1.0.0.1（2026-09-01）— 企业交付版本可见与 Windows 临时交付

- **版本 SSOT**：产品四段版本升级为 `1.0.0.1`；npm/Electron、Flutter pub 与 Apple 工具链继续使用等价三段版本 `1.0.0`。
- **桌面续会**：已登录用户在冷启动时先恢复本机已验证会话，再后台完成官网账号校验；未新增、复制或绕过任何官网凭据。
- **首次体验**：保留既有宿主、工作区和入门完成状态，避免更新后重复进入宿主入门页。
- **交付版本可见**：客户交付中心显示最近一次成功安装回执中的产品版本和平台；历史回执缺失版本时明确显示“当前版本未上报”，失败升级不覆盖已安装版本。
- **安装回执**：首次登录和 OTA 安装成功后上报安装版本、构建 SHA 与平台，为客户交付追踪提供真实设备证据。
- **Windows 临时交付**：在 SSL.com 签名凭据尚未配置时，独立产出名称带 `-macalign` 的未签名企业临时包；官网明确显示风险、文件大小和 SHA-256，不写入稳定自动更新通道。
- **官网同步**：临时交付流水线从下载版本 SSOT 生成独立公开指针和更新日志，并在发布后核验下载中心、更新日志、安装包、构建 SHA、文件大小和 SHA-256 一致。
- **发布纪律**：仅当最终 SHA 的 Windows 签名、macOS 公证、更新源、安装启动检查和公开下载中心验收全部通过后，才可对外标记为正式稳定版。

---

## 1.0.0.0（2026-07-12）— 稳定上线版本基线

- **版本 SSOT**：对外产品版本统一为 `1.0.0.0`；npm/Electron、Flutter pub 与 Apple 市场版本映射为合法三段版本 `1.0.0`。
- **发布链**：Windows/macOS/Android/Harmony/Web 工作流、打包脚本、发布目录和下载清单统一使用 `xcagi-v1.0.0.0`。
- **自动更新**：Electron `latest*.yml` 保持 SemVer `1.0.0`，同时写入 `productVersion: 1.0.0.0`；制品文件名使用四段产品版本。
- **Mod 兼容**：宿主与内置 Mod 的版本/依赖基线统一为 `1.0.0.0`，避免历史 `>=10.0.0` 阻断加载。
- **下载清单**：manifest 补齐 `xcagi.download_manifest/v1` schema，官网 fallback、nginx 路径和双 SKU 文件名同步到稳定版本。
- **发布纪律**：历史 `10.0.0` 制品与证据保留为历史事实；新的稳定制品必须重新构建、签名、公证、上传并通过端到端验收。

## 历史 Unreleased（10.0.0 线内记录 · 截止 2026-07-12）

### macOS 公证 CDN 闭环（2026-07-12 · v10 线内迭代）

- **release(desktop)**：`main` Release Desktop 产出 Developer ID + 公证 staple 的 mac personal/enterprise 安装包（buildSha `3f00c87b`）
- **release(cdn)**：本机 rsync 上架 `xiu-ci.com/releases/stable/{enterprise,personal}/`（DMG/ZIP/blockmap/`latest-mac.yml` + Ed25519）
- **docs(evidence)**：公网下载/SHA512/Ed25519/Gatekeeper 复测 PASS — `mac-notarize-cdn-closure-2026-07-12.md`

### v10-B/C 交付推进（2026-07-11 · v10 线内迭代）

- **fix(mobile-flutter)**：落地 `preferCloudIfLanUnreachable` + session LAN/云 base 路由，避免 5G 下死打局域网
- **fix(mobile-flutter)**：探索 Tab 增加审批入口；通知页去掉假数据 fallback（空态诚实）
- **fix(backend)**：审批驳回与 AI 工作流驳回均 `notify_mobile_user`，对齐通过路径
- **fix(modstore)**：商品履约同步写入 `user_mods`（`pkg_id`），打通支付→桌面 entitlement
- **ci(mobile)**：发版/门禁切到 `mobile-flutter-poc`（`ci-mobile-flutter` / `fhd-release-android` / `android-build`）；归档 Kotlin CI 改为走 Flutter
- **docs(evidence)**：v10-B 终稿签字 — `v10-b-store-desktop-acceptance-2026-07-11-final.md`；`specs/tasks.md` **PL2 已勾选**
- **docs(evidence)**：v10-C 底稿 `v10-c-mobile-acceptance-2026-07-11.md`（真机/正式签名未签，PL3 暂不勾）

### v10-A 真机验收修复（2026-07-09 · v10 线内迭代）

- **fix(desktop)**：`deliverable-status` 读取运行中 `request.app`，消除 `MOD_ROUTES_NOT_MOUNTED` 误判（Mac 真机已验）
- **fix(desktop)**：桌面 fast-start 将 `platform-shell` 路由提前至 bootstrap，避免 deferred 完成前 SPA fallback 对 `/api/platform-shell/*` 返回 404（v10-A Win 404 根因）
- **fix(desktop)**：`win_v10a_hotfix_deploy.ps1` 改为纯 ASCII + 轮询 health/deliverable（PS5 兼容）
- **fix(desktop)**：PyInstaller `xcagi_backend.spec` 强制 hiddenimports（`platform_shell_routes` / `deliverable_status`），修复 Win frozen 包缺模块导致 deliverable-status 404
- **fix(desktop)**：Win 源码中文 docstring 损坏导致 SyntaxError / invalid module；关键模块改为 ASCII 文案后重建通过
- **fix(package)**：`add_data` 对单文件改用父目录 dest，避免 `alembic.ini` 被打成 `_MEIPASS/alembic.ini/alembic.ini`；`migrate.py` 兼容嵌套路径
- **fix(desktop)**：PyInstaller 打包 OTA `migrate-only` 在 frozen 环境改走 `alembic.command` API（修复 `upgrade head` exit 2）
- **docs(evidence)**：v10-A 终验 — Win A5 `deliverable=true` + A9 `migrate_exit=0`；`specs/tasks.md` PL1 已勾选

### 桌面冷启体感（2026-07-08 · v10 线内迭代 · 第三轮）

- **perf(desktop)**：先出 Splash 窗再 spawn 后端；Splash 状态文案 + 秒数反馈
- **perf(desktop)**：主应用等待 `appRoutesReady`（ping + deferred 路由挂载完成）
- **perf(backend)**：fast-start 仅注册 bootstrap 路由（health/infrastructure），业务路由并行 deferred
- **perf(backend)**：lifespan 跳过 `mods_deferred_bootstrap` 重复同步 Mod 引导
- **perf(package)**：PyInstaller 默认关闭 UPX（`XCAGI_PYINSTALLER_UPX=1` 可显式开启）

### OTA session 代理绕过（2026-07-08 · v10 线内迭代）

- **fix(desktop)**：`session.defaultSession.setProxy` 显式配置 `proxyBypassRules`，死代理（7890 未开）时 OTA 仍可直连 `xiu-ci.com`
- **fix(desktop)**：Windows 系统代理场景改用 PAC——更新站 `DIRECT`，其余 `PROXY; DIRECT` 回退
- **fix(desktop)**：OTA 专用 `netSession` 直连（`persist:xcagi-updater`），electron-updater 与元数据拉取均绕过死代理
- **fix(desktop)**：检查更新期间临时将 `defaultSession` 切直连，规避死系统代理
- **fix(desktop)**：启动时探测系统代理端口；不可达则 `defaultSession` 全程直连（桌面 UI 仅加载 127.0.0.1）
- **fix(desktop)**：死代理在进程启动前追加 `--no-proxy-server`，避免 Chromium 仍走 WinINet 代理

### OTA 更新站域名 + channel 修复（2026-07-08 · v10 线内迭代）

- **fix(desktop)**：`SKU_UPDATE_URL` 改走可达的 `xiu-ci.com/releases/stable/{sku}/`（`update.xcagi.com` 在 Win32 解析到不可达 IP）
- **fix(desktop)**：electron-updater 不再默认 `channel: stable`（避免请求 `stable.yml` 404，应拉 `latest.yml`）
- **fix(desktop)**：`proxy-bypass-list` 同时覆盖 `update.xcagi.com` 与 `xiu-ci.com`

### OTA 推送验活（2026-07-08 · v10 线内迭代）

- **chore(release)**：enterprise Windows 同版本 `buildSha` OTA 推送验活（Win32 真机拉取）

### 桌面侧栏版本 + 配对码 SSOT（2026-07-08 · v10 线内迭代）

- **fix(web)**：侧栏「系统正常」右侧显示 `v10.0.0`（非管理端从 `/api/health` 读取）
- **fix(web)**：移动端配对 QR 与 6 位设备码统一 `normalizePairingPayload` SSOT

### 桌面 LAN 配对 + OTA 代理绕过 + 云中继直连（2026-07-08 · v10 线内迭代）

- **fix(desktop)**：后端默认绑定 `0.0.0.0:17500`，手机同 WiFi 可连局域网 IP；Electron UI 仍只加载 `127.0.0.1`
- **fix(desktop)**：`proxy-bypass-list` 对 `xiu-ci.com` 直连，避免系统代理 `127.0.0.1:7890` 未开时 OTA 报 `ERR_PROXY_CONNECTION_FAILED`
- **fix(desktop)**：死系统代理不可达时启动前追加 `--no-proxy-server`，`defaultSession` PAC/直连与 updater 专用 `netSession`
- **fix(desktop)**：OTA `setFeedURL` 不再默认 `channel: stable`（避免拉 `stable.yml` 404）
- **fix(desktop)**：v10 同版本迭代 OTA — `latest.yml` 写入 `buildSha`，`build-info.json` 比对后仍可拉取新包
- **fix(mobile-relay)**：桌面云中继 `httpx` 使用 `trust_env=False`，修复代理环境下 `Invalid port` 注册失败

### 桌面冷启性能（P1-3 · 2026-07-08 · v10 线内迭代）

- **perf(desktop)**：Splash 先出窗，不再在 `show()` 前阻塞 `waitForBackendHealth`；就绪探测改 `/api/ping`（300ms 轮询）
- **perf(desktop)**：主窗口立即 `show`，主应用加载与 ping 等待解耦，清缓存改为后台
- **perf(desktop)**：`electron-backend.log` 超 8MB 自动轮转；打包默认 `LOG_LEVEL=WARNING`
- **perf(backend)**：`XCAGI_DESKTOP_FAST_START=1` 时 lifespan 仅 DB+Mod，NeuroBus/员工调度/云中继/性能优化延后后台加载
- **perf(backend)**：fast-start 下 Mod `bootstrap` 从 factory 同步路径延后到 deferred，消除 ~3.4s `mod_staged` 阻塞
- **perf(api)**：`GET /api/health?lite=true` 跳过 NeuroBus 载荷
- **perf(frontend)**：桌面壳 `mods` 列表重试退避缩短（150–600ms）

### UX P0/P1 四线收敛（2026-07-07 · v10 线内迭代）

- **fix(mobile-flutter)**：`mobile-relay-*` 会话 validate 不再误 401；`preferCloudIfLanUnreachable` + session 路由 LAN/云；`/employee-ssot` client
- **docs**：移动统一 **Flutter 主线**；`mobile-android` / `mobile-ios` 归档；`MOBILE_FLUTTER.md` + SSOT 登记
- **feat(web)**：`productErrorMessage` 统一引导/Mod/IM 错误文案；引导续接 `xcagi_product_flow_last_step`；企业版不再重复 shell welcome 拦截
- **feat(web)**：IM 员工通讯录优先消费 `GET /api/platform-shell/employee-ssot`
- **docs**：`PRODUCT_USER_FLOW.md` 对齐 industry → host-pack 实现顺序

### 定价 SSOT 文档同步（2026-07-07 · v10 线内迭代）

- **docs**：`LICENSING.md` 清除过期年费/Offline 固定价 FAQ，定价指向 `saas_plans.json` + MODstore `PlanTemplate`
- **docs**：`account_system_ssot.md` / `SSOT_INDEX.md` 登记 `pricing-enterprise` / `pricing-membership` SSOT
- **docs**：`COMMERCIAL_LICENSE.md` §2.1 / §4.3、`BUSINESS_MODEL.md` 对齐运行时价格，退役旧参考价表

### OTA update 站 DNS/HTTPS 与推送（2026-07-07 · v10 线内迭代）

- **决策**：放弃阿里云 `update.xcagi.com`（欠费停放），OTA/ manifest SSOT 统一 `https://xiu-ci.com/releases/stable/...`（腾讯云 DNSPod + 同机 nginx）
- **fix(desktop)**：内置 OTA URL 改 `https://xiu-ci.com/releases/stable/{personal|enterprise}/`（同机 HTTPS alias 已可用）
- **fix(admin)**：`check_deploy_updates` manifest 默认走 `http://119.27.178.147/.../fhd-manifest.json`，避免域名超时误判 unreachable
- **ops**：新增 `ops/fix-update-xcagi-https.sh`（DNS 切到本机后 acme.sh 签发 + nginx 443）
- **deploy**：已 pack+push `git_sha=7f2ad0fffad6`，服务器 `fhd-auto-update` 应用成功

### Flutter 全功能补齐（2026-07-07 · v10 线内迭代）

- **feat(mobile-flutter)**：员工任务中心（Phase-D 提问列表 + 老板回答）对齐 Android `EmployeeQuestionsScreen`；员工档案新增「问他/她的待回答问题」入口
- **feat(mobile-flutter)**：IM WebSocket 实时客户端（`/ws/im` 心跳 + 断线重连），`ImMessengerScreen` 接入实时消息
- **feat(mobile-flutter)**：登录/配对成功后自动 `registerDevice`（有 `fcm_token` 时），对齐 Android `PushRegistrar`
- **test(mobile-flutter)**：员工提问与 IM WS 解析单测；**257** 测试全绿

### 启动深链配对红屏修复（2026-07-07 · v10 线内迭代）

- **fix(mobile-flutter)**：配对深链不再在 `_route == null`（加载中）或协议页触发，避免与路由切换冲突导致 `_dependents.isEmpty` 红屏
- **fix(mobile-flutter)**：`MobileRepositoryScope` 上移到 `MaterialApp` 外层，配对 Toast 延后到下一帧展示

### 配对码仅局域网 · 云中继账号鉴权（2026-07-07 · v10 线内迭代）

- **fix(mobile-flutter)**：6 位配对码不再走 `relay/mobile/confirm-code`；统一 `pairing/lookup` → `pairing/exchange` 局域网绑定，与 Android 一致
- **fix(frontend)**：`MobilePairingQrCard` 展示 LAN `shortCode`（非 relay `pairing_code`）；文案明确配对码仅同 WiFi，跨网走登录后云中继账号鉴权

### 扫码配对 400 修复（2026-07-07 · v10 线内迭代）

- **fix(mobile-flutter)**：配对 exchange 不再误打云端 `/fhd-api`；解析失败时禁止把整段 JSON 当 nonce 提交；局域网 baseUrl 改为 `http://host:port/` 并在 exchange 前写入 session `fhdHost`
- **fix(mobile-flutter)**：400/配对码无效时展示「请在电脑端刷新二维码后重试」友好文案

### 扫码相机权限修复（2026-07-07 · v10 线内迭代）

- **fix(mobile-flutter)**：扫一扫「授予相机权限」按钮现通过原生 `ActivityCompat.requestPermissions` 弹出系统授权框；授权后自动启动 `MobileScanner`

### 扫码相机启动修复（2026-07-07 · v10 线内迭代）

- **fix(mobile-flutter)**：授权后等 `MobileScanner` 挂载再 `start()`，避免 `controllerNotAttached` 被静默吞掉；从设置返回时自动重试；相机故障与权限页分离展示

### 扫码相机插件替换（2026-07-07 · v10 线内迭代）

- **fix(mobile-flutter)**：小米真机 `mobile_scanner` CameraX 启动 NPE；改用 `camera` + ML Kit 帧流扫码，对齐原生 Kotlin 方案

### 扫码识别无反应修复（2026-07-07 · v10 线内迭代）

- **fix(mobile-flutter)**：相机帧转 ML Kit 输入改用 **NV21**（Android 插件仅支持 NV21/YV12，此前误用 iOS 的 yuv420 导致每帧静默失败）；修正旋转角与扫码成功后停流

### 6 位设备码云中继绑定（2026-07-07 · v10 线内迭代）

- **fix(mobile-flutter)**：输入 6 位设备码时优先调用 `relay/mobile/confirm-code`（对齐管理端「服务器中继设备码」），失败再回落局域网 `pairing/lookup`；LAN 探测单次超时缩短至 ~900ms，避免 spinner 卡数分钟
- **fix(mobile-flutter)**：`xcagi://pairing?code=` 深链携带 query，未登录态可直接触发配对（便于 adb/桌面 QR 拉起绑定）

### 6 位设备码局域网绑定（2026-07-07 · v10 线内迭代）

- **fix(mobile-flutter)**：恢复「只输入设备码」— 同一 WiFi 下自动探测局域网电脑（`pairing/lookup` + 5011/17500 等端口），无需扫完整二维码
- **fix(backend)**：`/api/mobile/v1/pairing/lookup` 加入 LAN 门禁白名单

### 局域网扫码配对修复（2026-07-07 · v10 线内迭代）

- **fix(backend)**：配对 QR 在后端仅监听 `127.0.0.1` 时不再写入手机不可达的 API 端口（如 `:17500`）；经 Vite 管理端/企业端（`:5011`/`:5001`）签发时改写入局域网可达的代理端口，并忽略 Vite Host 误作 API 端口
- **fix(frontend)**：`MobilePairingQrCard` 在 dev 代理页即时把 QR 中的 `api_base_url` 改写到 `:5011`/`:5001`，刷新二维码后手机可立即扫码绑定（无需等后端重启）

### Flutter 手机端聊天发送修复（2026-07-07 · v10 线内迭代）

- **fix(mobile-flutter)**：根治聊天页「点击发送无反应」——`loadInitialMessages` 返回 fixed-length 列表后 `_messages.addAll/clear` 在 `setState` 内抛 `Cannot add to a fixed-length list`，`_sending` 卡 true 拦截后续发送；改为拷贝赋值 + 不可变式追加，并补 widget 回归测试
- **fix(mobile-flutter)**：release R8 裁剪 `WorkDatabase` 导致新装包启动即崩；新增 `proguard-rules.pro`（对齐 mobile-android keep 规则）
- **fix(mobile-flutter)**：`clearActiveAuth` 的 `cachedModInfos: const []` 类型转换崩溃；恢复企业端会话「已安装」徽章（对齐 Android AppViewModel）
- **chore(mobile-flutter)**：IM 端点切换到 `api/mobile/v1/im/*` 并补 `im/conversations`、`read`、管理端客服收件箱、员工 Phase-D 提问端点，与 Android `ApiEndpoints.kt`/`FhdApi.kt` SSOT 重新对齐（parity 测试恢复全绿）

### 员工 IM 工作闭环（2026-07-07 · v10 线内迭代）

- **fix(im)**：`employee_id_for_conversation` 同时识别 `emp:` / `ai-employee:` 两套员工合成用户命名并按 `AiEmployeeProfile.user_id` 兜底反查——此前生产桥（`/api/internal/employee-im/send`）建的会话里老板回复被静默丢弃（已读不回）
- **feat(im)**：桌面/Web `POST /api/im/conversations/{id}/messages` 补齐员工入站回流（与手机端对齐），共享 `app/infrastructure/im/employee_reply_relay.py`
- **feat(modstore)**：老板 IM 消息无 pending 问题时不再丢弃：`boss_im_inbound` 转成该员工的 `PendingBriefTask(source_kind="boss_im")`，即时 ACK「收到我来处理」，调度循环直达点名员工执行后 IM 回音（失败也回音，不静默）
- **feat(modstore)**：`boss_daily_im_report` 每日定时（默认北京 09:15）以数字管家身份把过去 24h 员工执行/任务/待答问题账本主动推送到老板 IM；注册 `boss_daily_im_report` 调度任务并纳入 `/api/scheduler/runtime` 追踪
- **feat(modstore)**：`notify_boss` 支持显式 `boss_user_id` / `owner_user_id`（回流场景绑定员工 owner）；执行器 report hook 支持 `im_reply_managed` 抑制避免双发
### 表格员工闭环 · LLM 亲考与固化产物（2026-07-06 · v10 线内迭代）

- **feat(employee)**：收录 `examples/sunbird-solidified/transform.py`——LLM 在固化循环中亲笔编写的太阳鸟考勤转换脚本（288 行零 taiyangniao 依赖），三轮迭代通过金样门禁（68.7%→97.8%→100%，3842/3842 槽），端到端与太阳鸟单体输出数据区 30240 格逐格 0 差异；每人参数（MORNING9/OT_1830）由金样归纳，等价模板 B 列 DSL 快照
- **test(mods)**：`test_solidified_example_passes_golden_gate` 常驻回归——固化脚本对真实钉钉表金样对账必须全绿，同时守护金样反读器与 records 契约兼容性

### 表格员工闭环 · 固化循环（2026-07-06 · v10 线内迭代）

- **feat(employee)**：规则映射员新增 `solidify` 动作（`solidify.py` + `golden.py`）：LLM 把业务转换规则写成 `produce_records(source_workbook, rules)` Python 脚本（窄接口，管道其余保持白盒）；循环「生成→静态安全检查→沙箱执行→records 契约校验→金样对账→diff 喂回重写」，全绿才固化 `transform.py` + `solidify_report.json`（迭代证据+sha256+rules_ref）；金样判据 = 金样 xlsx 按 rules 确定性反读 records 逐槽 diff；固化后每月运行零 LLM
- **test(mods)**：`test_excel_rules_solidify.py` 7 用例：反读器往返、diff 三态、固化一轮过/反馈迭代/黑名单拒绝/失败留证、convert 层端到端；**太阳鸟金样端到端**：金样=太阳鸟单体转化真实钉钉表（4557 行/69 人），固化循环金样对账 3842/3842 槽全匹配，零 LLM 复跑数据区 30240 格逐格 0 差异——固化管道完整复现太阳鸟转化

### 表格员工闭环 · LLM 协作（2026-07-06 · v10 线内迭代）

- **feat(employee)**：规则映射员接 LLM 精修（`llm_refine.py`）：LLM 基于表头/块文本样本回答 open_questions（bands 多带布局/键列兜底/clear_zone 边界），**每条提议经确定性验证**（越块/公式区重叠/覆盖率）才采纳，采纳与拒绝全留痕 `evidence.llm`；无 `ctx.call_llm` 或 `use_llm=false` 时与纯启发式一致
- **feat(employee)**：质检员新增 `semantic` 第七节（`llm_review.py`）：LLM 业务合理性审查（数值常理/丢弃记录可疑度/警告分级）+ `human_summary` 中文摘要；LLM finding 计入 verdict（blame=`semantic_llm`）但不可推翻确定性六节，`llm_strict=false` 降级为 warn
- **test(mods)**：`test_excel_employee_llm_paths.py` 8 用例（mock call_llm）：合法提议采纳/越界拒绝/乱码与宕机留痕/无 LLM 回归基线/semantic 并入 verdict/降级/skipped；真实太阳鸟模板 LLM 协作全链冒烟（LLM 提议三带布局→机器验证采纳→QC 语义审查抓出 30h 超常值）

### 表格员工闭环 · 质检员（2026-07-06 · v10 线内迭代）

- **feat(employee)**：新增 `excel-qc-employee`（Excel 质检员）：对回填结果六节独立对账——计划符合性（cell/formula/clear/retain 逐格比对）、保护区完整性（原模板 diff）、expected 三方重算（映射员自述 ↔ 计划重算 ↔ 输出文件重算）、公式健康（#REF!/悬空 sheet 引用）、rules_ref 哈希追溯、块结构漂移；verdict PASS/WARN/FAIL + blame 问责路由（writer_or_plan/mapper/pipeline/rules_stale）；不 import 映射员/写入员代码，缺输入的节如实 skipped
- **test(mods)**：`test_excel_qc_employee.py` 12 用例：诚实链路 PASS、六类篡改逐一检出（写入篡改/残值/伪造 expected/保护区破坏/#REF!/规则漂移）+ 真实太阳鸟模板五段全链质检（1290 格核对、3458 公式扫描、80 块零漂移）

### 表格员工闭环 · 规则映射员（2026-07-06 · v10 线内迭代）

- **feat(employee)**：新增 `excel-rules-map-employee`（Excel 规则映射员）双动作：`infer` 从读取员模板 workbook.json 通用推断块结构（竖向合并周期投票）/键列（覆盖率×唯一率）/日历锚（1..N 等差序列）/公式区/公式模板（跨块数字等差拟合），产出可固化 rules.json 提案（confidences + open_questions）；`compile` 把固化规则 + 槽位记录编译为写入员 plan.json（day/band/entry 越界校验、公式按块实例化、expected 对账基准、rules_ref sha256 追溯）
- **test(mods)**：`test_excel_rules_map_employee.py` 合成模板全字段推断 + 真实太阳鸟模板金样对照（151 块/31 天日历/16 公式列，实例化公式与模板原文逐字一致）+ 读→推→编→写→重读 e2e；真实模板四段全链冒烟通过

### 表格员工闭环 · 读取员/模板写入员（2026-07-06 · v10 线内迭代）

- **feat(employee)**：新增 `excel-template-write-employee`（Excel 模板写入员）：模板 xlsx + `plan.json` 写入计划 → 回填结果，phases（clear_ranges/cell_writes/formula_writes/retain_sheets）顺序执行，模板样式/合并/既有公式保真，`protected_ranges` 拒写并记 violation，输出 `outputs/filled.xlsx` + `write_report.json`（透传 `expected` 供质检员对账）
- **feat(employee)**：`excel-full-read-employee` workbook.json 每 sheet 新增 `merged_ranges`，cells 非 General 时输出 `number_format`（模板结构识别 / 回填保真前置）
- **test(mods)**：`test_excel_template_write_employee.py` 覆盖读取员新字段、写入员全阶段、保护区、读→计划→写→重读闭环；太阳鸟真实模板（909 行 × 85 列、979 合并区、1944 SUMIF）冒烟通过

### 平台七柱 Wave 2（2026-07-05 · v10 线内迭代）

- **feat(scaffold)**：`scripts/dev/scaffold-industry-mod.sh` 从中性行业包模板生成 `*-industry` Mod
- **feat(onboarding)**：首启 seed 按 manifest `industry.subsystems` 映射演示客户/产品；前端 seed/AI 文案随行业变化
- **feat(chat)**：`approval_card` 结构化 payload + `ChatApprovalInlineCard` 内联确认/取消
- **feat(risk)**：`ApprovalService` 读取 registry `approval: always` 作为 YAML 规则补充

### 平台七柱 Wave 0（2026-07-05 · v10 线内迭代）

- **feat(contracts)**：`industry_package.schema.json` + release_gate 校验 `*-industry` manifest；MOD_AUTHORING_GUIDE §4b
- **feat(risk)**：`config/risk_actions.registry.json` SSOT；`planner.get_tool_registry` 收敛至 execution registry
- **feat(security)**：`LOCAL_DATA_POLICY.md`；诊断包/上传/模型 API 需登录；日志脱敏；`purge_local_temp_data.py`

### 发版红线七柱（2026-07-05 · v10 线内迭代）

- **chore(repo)**：`.codex-artifacts/`、`templates/admin-vue-dist/`、`release_train_history/` gitignore；admin 构建产物改 CI 生成
- **ci**：`vue-tsc` / `mypy` / `build:strict` 硬门禁；新增 `release-verify`、`desktop-build-smoke` job 与 `scripts/dev/release_verify.sh`
- **feat(platform)**：办公文件平台管道（五类 upload/parse/review/confirm）、Chat 办公对接入口
- **feat(onboarding)**：通用首启 `seed-demo` + `first-ai-task` 步骤与 `/api/platform-shell/onboarding/seed-demo`
- **feat(auth)**：`auth_permission_resolver` 统一 Mod 权益 + RBAC；CI 默认 `XCAGI_TENANT_STRICT=1`
- **feat(employee)**：`employee_run_logs` 表、run ledger、结果验收与 Admin `/local/employees/{id}/runs`
- **fix(desktop)**：updater 失败保留当前版本 + 诊断包含 updater 事件与 mods 列表

### 桌面通用交付修复（2026-07-05 · v10 线内迭代）

- **fix(desktop)**：Electron 启动后端注入 `XCAGI_GLOBAL_RATE_LIMIT=0`；`XCAGI_DESKTOP_MODE` 下中间件跳过全局限流，`/api/platform-shell/*` 永不 429
- **fix(frontend)**：桌面壳侧栏对行业 ERP 路由（print/products 等）强制优先宿主直跳，避免连点落到对话页
- **fix(ci)**：`test_desktop_windows_runtime_matches_mac_shell_policy` 断言与当前 router 守卫对齐
- **feat(release)**：macOS CI 通过 App Store Connect API 签发 Developer ID、`notarize.cjs` 公证、`latest-mac.yml` Ed25519 签名

### 太阳鸟 PRO Mod API 治根（2026-07-04 · v10 线内迭代）

- **fix(mod)**：登录后 `mount_entitled_client_mod_api_routes` 为 entitlement 客户 Mod 执行 load + `/api/mod/{id}/*` 挂载；动态挂载后 `ensure_spa_fallback_last` 避免被 SPA catch-all 抢先 404
- **fix(mod)**：`business.py` compat 跳过条件改为检查 `_http_routes_registered`，不再仅凭磁盘 `blueprints.py` 存在
- **fix(mod)**：Registry 无元数据时 `_resolve_mod_metadata_for_http` 从磁盘 manifest 补全，支持冷启动后按需挂载

### 企业定价 · 预算档位永久购买（2026-06-21 · v10 线内迭代）

- **feat(billing)**：`saas_plans.json` 按预算四档永久购买定价（¥49,999 / ¥199,999 / ¥499,999 / ¥999,999）+ 30 天试用 ¥99
- **feat(api)**：`GET /api/model-payment/plans?budget_range=` 返回试用 + 对应永久套餐
- **feat(frontend)**：定价页展示 `/永久` 单位并按 `budget_range` 加载套餐

### 账号体系（2026-06-21 · v10 线内迭代）

- **chore(miniprogram)**：移除过期 `XCAGI/miniprogram/` 前端树；`tasks.md` 标记下线；DB ORM 保留作历史表兼容
- **feat(auth)**：OIDC SSO 回调/Android `oidc/exchange` 经 MODstore `POST /api/auth/internal/sso-issue-token` 自动绑定市场 JWT（`XCAGI_MARKET_INTERNAL_API_KEY`）
- **docs(auth)**：`AUTH_MARKET_CONTRACT.md` / `ENTERPRISE_IDP_SETUP.md` 同步 SSO 市场桥接说明

### Windows/macOS 桌面打包统一（2026-06-17 · v10 线内迭代）

- **fix(desktop)**：Electron 后端启动改为统一候选路径 + `electron-backend.log`；迁移流程复用 SKU Edition 环境；Windows 退出使用 `taskkill /T /F` 清理后端子进程
- **fix(package)**：`build-backend.sh` 默认 v10.0.0，并与 PowerShell 构建链一样 staging SKU mods、industry-seeds、`product-sku.json`
- **fix(package)**：`read-host-profile-stage-ids.py` / `read-open-industry-seed-ids.py` 改为纯 JSON 配置读取，避免 CI 打包阶段在 pip install 前导入完整 app 依赖
- **fix(package)**：`generate_mods_index.py` 构建阶段只索引 staged mods 根，避免 personal 包索引混入根 `mods/`、`mods-admin-runtime` 或 `XCAGI/mods`
- **fix(package)**：Docker/Wine Windows 构建链写入 `product-sku.json` 并带入 `XCAGI_STAGED_INDUSTRY_SEEDS_DIR`
- **guard(package)**：`build-windows-electron-only.sh` 默认禁止作为发布链路，避免产出缺少 `resources/backend/xcagi-backend.exe` 的不可用 Windows 安装包
- **guard(release)**：post-release 安全验收硬性检查 Windows 后端 exe、mods、industry-seeds 与 `product-sku.json`

### 文档 SSOT 全量同步（2026-06-17 · v10 线内迭代）

- **docs(coverage)**：退役 `60.63%` / 窄包 `70%` / `77.4%` 误报；`coverage-dual-summary.json` 重写为 HEAD（52.74% 行）+ WIP（74.56% 行，196 红灯）双轨
- **docs(claimed)**：`CLAIMED_VS_ACTUAL.md` 工程节对齐全量棘轮口径；`COVERAGE_RAMP.md` / `COVERAGE_GAP.md` 全面更新
- **docs(repo)**：`README.md` Android 签约级对齐 `VERSION.md`；`spec.md` / `checklist.md` / `对标头部SaaS` 覆盖率行更新
- **chore(metrics)**：`coverage-history.jsonl` 追加 WIP 快照；`xcmax-pytest-coverage.json` 标记退役

### Phase 4 覆盖率长尾与变异测试（v10 线内迭代 · 2026-06-14）

- **test(contexts/di)**：补 `manifest` / `flags` / `registry` / `fastapi_deps` 纯函数单测
- **chore(coverage)**：`health_k8s` 移除 2 处可测 `pragma: no cover`（诊断分支已有探针单测）
- **chore(mutmut)**：`pyproject.toml` 新增 `[tool.mutmut]`，首轮 `app/http` · `app/contexts` · `app/di`
- **chore(stryker)**：`frontend/stryker.conf.json` + `docs/reports/MUTATION_TESTING.md`（需 `npm i -D @stryker-mutator/*`）

### 企业引导 Mod 种子（v10 线内迭代 · 2026-06-14）

- **chore(mods)**：`scripts/dev/sync-enterprise-mod-seeds.sh` 从 desktop-dev / admin-runtime 补全 `FHD/mods/` bridge、core-workflow、planner-excel 等种子
- **feat(mods)**：新增 `mods/_employees/xcagi-host-foundation-employee` 宿主基础预装员工包 manifest
- **fix(onboarding)**：`industry_baseline` / `deliverable_status` 以磁盘 scan + 已加载 Mod 并集判定「已安装」

### 真正员工运行时（EmployeeAgent · v10 线内迭代 · 2026-06-14）

- **feat(employee_runtime)**：`EmployeeAgent` 编排对象接管 `execute_employee_task_local`；P0 多轮 `agent_loop` + `EmployeeMemoryManager`（短期 ConversationService / 长期 `emp:{id}` 向量索引）；P1 `tool_scope` 作用域工具 + `workspace_guard` 运行时强制 `scope_globs/forbidden_globs`；P2 `PerceptionPipeline`（document/vision/audio/text）；P3 `orchestrator` 本地 `depends_on` DAG + `triggers` NeuroBus 动态订阅；P4 写操作 `write_approval` 接 ApprovalGatedEngine 语义 + `metrics` 可观测
- **feat(domain/employee)**：值对象 `MemoryScope` / `PerceptionSpec` / `CollaborationGraph` / `TriggerBinding` / 标准事件类型
- **compat**：保留 echo/llm_md/direct_python handler；capabilities 已声明包无需改 manifest 即可派生工具子集；单轮 `_chat_completion` 仅保留给认知层

### L3 CI/CD 全自动端到端（v10 线内迭代 · 2026-06-13）
- **GitOps**：ArgoCD App-of-Apps、`bump_image.sh`、`gitops-image-bump`（opt-in）
- **Rollouts**：金丝雀 20→50→100 + `xcagi-slo-gate` Prometheus 分析门
- **可观测性**：`monitoring/overlays/full`、`bringup_stack.sh`、`local_stack_up.sh`、DORA 采集
- **预览**：`fhd-preview-env.yml` + `k8s/overlays/preview`（无 `KUBE_CONFIG` 时跳过构建并 PR 评论说明）
- **日更闭环**：`post_merge_promote.sh` + `MODSTORE_POST_MERGE_GITOPS_SCRIPT`
- **CI 阻断说明**：PR #20 全量红因 GitHub Actions **账单/spending limit**（非 workflow 缺陷）；修复付款后重跑；branch protection 需 Team/Enterprise（见 `docs/CI_SSOT.md`）

### 术债收口 + Tier C 高并发（Wave 0–10 · v10 线内迭代）
- **docs**：`SLO.md` Tier C 压测 SLO；`docs/evidence/arch/` 路由/OpenAPI 基线；`services_import_matrix.md`；`WAVE2_ROUTE_SSOT.md`
- **loadtest**：`tier_c_smoke.js` / `tier_c_sustained.js` / `tier_c_chat_streams.js`；k6 7d `tier_c_ramp` 阶梯场景
- **infra**：`DATABASE_READ_URL` + `get_read_session`；`pool_sizing.py`；staging/prod Redis 查询缓存与连接池文档
- **k8s**：`celery-worker-deployment.yaml` + HPA；API `deployment`/`hpa` Tier C 资源；chat 流式 Redis 信号量
- **migrate**：`catalog_client`/`catalog_visibility` → `infrastructure/mods/`（services shim）；`mod_store_routes` 走 application 门面
- **tasks**：`inference` Celery 队列（OCR/intent）；`workflow_excel_paths` 拆分巨型 `workflow.py`
- **registry**：`app_service_pair_registry` 增加 `resolve_http_getter` / `resolve_neuro_getter`

### 五项技术债全量修复（2026-06-13 · v10 线内迭代）

- **ci/cd**：`fhd-release-orchestrator.yml` tag 编排 CVM+K8s+桌面/Web/Android；`fhd-ci-cd` 监听 `FHD/v*`；production K8s 无 kubeconfig 则 fail；Android release 统一 tag
- **types**：mypy 解禁 `mod_sdk`/`neuro_bus`/`routes`/`legacy`；`count_type_debt.py` 棘轮；ESLint `no-explicit-any` error（Chat 债务文件 warn）
- **sql**：`sql_identifiers.py` + P0 标识符拼接修复；`count_raw_sql.py` 棘轮；`test_sql_identifiers.py`
- **frontend**：ChatView 拆至 `components/chat/*`；`useChatPersistence`/`useChatTaskList`；vue-i18n zh-CN/en-US；`resolveApiError.ts`
- **docs**：`MYPY_BATCH_STATUS.md`、`SQL_RAW_INVENTORY.md`、`I18N_ROLLOUT.md`、`deploy/RELEASE_CHECKLIST.md`

### 技术债计划目标收尾 Phase 7–12（2026-06-13 · v10 线内迭代）

- **Phase 7**：`useChatView.ts` facade + `useChatOrchestration`/`useChatWorkflowPanel` 等子 composable；`ChatView.vue` <400 行；去 `@ts-nocheck`
- **Phase 8**：`compat_db` SQL 拼接 SSOT + `products_pg_*` 写路径；`count_raw_sql` 棘轮 **0**；`test_compat_products_sqli.py`
- **Phase 9**：mypy 严格岛 + 宽口径分批（`tests.*` ignore）；middleware/di 类型修复；Ruff `ANN` 启用
- **Phase 10**：Chat/Login/Settings `$t()`；auth `error_envelope`；`resolveApiError` 接线
- **Phase 11**：`count_type_debt` 棘轮 **0**（any / type-ignore / nocheck）；`tsconfig.build` 全 strict
- **Phase 12**：全量门禁见 `START_HERE.md` §技术债门禁；CD RC 需仓外 `FHD_PUSH_*` / `KUBE_CONFIG_B64`

### 三项技术债清偿（2026-06-13 · v10 线内迭代）

- **refactor(errors)**：`app/errors.py` 扩展 Mod/Workflow/ExternalService/Validation 等业务异常 SSOT；`operational_errors.py` 拆为 `INFRA_TRANSIENT`/`DATA_SHAPE`/`RECOVERABLE_ERRORS`；全仓迁移、`app/` 下旧符号 `OPERATIONAL_ERRORS` 清零；payment/auth 域窄 catch + `PaymentError`；新增防回归门禁 `scripts/ci/check_operational_errors_gate.py`
- **refactor(frontend-types)**：`ApiResponse` SSOT 于 `types/api.ts`；`ModManifest`/`ModCatalogItem` 拆分；`ApiChatMessage`/`UiChatMessage` 拆分；消除组件内重复 interface
- **test(coverage)**：取消 `CI_STABLE_ONLY`；`source=[app]` 全量口径；清空 `collect_ignore`；修复 routing/coverage_ramp 运行时 skip
- **test(rotten-fix)**：移除 stable-only 跳过后暴露的腐烂测试**全量修复**，后端 `tests/` **1780 passed / 101 skipped / 0 failed / 0 error**（`source=[app]`）。生产侧最小回归修复：`retry_handler` 纳入 `sqlite3.OperationalError`、`session_cache` 补 `delete()`/`make_key()`、`product_app_service.get_products` 接受 `unit_name`/`model_number` 并归一、`init_db.init_im_tables`、IM WS 测试模式 `X-User-ID` 回退、`metrics.record_ai_call`、`mobile_api` `per_page=0` 防除零、neuro `bus`/`health_monitor`/`sla_controller` 行为对齐
- **test(coverage-baseline)**：`fail_under` 由失真的 `58`（旧窄 include 口径）按全量诚实基线**下调为 `35`**（实测 36.13%，~1pt 余量）；提升覆盖率单独立项，禁止再用窄 include 凑数

### v10 交付前全量修复（2026-06-12 · v10 线内迭代）

- **feat(android)**：AuthScreen 密码/手机号 OTP 双模式；NavHost 注册 `CONNECT`/`WORKBENCH`；发现/我的入口工作台
- **test(android)**：`RoutesTest` + `NavRoutesInstrumentedTest`；gradle 单测/instrumented 依赖；lint 门禁启用
- **docs(android)**：`VERSION.md` Android 签约级；`MOBILE_ANDROID.md` / `CLAIMED_VS_ACTUAL` 对齐
- **test(backend)**：time_rail / production_line_event / business mount / shipment_parser / mod_store_catalog 单测；CI 稳定子集扩面
- **test(frontend)**：修复 `plannerPagePaths` 租户隔离 mock；Vitest gate ≥50% 绿
- **docs(v2)**：`*_v2` 24 模块为受控双入口 SSOT（非 tech debt）；allowlist guard 零漂移
- **fix(except)**：`chat_stream_limit` / `agent_runner` / `inference_tasks` / 流式 bridge 缩窄为 `OPERATIONAL_ERRORS`
- **deps**：生产 lock SSOT 为 `deploy/requirements-server-api.lock.txt`（见 `scripts/dev/check_requirements_lock.py`）
- **release 制品核对（2026-06-12）**：Win Enterprise `XCAGI-Enterprise-Setup-10.0.0-x64.exe`（CDN）；macOS dmg 见 `config/download_release.json`；Docker `docker/Dockerfile.fhd-api`；Android `./gradlew assemble*Release` + CI `fhd-release-android.yml`

### 四阶段架构与可靠性闭环（2026-06-12 · v10 线内迭代）
- **evidence**：Round-1 归档 `acceptance-round1-invalid-20260612.yaml`；Round-2 k6 已启动（ES5 兼容 `k6_7d_contract.js` · 镜像 `0.50.0`）
- **obs**：`export_m0_panels.sh`、`check_round2_metrics_gate.sh`、`xcagi-slo.json` 五域面板、`staging_rollout_metrics.sh`
- **capacity**：`capacity-planning.md` §6 staging k6 + probe 实测
- **deploy**：`Dockerfile.fhd-api` Gunicorn；`deploy_k8s_staging.sh` 2 副本；`k8s/overlays/staging/`
- **adr**：`ADR-route-a-desktop-private.md`；`M0-remaining-gaps.md` 更新
- **ci**：`capacity-staging-monthly.yml`、`legacy-usage-weekly.yml`
- **fix(metrics)**：登录/手机验证码 `auth_login_duration_seconds`、流式 `chat_stream_first_byte_seconds`
- **fix(admin-console)**：挂载 `im_routes`；时间轨 MODstore 不可达时 degraded 200 替代 503；全景 HTML 字体改 `fonts.googleapis.cn`；管理端跳过 IM 未读轮询
- **fix(all-hands)**：MODstore 单员工汇报 300s 超时，避免 19/20 卡 95%；收集阶段进度封顶 88%；ServerFunctions 阶段文案与停滞提示
- **fix(admin-console)**：本地 duty-graph health 不再把「未安装 employee_pack」误标为 catalog 缺岗，编制图谱恢复展示；`missing_local_employee_packs` 区分本机未落盘
- **test**：`test_slo_metrics_histogram.py`

### 行业种子分层隔离 L2（2026-06-12 · v10 线内迭代）
- **feat(backend)**：`industry_seed.py` + `POST /api/mod-store/install-industry-seed`（池内 copy → Catalog 兜底；换行业卸载其它 open 中性 Mod）
- **feat(package)**：`industry-seeds/` 只读池（`onboarding_open` 行业）；`stage-industry-seeds.ps1` + `verify-industry-seeds.ps1`
- **feat(web)**：引导 `runBootstrap` 优先 `installIndustrySeed`；L3 定制仍 `installMod`

### 办公 employee_pack Planner 桥接（2026-06-12 · v10 线内迭代）
- **feat(backend)**：`employee_runtime` 包（loader / executor / risk_gate / agent_runner）对齐 MODstore `execute_employee_task`；`employee_tool_registry` 合并进 `get_workflow_tool_registry`
- **feat(backend)**：工具名 = pack_id；装包/卸载/启动 warm scan + `invalidate_workflow_tool_registry`；bridge `POST .../execute`、`GET /api/platform-shell/employee-tools`
- **feat(web)**：`useOfficeEmployeePackReady`；runBootstrap / Mod Store 装齐后刷新 registry；Mod Store `?tab=office` + driver 教程验收

### 人工试用阻断修复（2026-06-12 · v10 线内迭代）
- **feat(web)**：注册 `/im` 路由与侧栏「消息」入口；未读角标 + `useImUnreadBadge`
- **fix(web)**：企业版不再被平台壳拦截设置/Mod 商店/IM；跳过首次引导拦截员工工作台
- **fix(web)**：设置页「关于」版本读取 `package.json`（10.0.0）；商标导出副窗默认文案
- **fix(chat)**：流式桥接线程异常转为 SSE error 事件；修茈平台连接失败返回明确 503 而非空流
- **fix(market)**：`XCAGI_USE_REMOTE_MARKET=1` 优先于本地 `.env.local-market`，避免演示 shim 误挡官网 LLM
- **fix(backend)**：`httpx` 传输错误纳入 `OPERATIONAL_ERRORS`；流式桥接线程异常转为 SSE error 事件

### 桌面/移动上线阻断项修复（2026-06-12 · v10 线内迭代）
- **fix(desktop)**：`update-available` 后自动 `downloadUpdate`；`installUpdate` 校验已下载；preload 暴露 `setBadge` / `showNotification` IPC
- **fix(android)**：Release 允许局域网 HTTP/ws（`network_security_config`）；LAN WebView 注入 `session_id` cookie；推送注册失败可见提示
- **fix(android)**：Crashlytics mapping 上传默认关闭（`-PuploadCrashlyticsMapping=true` 显式开启）；新增 `fhd-release-android.yml`
- **fix(backend)**：审批操作人优先 session 鉴权，生产不信任 `X-User-ID`（测试 `FHD_ALLOW_X_USER_ID_HEADER=1`）
- **chore**：Android `versionName` 纳入 `verify_version_anchors.py`

### 发版制品与构建链收口（2026-06-12 · v10 线内迭代）
- **fix(release)**：Enterprise Windows `XCAGI-Enterprise-Setup-10.0.0-x64.exe`（Electron 薄壳）已上传 `update.xcagi.com`；完整内嵌 PyInstaller 后端仍需 Windows 或 GitHub Actions
- **feat(scripts)**：新增 `build-windows-electron-only.sh`（Mac/Linux 交叉编译 Windows NSIS 薄壳）；Wine Docker 默认 DaoCloud 镜像
- **fix(modstore)**：`orcaterm-deploy-commands.sh` 使用 `npm ci --ignore-scripts` 跳过 onnxruntime-node 原生下载失败
- **fix(ci)**：`fhd-ci-cd.yml` docker save 路径对齐 `FHD/dist/deploy/`

### 多租户隔离锚定服务器会话（2026-06-11 · v10 线内迭代）
- **fix(backend)**：`/api/auth/me` 与 session validate 通过 `enrich_session_meta_with_tenant` 补全/自动 provision `tenant_id`；下发 `market_user_id`、`local_user_id`、`tenant_id`
- **fix(backend)**：桌面 SQLite 启动时幂等创建 `user_preferences` 表；`GET /api/workspace/prefs` 缺表时降级空数据，不再 500
- **fix(frontend)**：客户端持久化 scope 优先服务器会话（tenant → 市场用户 → FHD `session:{user.id}`），不再把未绑定租户的用户都打进 `local` 共享域

### 企业级行业二级筛选与跨设备工作区同步（2026-06-11 · v10 线内迭代）
- **feat(backend)**：`build_onboarding_industry_catalog` 合并 `industry_presets.json`，返回 `name` / `scenario` / `product_name` 二级结构及 `preview_packages`
- **feat(api)**：`GET /api/platform-shell/onboarding-industries` 企业版按 session entitlement 裁剪开放行业（legacy `taiyangniao-pro` / `sz-qsm-pro` 与中性 mod 对齐）；返回 `selected_industry_id` / `enterprise_filter_applied`
- **feat(api)**：`GET/PATCH /api/workspace/prefs` 按租户/会话持久化行业选择、员工开关、引导完成态；`GET/POST /api/system/industry` 登录用户读写租户 prefs，未 entitlement 行业返回 403
- **fix(frontend)**：`ProductOnboardingView` 行业 chip 以服务器 catalog 为准；登录后 hydrate 工作区 prefs，员工开关与引导状态跨设备一致

### 企业端工作流员工多租户隔离（2026-06-11 · v10 线内迭代）
- **fix(frontend)**：员工开关、工位快照/工时、当前扩展 Mod、聊天 sessionId、聊天记录、能力库 catalog 缓存、Kitten 可视化员工选择均按 `tenant_id` 分域持久化；登录/切换账号后自动重载对应租户数据，避免同浏览器串租户

### 企业端移除「员工视图」侧栏入口（2026-06-11 · v10 线内迭代）
- **fix(frontend)**：取消「员工工作台 → 员工视图」；企业端仅保留「员工空间」；旧 `/other-tools` 重定向至员工空间；管理端 `:5011` 改为「编制图谱」子项
- **fix(frontend)**：企业账号侧栏/沙箱/壳模式不再展示「流程全景」；路由与副窗链接隐藏；管理端 `:5011/admin/` 保留

### 管理端 other-tools 改为编制图谱（2026-06-11 · v10 线内迭代）
- **fix(admin-console)**：`/other-tools` 管理端直接渲染 `DutyRosterGraphPanel`（编制图谱）；侧栏管理端显示「编制图谱」；企业端仍为「员工视图」开关页

### 侧栏「员工可视化」命名对齐（2026-06-11 · v10 线内迭代）
- **revert**：撤销仅改文案的「员工可视化」命名；编制图谱与员工视图分轨

### 管理端侧栏恢复「员工工作台」分组（2026-06-11 · v10 线内迭代）
- **fix(admin-console)**：从 aux 尾部菜单移除平铺的「员工视图/员工空间」，改由 `CORE_MENU_ITEMS_BASE` 的「员工工作台」子菜单承载；放开管理端 `workflow-visualization` 路由

### 员工视图独立页（2026-06-11 · v10 线内迭代）
- **feat(frontend)**：`/other-tools` 改为独立「员工视图」页（`WorkflowEmployeeInspector` + 状态/进度），移除与侧栏重复的「员工空间」「流程全景」卡片

### 员工视图内嵌工作流员工开关（2026-06-11 · v10 线内迭代）
- **feat(frontend)**：`OtherToolsView` 首卡改为「员工视图」，内嵌 `WorkflowEmployeeSelectPanel`（与副窗「一键托管」开关同步）；侧栏/路由标签由「流程与员工」改为「员工视图」

### 设置页恢复 App 扫码配对二维码（2026-06-11 · v10 线内迭代）
- **feat(frontend)**：`SettingsView`「移动端连接」展示配对 QR（`/api/mobile/v1/pairing/issue`），App「扫码连电脑」可绑定本机宿主
- **fix(mobile+frontend)**：QR 改为 JSON（含 host/port/nonce）；App 向电脑 exchange 而非本机 127.0.0.1，并保存 `host:port`（修复 :5100 误连 :5000）
- **fix(backend)**：`discover-hint.api_port` 与 `FASTAPI_PORT`/`XCAGI_API_PORT` 对齐

### MOD 扩展内嵌 AI 市场目录（2026-06-11 · v10 线内迭代）
- **feat(backend)**：`GET /api/mod-store/market-catalog` 代理修茈 `/api/market/catalog`，按 `collection` / `artifact` / `material_category` 分页拉取并合并本机安装态
- **feat(frontend)**：`ModStore.vue` 侧栏对齐网页 AI 市场（办公员工包 / 附属包1 / 工作流 / AI 员工），分类数据直载无需外链跳转

### 小猫分析 · 可视化 AI 员工（2026-06-11 · v10 线内迭代）
- **feat(frontend)**：小猫分析接入办公员工附属包1（柱状/折线/饼图/看板可视化员 + JSON 量化报告员同栏），员工选择条 + 主题色 ECharts；综合看板多图联动
- **feat(modstore)**：`bootstrap_kitten_chart_employees.py` / `publish_kitten_chart_employees.py`；chart-* 员工与报告员一并归入「办公员工附属包1」

### AIOPEN 生态入口图标重设计（2026-06-11 · v10 线内迭代）
- **ui**：AI生态应用卡片替换 🤖 emoji 为品牌 SVG（开放弧 + 虚拟光标 + MCP 节点），与 AIOPEN 面板视觉统一

### AIOPEN 发给 AI 助手一键配置 + MCP 403 修复（2026-06-11 · v10 线内迭代）
- **fix**：MCP 健康检查改 manifest GET；MCP 配置 URL 固定指向后端 :5100 非 Vite :5001
- **feat**：「复制发给 AI 助手 · 一键配置」— 含说明链接 + MCP JSON + 验证步骤，可粘贴 ChatGPT/Claude/Kimi

### AIOPEN MCP CSRF 豁免（2026-06-11 · v10 线内迭代）
- **fix(csrf)**：`/api/aiopen/*` 与旧 `/api/ai/qclaw/*` 变更 POST 不再要求 CSRF（外部 Agent 无 Cookie）；面板 MCP 自检改 GET 探测

### AIOPEN 多 AI 客户端 MCP 配置（2026-06-11 · v10 线内迭代）
- **feat(frontend)**：面板支持 Cursor / Claude / VS Code / Windsurf / Trae / 其他 六种 AI 软件分别安装或复制配置，可同时配置多个
- **feat(backend)**：`/api/aiopen/install` 返回 `clients[]` 多客户端安装包

### AIOPEN MCP 对齐业界接入（2026-06-11 · v10 线内迭代）
- **feat(mcp)**：`GET /api/aiopen/install` 安装包（Cursor deep link / npx mcp-remote / Python stdio 桥）；`GET /api/aiopen/mcp` 探测；响应头 `MCP-Protocol-Version` + `Mcp-Session-Id`；`tools/call` 人类可读输出
- **feat(frontend)**：面板「在 Cursor 中安装」一键 MCP、MCP 自检、工具列表预览
- **feat(scripts)**：`scripts/dev/aiopen_mcp_stdio.py` stdio→HTTP 桥接

### AIOPEN 面板小白化 + 接入说明链接（2026-06-11 · v10 线内迭代）
- **feat(aiopen)**：`GET /api/aiopen/guide` 公开接入说明（JSON 或 `?format=markdown`），供其他 AI 阅读后自行配置 MCP
- **feat(frontend)**：面板「发给其他 AI」— 一键复制说明链接 / 复制给 AI 的提示语

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

### Mac 主跑 / 服务器跟 git（混合日更 · 2026-06-10 · v10 线内迭代）
- **feat(automation)**：`automation_primary.py` — `MODSTORE_AUTOMATION_PRIMARY` + `ROLE` 门禁，服务器跳过 digest/08:15–08:25 编排
- **fix(digest)**：`digest_action_items.ensure_table` 按方言选用 Postgres SERIAL / SQLite AUTOINCREMENT
- **fix(audit)**：`surface_audit_deps` 从 `MODSTORE_DEPLOY_HEALTH_URL` 推断内部 API（生产 :9999）
- **ops(closure)**：`patch_prod_daily_closure.sh` follower 块 + `trigger_server_git_sync.sh`；Mac `MODSTORE_SYNC_DEPLOY_BASH`

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
| **v5.0** | 稳定 | Neuro-DDD 架构 + 性能监控 + 审批流 |
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

### 🆕 新增核心能力

| 能力 | 说明 | 重要性 |
|------|------|--------|
| **Neuro-DDD 架构** | 12 个神经域自治协同（含 `ShipmentNeuroDomain` 出货域） | ⭐⭐⭐⭐⭐ |
| **NeuroBus 8 大机制** | 去重、追踪、限流、熔断、SLA 等 | ⭐⭐⭐⭐⭐ |
| **神经反射弧** | <1ms 规则匹配快速响应 | ⭐⭐⭐⭐ |
| **潜意识/显意识双模** | <10ms / <200ms 双模处理 | ⭐⭐⭐⭐ |
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
    + MODstore / Mod Manager + 审批流
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
