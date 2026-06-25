# 手机发版闭环 · 落地方案（MOBILE_RELEASE_LOOP_PLAN）

> 目标：把"**发版员发现最新版本 → 三端对齐 → 审批 → 构建签名 → 分发 → OTA 公告 → 验证回滚**"做成一条真实、可观测、幂等、可回滚的闭环，替代当前"手工 scp APK + 改 .env + 重启"。
>
> 状态：方案稿（未动代码）。生成日期 2026-06-24。跨 `FHD/`（手机 app + 版本 SSOT）与 `成都修茈科技有限公司/MODstore_deploy/`（编排 + OTA）两棵树。

---

## 0. 一句话闭环

```
触发 → ①发现目标版本(确定性) → ②三端就绪对齐(确定性判定 + LLM点评) → ③版本SSOT落盘
     → ④redline审批门(admin) → ⑤CI构建签名(workflow_dispatch) → ⑥COS/nginx分发
     → ⑦OTA版本公告(写数据,非env) → ⑧smoke验证·汇报·失败回滚
```

## 1. 已定关键决策（本方案据此设计）

| 决策点 | 选择 | 设计影响 |
|---|---|---|
| 对齐语义 | **混合：确定性提议 + LLM 点评** | 目标版本由 SSOT/git 确定性发现；`ready` 由确定性信号判定；LLM 只在每官签字上附"就绪/风险点评"，不决定共识。抗配额 403。 |
| iOS | **先建 iOS 原生工程再纳入** | iOS = 与 108 文件 Android 对等的原生 SwiftUI 大工程，是长杆。两端(Android+鸿蒙)闭环先全闭，iOS 工程+分发就绪后接入。 |
| iOS 分发 | **走 $99 App Store/TestFlight** | 企业 in-house($299,即时OTA)对单人运营不可用(需100+员工+禁外部客户)。iOS"发布"=提审上架，**无即时 OTA**，与 Android/鸿蒙的 OTA 性质不同。 |
| 构建位置 | **触发现有 CI `workflow_dispatch`** | 签名密钥/keystore 留在 CI secrets，modstore 服务器只持一个**触发用** GitHub token，不碰签名。 |
| 本次交付 | **落地方案文档** | 即本文。审完再动代码。 |

## 2. 现状基线（已核实，file:line）

### 2.1 三端 app —— 满血原生，非 WebView 壳
- Android：`FHD/mobile-android/` 共 **108 个 Kotlin 文件**（Compose UI / Room / IM 重连 / 配对 QR / 鉴权策略）。构建 `./gradlew assembleEnterpriseRelease`，JKS 签名（env `XCAGI_ANDROID_KEYSTORE*`），产物 `app/build/outputs/apk/enterprise/release/`。CI：`.github/workflows/fhd-release-android.yml`。**完整可用。**
- 鸿蒙：`FHD/mobile-harmony/` 共 **37 个 ArkTS 原生页**。构建 `scripts/build-hap.sh --version X --mode release`（`hvigor assembleHap`），签名走 build-profile，发布 `scripts/publish-release-harmony.sh`。CI：`fhd-release-harmony.yml`（**不随 tag 自动触发，需手动 dispatch**）。**构建完整，OTA 缺。**
- iOS：**纯空壳**——只有 `FHD/mods/_employees/mobile-ios-release-officer/` 员工骨架，无 Xcode 工程 / 无 `.pbxproj` / 无 fastlane。

### 2.2 发版员现状
- 三个手机发版员（`mobile-{android,harmony,ios}-release-officer`）是 MODstore 通用模板，manifest 声明 `handlers:['llm_md','echo']`，**只会产文字，不 build/sign/publish**。
- 真发布链 `INSTALLER_EMPLOYEE_CHAIN`（P5/P6/P9，`digest_daily_line_chain.py:42`）用的是 `deploy-release-officer` + `push-update-context-officer`，干的是**桌面 installer / electron-updater / COS·SKU**，与手机 APK 无关。
- 线链调度**在进程内**经 `plan_and_dispatch → employee_orchestrator → execute_employee_task`（LLM cognition + handlers）执行，非 HTTP 调 mod 的 `/run`。→ 闭环统一走 `execute_employee_task` 路径，给它加"真手"。

### 2.3 协作底座（部分存在）
- ✅ collab thread（`employee_autonomy_service.create_collab_thread / post_collab_message`）、AI 群聊（`FHD/app/application/ai_group_chat_service.py`）、suggestion（`create_employee_suggestion / dispatch_suggestion`）。
- ✅ redline 审批门（`redline_approval_gate.py`，**admin-only 真实**，非员工投票）。
- ❌ **多员工 verdict → 共识聚合**这层不存在，是本方案核心新建项。

### 2.4 版本 SSOT —— 散落 6+ 文件，且门禁只查 Android
| 源 | 文件 | 现值 | CI 门禁 |
|---|---|---|---|
| 主锚 | `FHD/VERSION.md:12` | 10.0.0 | — |
| Android | `FHD/mobile-android/app/build.gradle.kts:22-23` | code 10 / name 10.0.0 | ✅ 查 |
| 鸿蒙根包 | `FHD/mobile-harmony/oh-package.json5:4` | 10.0.0 | ❌ 漏 |
| 鸿蒙清单 | `FHD/mobile-harmony/AppScope/app.json5:6` | code 100000 / name 10.0.0 | ❌ 漏 |
| 鸿蒙 entry | `FHD/mobile-harmony/entry/oh-package.json5:3` | 10.0.0 | ❌ 漏 |
| 下载/营销 | `FHD/config/download_release.json` | 10.0.0 | ❌ 漏 |
| OTA 服务 | `app_config_api.py:36-39` env `XCAGI_ANDROID_LATEST_*` | 默认 10/10.0.0，**全仓无处 SET** | ❌ 不在任何门 |

门禁：`FHD/scripts/dev/verify_version_anchors.py` 仅覆盖 android（+后端/前端/桌面）。

### 2.5 编排器现状
- `daily_release_train_orchestrator_job.py` 默认 `shadow` 影子模式（只记录不真跑）；P-App 路由 `APP_LANE_EMPLOYEE_IDS` 仅含 android+ios，**漏鸿蒙**。
- OTA `/app/config` 只服务 android；iOS/鸿蒙无版本字段。
- 可观测：`time_rail_runtime` 已有 **APPB / P-App** 节点可直接挂。

---

## 3. 闭环架构 · 九阶段（标 ✅复用 / 🔨新建）

### ①触发
- 入口：每日 cron（apscheduler，复用）/ 小C·admin 手动「发版」/ tag。
- 前置守卫：scheduler 心跳活（`daily_pipeline_lock.scheduler_heartbeat_status`，复用）；LLM 配额探针——不足则②退化为纯确定性签字（无 LLM 点评），loop 不死。

### ②发现目标版本（确定性，无 LLM）🔨
- 读 `VERSION.md` 主锚 + 最新 git tag `FHD/v*` + `download_release.json`，算 `target_version` 及每平台 current↔target diff，产「提议单」。
- 新建：`release_version_discovery.py`。

### ③三端就绪对齐（确定性判定 + LLM 点评）✅底座 + 🔨聚合器
- 协调员开 collab thread / AI 群，@三平台官，贴提议单。
- 每官经 `execute_employee_task` 跑就绪体检：采集**确定性信号**（该平台 CI 最近一次构建是否绿、版本 diff 合法、产物可在此版本构建）→ 得 `ready`（确定性）；再让 LLM 生成一段 `commentary`（就绪/风险点评，仅注解）。
- 🔨 **共识聚合器**：收三份 verdict，`aligned ⇔ 所有在编平台 ready`；iOS 未就绪前 in_scope 自动剔除/标 `blocked:no-project`。把每官 commentary + blockers 汇总贴回群。

### ④版本 SSOT 落盘 🔨
- `aligned` 后，`bump_mobile_version.py` 原子写全部 6 源（含鸿蒙 100000 制 versionCode 换算）。
- 扩后的 `verify_version_anchors.py` 当门禁卡一致性（补鸿蒙 3 文件 + download_release）。**这是真"对齐"——强制，非祈祷。**

### ⑤审批门 ✅
- 发布=redline 变更 → `EmployeeChangeRequest(status=pending)` → 你 admin 批。批前全部可逆（仅文件/记录）。复用 `redline_approval_gate`。

### ⑥构建+签名（CI workflow_dispatch）✅CI + 🔨真手
- 🔨 新建员工动作 `ci_dispatch`：调 GitHub API `POST /repos/{repo}/actions/workflows/{wf}/dispatches`（ref + inputs `{version}`）→ 轮询 run → 取产物。token 仅触发用，签名密钥留 CI。
- android→`fhd-release-android.yml`（已自动）、harmony→`fhd-release-harmony.yml`（🔨补进编排 dispatch）、ios→`fhd-release-ios.yml`（🔨待建）。

### ⑦分发 ✅
- 拉产物 → COS 上传（`upload-xcagi-releases-cos.py`）+ nginx `/var/www/update`；回填 `download_release.record_installer_push`。

### ⑧OTA 版本公告（写数据，非 env）🔨
- 🔨 把"每平台最新版本"从裸 env 挪进 `download_release.json`（或 DB），`app_config_api` 改为读该数据源 + 按 `platform` 分平台返回；新增 harmony（及 iOS 占位）字段。→ loop 写数据即生效，**免 env+重启**。

### ⑨验证·汇报·回滚 ✅底座 + 🔨smoke
- 🔨 smoke：拉 `/api/app/config?platform=&sku=` 断言返回新版 + 产物 URL HEAD 200。
- 汇报进 AI 交流圈（reporter→collab feed，复用）。
- 回滚：smoke 失败 → OTA 数据回退到 last-known-good；redline `auto_rollback` 标记。复用。

横切：每阶段以 `ReleaseAlignmentRecord.id + version` 幂等；观测挂 `time_rail_runtime` APPB；**显式 env 翻 `shadow→primary` 才真跑**。

---

## 4. 新建组件 · 接口契约

### 4.1 版本 SSOT 统一
- `FHD/scripts/dev/bump_mobile_version.py`
  - `bump(target: str, *, check_only=False) -> dict`：写/校验 6 源；鸿蒙 versionCode = `major*10000 + minor*100 + patch`（10.0.0→100000）。
- 扩 `verify_version_anchors.py`：anchors 增 `mobile-harmony/oh-package.json5`、`AppScope/app.json5`、`entry/oh-package.json5`、`config/download_release.json`。

### 4.2 共识聚合器（核心缺口）
- 模型 `ReleaseAlignmentRecord`：`{id, target_version, target_codes:{android:int,harmony:int}, proposal:{base,git_tag,diff}, verdicts:{platform:{officer_id,ready,blockers[],current,commentary}}, consensus:'proposed|aligned|blocked', in_scope[], change_request_id, ci_runs{}, smoke{}, status, prev_good_version}`。
- `aggregate(verdicts, in_scope) -> consensus`：全 ready 则 aligned。
- 存储复用 collab thread 做消息轨；聚合逻辑新建 `release_consensus.py`。

### 4.3 发版员真手
- `ci_dispatch` 动作（注册进 `execute_employee_task` handler 集 / 作 ctx 工具）：`dispatch(wf, ref, inputs) -> run_id`；`await_run(run_id, timeout) -> {conclusion, artifacts}`。token=env `GITHUB_DISPATCH_TOKEN`（仅 `actions:write`）。

### 4.4 鸿蒙 OTA
- `app_config_api`：加 `XCAGI_HARMONY_LATEST_*`（过渡）→ 终态读 `download_release.json` 的 per-platform 块；`APP_LANE_EMPLOYEE_IDS` 补 `mobile-harmony-release-officer`。

### 4.5 闭环编排器
- `mobile_release_loop.py`（modstore_server）：按 `ReleaseAlignmentRecord.status` 状态机推进①–⑨，幂等、挂审批门、挂 time_rail、带回滚。默认 shadow，env `MODSTORE_MOBILE_RELEASE_LOOP_MODE=primary` 开真跑。

---

## 5. iOS 工程工作流（长杆，诚实框定）

iOS 不是"补个壳"——Android/鸿蒙都是满血原生，iOS 要做到对等是**从零的原生 SwiftUI app**：
- **前置硬依赖**：**Apple Developer Program（$99/yr，已定走此条）**；签名证书 + provisioning profile；**macOS CI runner**（GitHub macOS runner 或自托管 Mac）跑 `xcodebuild archive` + fastlane。
- **分发=App Store/TestFlight，无即时 OTA（已定）**：企业 in-house 分发($299，能像 APK 即时 OTA)对单人运营不可用——需 D-U-N-S + 100+ 员工，且**禁止分发给外部客户**，给客户用即吊销证书。故 iOS 客户端只能走商店：CI 打包 `.ipa` → 上传 App Store Connect → **提交审核** → 过审上架。**iOS 没有"改版本号手机就弹更新"的即时 OTA。**
- **工作量**：工程脚手架 → 核心域对齐（鉴权 / IM 重连 / 聊天 / 配对，镜像 108 文件 Android）→ 签名+CI → 提审上架。量级=周，且卡在 Apple 账号开通 + 商店审核周期（数小时~数天，不可控）。
- **建议**：iOS 作并行长杆；先建脚手架 + 核心(鉴权/IM/聊天) MVP 对等，再以 `fhd-release-ios.yml`（`xcodebuild` + fastlane `pilot/deliver`）接入闭环。在此之前闭环对 iOS 标 `blocked:no-project`，两端先全闭。
- **闭环差异**：iOS 走的不是⑦OTA 公告，而是**⑤'提审分支**——CI 上传 App Store Connect + 提审；⑦/⑧对 iOS 退化为"提审状态轮询 + 过审通知"，无"OTA 抬版/即时回滚"（商店版本一旦上架，回滚=再提一审）。

---

## 6. 文件清单（新建/改）

| 动作 | 路径 | 内容 |
|---|---|---|
| 🔨新 | `FHD/scripts/dev/bump_mobile_version.py` | 6 源原子写/校验 |
| ✏️改 | `FHD/scripts/dev/verify_version_anchors.py` | 补鸿蒙3 + download_release |
| 🔨新 | `.../modstore_server/release_version_discovery.py` | ②确定性发现 |
| 🔨新 | `.../modstore_server/release_consensus.py` | ③聚合器 + 模型 |
| 🔨新 | `.../modstore_server/mobile_release_loop.py` | ⑨阶段状态机编排 |
| ✏️改 | `.../modstore_server/employee_executor.py` | 注册 `ci_dispatch` 动作 |
| ✏️改 | `.../modstore_server/app_config_api.py` | harmony/ios 字段 + 读 download_release |
| ✏️改 | `.../modstore_server/digest_vibe_line_dispatch.py` | `APP_LANE_EMPLOYEE_IDS` 补鸿蒙 |
| 🔨新 | `FHD/.github/workflows/fhd-release-ios.yml` | iOS CI（待工程就绪） |
| 🔨新 | iOS Xcode 工程（`FHD/mobile-ios/`） | 见 §5 |

## 7. 分期里程碑

- **M0 版本 SSOT 承重墙**：bump 脚本 + 扩 verify 门。DoD：改一个版本号，一条命令同步 6 源，CI 门挡住任何漂移。
- **M1 OTA 数据化 + 鸿蒙就位**：OTA 读 download_release、加 harmony 字段、P-App 补鸿蒙。DoD：`/app/config?platform=harmony` 返回鸿蒙版本。
- **M2 真手**：`ci_dispatch` 动作，手动驱动一次 android CI 全程。DoD：一条 API 触发 CI→产 APK→COS→OTA 抬版，手机能"检查更新"到新版。
- **M3 对齐闭环（两端）**：发现②+聚合器③+编排器⑨（shadow），混合点评。DoD：shadow 跑出完整 alignment_record + 群里三端签字汇总。
- **M4 翻 primary + 审批 + 回滚**：挂 redline 门、smoke、回滚，env 翻 primary。DoD：一次真发版（android+鸿蒙）端到端闭环，故意制造 smoke 失败验证回滚。
- **M5 iOS 接入**：iOS 工程 + 分发 + CI 就绪后纳入。DoD：三端齐发。

## 8. 边界 · 风险 · 未决

- **生产前置**（备忘录 06-22 只读快照，未重核）：scheduler inactive + LLM 配额 403。代码全对也要先保证调度器活 + 配额够，否则 loop 在生产不跑。
- ~~iOS 分发模型未决~~ **已定：iOS 走 $99 App Store/TestFlight，提审上架、无即时 OTA**（企业 in-house 对单人运营不可用）。见 §5。iOS 在闭环里走⑤'提审分支，非⑦OTA。
- **GitHub dispatch token** 落 modstore 服务器：需最小权限 `actions:write` + 轮换。
- **shadow→primary** 必须人为显式翻，避免半成品自动真发。
- 现"两套执行面"（mod `/run` echo vs `execute_employee_task`）统一收敛到后者；mod `/run` 仅留手动/测试。

## 9. 验收口径
每个里程碑以上方 DoD 为准，且新增逻辑须有真断言测试（非恒真），版本/OTA 改动须过扩后的 verify 门。M4 的"故意 smoke 失败→回滚"是整条闭环可信度的关键验收。
