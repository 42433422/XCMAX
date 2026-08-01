# XCAGI 1.0.0.0 → 1.0.0.1 更新清单

> 生成时间：2026-07-31（第三轮全量扫描后定稿，覆盖官网/COS/dashboard/MODstore 全量）
> 升级范围：XCMAX 全项目（FHD + MODstore + 根仓 workflows + 企业官网 + dashboard + COS 部署脚本）
> 校验状态：✅ verify_version_anchors 通过 / ✅ 478 后端测试通过 / ✅ workflow 已同步根仓 / ✅ 第二轮 42 mod 测试通过 / ✅ SSOT gate mods+version OK
> 第二轮补漏：workflow-visualization-bridge manifest（3 副本）+ dashboard "v10 锁恒" 表述（3 文件）+ release/VERSION
> 第三轮补漏：官网/COS 部署脚本（11 个）+ desktop-shell 3 个文件 + BRANCHING.md + runbook 示例 + market/public/download-release.json + corp-butler.js（已含 1.0.0.1，仅补登记）+ post-deploy-check.sh + upload-all-xcagi-cos.sh

---

## 1. SSOT 源头（1 处）

| 文件 | 行 | 改动 |
|---|---|---|
| `FHD/VERSION.md` | L12 | 稳定产品版本 `1.0.0.0` → `1.0.0.1` |
| `FHD/VERSION.md` | L15/L21-25/L31 | 所有反引号包裹的 `1.0.0.0` → `1.0.0.1` |
| `FHD/VERSION.md` | L73 | 最后更新日期 `2026-07-12` → `2026-07-31`，版本号同步 |

> 工具链兼容版本 `1.0.0` 不变（`_derive_toolchain_version` 自动取产品版本前三段，1.0.0.1 → 1.0.0）。

---

## 2. version_sync.py 自动同步（16 个文件）

执行 `python scripts/dev/version_sync.py --apply` 自动改写以下锚点：

| 文件 | 字段 | 改动 |
|---|---|---|
| `FHD/pyproject.toml` | version | → 1.0.0.1 |
| `FHD/XCAGI/pyproject.toml` | version | → 1.0.0.1 |
| `FHD/app/fastapi_app/factory.py` | L81 `version="..."` | → 1.0.0.1 |
| `FHD/app/infrastructure/mods/manifest.py` | L221 `current_version` | → 1.0.0.1 |
| `FHD/mobile-flutter-poc/android/app/build.gradle.kts` | injectedVersionName | → 1.0.0.1 |
| `FHD/mobile-flutter-poc/lib/src/api/mobile_api.dart` | versionName | → 1.0.0.1 |
| `FHD/desktop/resources/build-info.json` | version | → 1.0.0.1 |
| `FHD/config/download_release.json` | marketing_version | → 1.0.0.1 |
| `FHD/config/release_train.json` | product_version | → 1.0.0.1 |
| `成都修茈科技有限公司/FHD/config/release_train.json` | product_version | → 1.0.0.1 |
| `FHD/contracts/openapi.json` | info.version | → 1.0.0.1 |
| `FHD/setup.iss` | MyAppVersion | → 1.0.0.1 |
| `FHD/tools/XcagiDownloader/Models/AppSettings.cs` | 默认 return | → 1.0.0.1 |
| `FHD/scripts/package/build-installer.sh` | VERSION 默认值 | → 1.0.0.1 |
| `FHD/scripts/package/build-installer.ps1` | $Version 默认值 | → 1.0.0.1 |
| `FHD/release/VERSION` | 版本号 | → 1.0.0.1 |

> 8 个 toolchain 锚点（frontend/desktop/package.json 等）已是 `1.0.0`，无需改。

---

## 3. 代码 fallback 手动改（8 处）

version_sync pattern 只匹配每文件第一处版本号，以下 fallback 需手动改：

| 文件 | 行 | 说明 |
|---|---|---|
| `FHD/app/fastapi_app/factory.py` | L146 | `os.environ.get("XCAGI_VERSION", "1.0.0.1")` |
| `FHD/app/fastapi_routes/xcmax_admin.py` | L355 | `_default_snapshot` 的 `"current": "1.0.0.1"`（L354 epoch 保留 1.0.0.0）|
| `FHD/app/application/aiopen/service.py` | L582/L626 | `aiopen_manifest` version + 注释 |
| `FHD/app/infrastructure/mods/manifest.py` | L202 | 错误消息 `host version is 1.0.0.1` |
| `FHD/app/application/admin_deploy_push.py` | L79/L85/L87 | `_local_version` 三处 fallback |
| `FHD/scripts/package/build-installer.sh` | L12-13 | invalid VERSION fallback |
| `FHD/tools/XcagiDownloader/Models/AppSettings.cs` | L17 | 三元表达式 fallback |
| `FHD/mobile-flutter-poc/lib/src/api/mobile_api.dart` | L583 | `profileVersionText` |
| `FHD/scripts/deploy/fhd-pack-release.sh` | L37/L41 | 版本读取 fallback |

---

## 4. CI workflows（8 个文件，18 处）

`FHD/.github/workflows/` 源文件改后，已通过 `publish_ci_workflows_to_root.py` 同步到根仓 `.github/workflows/`（加 `fhd-` 前缀）：

| 文件 | 改动处数 | 说明 |
|---|---|---|
| `release-desktop.yml` | 6 | default + choices + 4 处 shell fallback |
| `release-desktop-mac-ota.yml` | 2 | default + choices |
| `release-android.yml` | 3 | default + 2 处 raw fallback |
| `release-orchestrator.yml` | 1 | shell fallback |
| `release-web.yml` | 1 | default |
| `sunbird-installer.yml` | 1 | default |
| `fix-mac-update-feed.yml` | 2 | default + zip 文件名 |
| `publish-local-mac-feed.yml` | 2 | default + zip 文件名 |

---

## 5. mod manifest（28 个文件）

只改 mod 自身 `"version"` 字段，保留 `"xcagi": ">=1.0.0.0"` 依赖下限。

**编辑源 `FHD/mods/`（14 个）**：xcagi-erp-domain-bridge、xcagi-planner-excel-tools、xcagi-planner-bridge、xcagi-office-employee-pack-bridge、xcagi-neuro-bus-bridge、xcagi-model-payment-bridge、xcagi-lan-license-bridge、xcagi-customer-service-bridge、xcagi-core-workflow-employees、xcagi-approval-bridge、_employees/xcagi-host-foundation-employee、wechat-contacts-ai-employee、lan-gate-ai-employee、**xcagi-workflow-visualization-bridge**（第二轮补漏：原误判"无 version 字段"，实际 version 从 `1.0.0` → `1.0.0.1`）

**运行时副本 `FHD/XCAGI/mods/`（13 个）**：同上（除 _employees/xcagi-host-foundation-employee 不在副本中）

**运行时副本 `FHD/mods-admin-runtime/`（2 个）**：xcagi-customer-service-bridge（第一轮已改）、xcagi-workflow-visualization-bridge（第二轮补漏）

---

## 6. Dockerfile（1 处）

| 文件 | 行 | 改动 |
|---|---|---|
| `FHD/Dockerfile` | L27 | `LABEL version="1.0.0.1"` |

---

## 7. 下载页 / nginx / 下载清单（10 个文件）

| 文件 | 改动 |
|---|---|
| `成都修茈科技有限公司/download.html` | L979-980 DEFAULT_VERSION + DEFAULT_ANDROID_VERSION + L984 base URL |
| `成都修茈科技有限公司/download-releases.html` | L670/L744/L783 当前版本展示（保留 L751/L788/L908 历史记录）|
| `成都修茈科技有限公司/download-release.json` | version_lock/download_version/android_version + release_root/manifest_url（保留 release_history 历史条目 + L19/L153 epoch 1.0.0.0）|
| `成都修茈科技有限公司/corp-butler/download-release.json` | 同上 |
| `成都修茈科技有限公司/corp-butler/corp-butler.js` | 第三轮核查：已含 1.0.0.1 引用（与 download-release.json 联动，无需改）|
| `成都修茈科技有限公司/MODstore_deploy/market/public/download-release.json` | version_lock/download_version/android_version + release_root/manifest_url（保留 release_history 历史条目）|
| `成都修茈科技有限公司/MODstore_deploy/market/src/utils/xcagiDownloadLinks.ts` | DEFAULT_XCAGI_DOWNLOAD_VERSION + DEFAULT_XCAGI_ANDROID_VERSION + OFFICIAL_MANIFEST_URL |
| `成都修茈科技有限公司/MODstore_deploy/market/src/utils/xcagiDownloadLinks.test.ts` | mockManifest version + 5 处 URL 断言（保留 L51/L60/L63 `xcagi-v8.1.0` 作为版本参数测试输入）|
| `成都修茈科技有限公司/nginx-xiu-ci.conf` | 新增 `/xcagi-v1.0.0.1/` location 块 + L110 注释「1.0.0.1 当前稳定版」；保留 `/xcagi-v1.0.0.0/`；download-release.json alias 指向 1.0.0.1 |
| `成都修茈科技有限公司/nginx-xiu-ci-root.conf` | 同上（L143 注释）|

> nginx 策略：新建 1.0.0.1 目录，旧版 1.0.0.0 保留可下载。

---

## 7.5 COS 部署脚本 / nginx snippet（第三轮补漏，11 个文件）

第三轮扫描发现 `deploy/scripts/` 与 `deploy/nginx/snippets/` 中 COS 上传脚本和 nginx snippet 仍残留 `xcagi-v8.0.0` 旧前缀默认值与 `8.0.0` 旧文件名，已统一更新：

| 文件 | 改动 |
|---|---|
| `成都修茈科技有限公司/deploy/nginx/snippets/xcagi-cos-alias.inc.conf` | 新增 `/xcagi-v1.0.0.1/` location（XCAGI_COS_ALIAS_BEGIN 块），保留 `/xcagi-v8.0.0/` 为 LEGACY 块 |
| `成都修茈科技有限公司/deploy/scripts/sync-xcagi-releases-to-cos.sh` | L11 注释 + L18 COS_PREFIX 默认值 + L69-71 echo 提示（personal/offline 移除，仅 enterprise）|
| `成都修茈科技有限公司/deploy/scripts/setup-xcagi-cos-upload-on-cvm.sh` | L17 COS_PREFIX 示例 + L37-38 缓存预热 echo 文件名 |
| `成都修茈科技有限公司/deploy/scripts/upload-xcagi-releases-cos.py` | L17 PREFIX 默认值 + L69 verify echo 文件名 |
| `成都修茈科技有限公司/deploy/scripts/upload-one-xcagi-cos.py` | L12 PREFIX 默认值 |
| `成都修茈科技有限公司/deploy/scripts/list-xcagi-cos.sh` | L10 Prefix 默认值 |
| `成都修茈科技有限公司/deploy/scripts/cos-upload-progress.sh` | 重写 files 数组：删除 personal/offline（已冻结），仅保留 enterprise；key 改用 `prefix` 变量；文件名 `8.0.0` → `1.0.0.1`；SUMMARY 改用 `total_n` |
| `成都修茈科技有限公司/deploy/scripts/upload-all-xcagi-cos.sh` | L22-25 删除 personal/offline 上传行，仅保留 enterprise；文件名 `8.0.0` → `1.0.0.1` |
| `成都修茈科技有限公司/deploy/scripts/post-deploy-check.sh` | L72-75 EXE 路径从 `personal/XCAGI-Personal-Setup-8.0.0-x64.exe` 改为 `enterprise/XCAGI-Enterprise-Setup-1.0.0.1-x64.exe`（personal 已冻结）|
| `成都修茈科技有限公司/MODstore_deploy/scripts/deploy-market-download-fix.ps1` | L2-3 加注释（历史兼容；正式走 docker-compose build args）+ L14-15 版本号 `8.0.0` → `1.0.0.1` |
| `成都修茈科技有限公司/MODstore_deploy/docs/runbooks/xcagi-software-download.md` | L84 COS 检查示例 `xcagi-v8.1.0` → `xcagi-v1.0.0.1`（personal 标注已冻结）|

> COS_PREFIX 策略：默认值统一为 `xcagi-v1.0.0.1`，与 `VITE_XCAGI_DOWNLOAD_BASE_URL` 路径一致；运行时可通过环境变量覆盖。
> personal/offline SKU 冻结决策：见 `specs/product-lines-3-plus-2.md`，所有上传/校验脚本仅保留 enterprise。

---

## 8. config 残留（5 个文件）

version_sync 只改了 product_version/marketing_version 字段，以下字段需手动改：

| 文件 | 改动字段 |
|---|---|
| `FHD/config/release_train.json` | `current` → 1.0.0.1（epoch 保留 1.0.0.0）|
| `成都修茈科技有限公司/FHD/config/release_train.json` | 同上 |
| `FHD/config/download_release.json` | _doc/version_lock/download_version/android_version/artifacts 文件名/last_push.release_train（保留 release_history）|
| `FHD/config/time_rail_workflow_graph.json` | L280 desc 描述（"v10 锁恒 1.0.0.0" → "v10 当前 1.0.0.1"）|
| `FHD/release/VERSION` | 第二轮补漏：内容 `1.0.0.0` → `1.0.0.1`（version_sync 应覆盖但实际漏改）|

---

## 9. 文档（20 个文件，53 处）

| 文件 | 处数 |
|---|---|
| `README.md` | 2 |
| `docs/CI_SSOT.md` | 4 |
| `.trae/rules/cicd-e2e-prompt.md` | 7（L521 去掉"恒 1.0.0.0 不 bump"表述，改为"当前产品版本 1.0.0.1"）|
| `FHD/docs/DELIVERABLE_PRODUCT.md` | 6 |
| `FHD/docs/DEPLOYMENT.md` | 1 |
| `FHD/docs/START_HERE.md` | 2 |
| `FHD/docs/aiopen.md` | 1 |
| `FHD/docs/SSOT_INDEX.md` | 1 |
| `FHD/docs/ARCHITECTURE.md` | 2 |
| `FHD/docs/QUICK_START.md` | 2 |
| `FHD/docs/deploy/RELEASE_CHECKLIST.md` | 2 |
| `FHD/docs/guides/RELEASE_TWO_SKUS.md` | 9 |
| `FHD/docs/guides/INSTALLER_UI.md` | 3 |
| `FHD/docs/guides/快速启动说明.md` | 4 |
| `FHD/docs/guides/EXTERNAL_RELEASE_OFFLINE_REMOVAL.md` | 3 |
| `FHD/docs/guides/MOBILE_ANDROID_STORE_COMPLIANCE.md` | 1 |
| `FHD/docs/guides/ADCDFG_COMPLETION_PLAN.md` | 1 |
| `FHD/docs/runbooks/windows-code-signing.md` | 2 |
| `docs/architecture/ARCH-ENTERPRISE-MOD-EMPLOYEE.md` | 1 |
| `成都修茈科技有限公司/MODstore_deploy/BRANCHING.md` | 1 |
| `成都修茈科技有限公司/MODstore_deploy/docs/runbooks/xcagi-software-download.md` | 全量 |
| `成都修茈科技有限公司/MODstore_deploy/desktop-shell/README.md` | 1 |

> 跳过：CHANGELOG.md（历史发版记录）、MOD_AUTHORING_GUIDE.md（`>=1.0.0.0` 依赖示例）

---

## 9.5 dashboard / 可视化（第二轮补漏，3 个文件）

| 文件 | 改动 |
|---|---|
| `docs/xcagi-dashboard/time_rail_workflow_graph.json` | L280 desc：`v10 锁恒 1.0.0.0` → `v10 当前 1.0.0.1` |
| `docs/xcagi-dashboard/emp-wf-radial-graph.js` | L285 desc：同上 |
| `XCAGI-Full-Pipeline.html` | L967-968：`v10 锁恒 1.0.0.0` → `v10 当前 1.0.0.1`（L1075/L1776 的 "1.0.0.0 起" 是历史 epoch 起点描述，保留）|

> 这些文件残留了 workspace rule 已废弃的 "恒 1.0.0.0 不 bump" 表述，与版本 bump 决策矛盾。

---

## 10. 测试断言（11 个文件）

| 文件 | 改动 |
|---|---|
| `tests/test_application/test_admin_deploy_push.py` | L157/L163/L175 断言 |
| `tests/test_application/test_admin_deploy_push_deep2.py` | L84 断言 |
| `tests/test_application/test_admin_deploy_push_ext2.py` | L70/L82/L88 断言 |
| `tests/test_aiopen.py` | L50 断言 |
| `tests/test_application/test_aiopen_service.py` | L439 断言 |
| `tests/routes/test_xcmax_admin.py` | L137 mock + L142/L157/L166/L174 断言 |
| `tests/routes/test_xcmax_admin_session.py` | L103 mock + L108/L123/L132 断言 |
| `tests/test_infrastructure/test_mods_manifest_parse.py` | L298 注释 |
| `tests/release_gate/test_desktop_update_feed_policy.py` | L23/L28/L58/L167 fixture |
| `tests/release_gate/test_server_release_push_policy.py` | L34/L42/L111/L119 fixture |
| `tests/test_dev/test_generate_download_manifest_enterprise_only.py` | 15 处 fixture |

> 保留：`>=1.0.0.0` 依赖下限测试参数、`_derive_toolchain_version("1.0.0.0")` 函数测试参数、历史注释

---

## 11. MODstore 代码 / 官网子项目（第三轮全量细化，35 个文件）

### 11.1 Python 后端（5 个，第三轮精确化）
- `MODstore_deploy/modstore_server/app_config_api.py` — `_ANDROID_LATEST_NAME` 默认值
- `MODstore_deploy/modstore_server/download_release.py` — L4 docstring + L74-77 默认值 + L95/L99 兜底 `1.0.0.1`
- `MODstore_deploy/modstore_server/release_train.py` — L134/L220 `product_version` 默认值 `1.0.0.1`（保留内部 release_train current）
- `MODstore_deploy/modstore_server/release_train_api.py` — L7 docstring `1.0.0.1`
- `MODstore_deploy/modstore_server/xcmax_admin_api.py` / `time_rail_workflow.py` / `digest_vibe_prep.py` — 保留内部 release_train 值（按设计不改）

### 11.2 测试（6 个）
- `MODstore_deploy/tests/test_download_release.py` — L14-16 fixture + L36 manifest_url 断言
- `MODstore_deploy/tests/test_public_visualization_api.py` — L26-29/38 日志路径 + L44 version_lock + L156 stable_version
- `MODstore_deploy/tests/test_agent_butler_api.py` — L375 mock return_value（保留 `current: 1.0.0.0` 作为 epoch mock）
- `MODstore_deploy/tests/test_release_train.py` — 保留 `1.0.0.0` 作为 epoch/parse_quad 测试输入（设计保留）
- `MODstore_deploy/tests/test_dr_guard_auto_rollback.py` / `test_backup_pipeline.py` — 保留 `1.0.0.0` 作为测试初始状态（设计保留）
- `MODstore_deploy/tests/test_public_action_board.py` / `test_strategic_layer_digest_integration.py` / `test_digest_strategic_bridge.py` — 保留 `1.0.0.0` 作为 release_train 测试输入（设计保留）

### 11.3 配置/容器（4 个）
- `MODstore_deploy/docker-compose.yml` — L284-286 market 服务 build args 默认值（VITE_XCAGI_DOWNLOAD_VERSION/ANDROID_VERSION/DOWNLOAD_BASE_URL）
- `MODstore_deploy/market/Dockerfile` — L9-14 ARG + ENV 默认值
- `MODstore_deploy/.env.production.example` — L45-47 VITE_XCAGI_* 变量
- `MODstore_deploy/desktop-shell/electron-builder.config.cjs` — L35 artifactName + L36 publish URL（`XCAGI-${label}-Setup-1.0.0.1-${arch}.${ext}` + `xcagi-v1.0.0.1/${sku}/`）

### 11.4 desktop-shell（4 个，第三轮补登记）
- `MODstore_deploy/desktop-shell/main.js` — L3 注释「对外稳定产品版本 1.0.0.1；Electron package 使用工具链兼容版本 1.0.0」
- `MODstore_deploy/desktop-shell/preload.js` — L7 `version: '1.0.0.1'`（contextBridge 暴露给 Web 端）
- `MODstore_deploy/desktop-shell/package.json` — `version: 1.0.0`（toolchain，设计保留）
- `MODstore_deploy/desktop-shell/README.md` — L6「对外稳定产品版本为 1.0.0.1，Electron 工具链包版本为 1.0.0」

### 11.5 文档/分支规范（3 个，第三轮补登记）
- `MODstore_deploy/BRANCHING.md` — L3「对外稳定产品版本统一为 1.0.0.1」
- `MODstore_deploy/docs/runbooks/xcagi-software-download.md` — 全量更新：L5/L17-19/L27/L30/L42/L45/L48/L60 路径与版本号 + L84 COS 检查示例
- `MODstore_deploy/desktop-shell/README.md` — 见 11.4

### 11.6 前端源码（2 个）
- `MODstore_deploy/market/src/utils/xcagiDownloadLinks.ts` — L7-8 DEFAULT_XCAGI_DOWNLOAD_VERSION + DEFAULT_XCAGI_ANDROID_VERSION + L12 OFFICIAL_MANIFEST_URL
- `MODstore_deploy/market/src/utils/xcagiDownloadLinks.test.ts` — L23/L27/L34/L37/L44/L47/L95/L103/L112/L121/L124/L132/L143/L167/L181/L200/L229/L242 mock + 断言（保留 L51/L60/L63 `xcagi-v8.1.0` 作为版本参数化测试输入）

### 11.7 静态资源（1 个）
- `MODstore_deploy/market/public/download-release.json` — version_lock/download_version/android_version/release_root/manifest_url（保留 release_history 两条历史 epoch 1.0.0.0）

### 11.8 其他官网根目录（已含 1.0.0.1，仅核查登记）
- `成都修茈科技有限公司/release/VERSION` — 内容 `1.0.0.1`（第二轮已改）
- `成都修茈科技有限公司/package.json` — `version: 1.0.0`（toolchain，第二轮已改）
- `成都修茈科技有限公司/package-lock.json` — L2/L9 顶部 `1.0.0`（第二轮已改；L582/L668/L2825 是第三方依赖 concat-map 的版本号，保留）
- `成都修茈科技有限公司/MODstore_deploy/market/package.json` — `version: 1.0.0`（toolchain）
- `成都修茈科技有限公司/MODstore_deploy/desktop-shell/package.json` — `version: 1.0.0`（toolchain，见 11.4）
- `成都修茈科技有限公司/marketing-site/package.json` — `version: 1.0.0`（builder 工具链，独立子项目）

---

## 12. 校验结果

| 校验项 | 结果 |
|---|---|
| `python3 scripts/dev/verify_version_anchors.py` | ✅ OK: all anchors match product=1.0.0.1, toolchain=1.0.0 |
| `python3 scripts/dev/publish_ci_workflows_to_root.py` | ✅ 8 个漂移文件已写入根仓 |
| 后端测试（10 个受影响文件） | ✅ 478 passed, 0 failed |
| `test_mods_manifest_parse.py`（第二轮） | ✅ 42 passed, 0 failed |
| `ssot_cli.py gate`（第二轮） | ✅ mods: OK / version: OK（db-schema DRIFT 是预先存在的无关问题）|
| 第三轮官网/COS 全量扫描 | ✅ 成都修茈科技有限公司目录所有 1.0.0.0 引用归类完毕；所有 `xcagi-v8.0.0`/`xcagi-v8.1.0` 旧前缀默认值已更新为 `xcagi-v1.0.0.1`（保留测试参数化输入与历史 LEGACY location）|

---

## 13. 保留未改的 1.0.0.0（历史事实，不回写）

第三轮全量扫描后，剩余文件中的 `1.0.0.0` 全部属于以下合理保留类别：

### 13.1 epoch 历史起点（设计保留）
- `epoch: "1.0.0.0"` — release_train 历史起点（FHD/config/release_train.json、MODstore release_train.py、xcmax_admin.py 等）
- `reset_reason: "stable-1.0.0.0-ssot"` — 历史描述
- `1.0.0.0 起` — dashboard/HTML 中描述版本方案起点的文字（XCAGI-Full-Pipeline.html L1075/L1776）

### 13.2 release_history 历史条目
- `release_history` 数组里的 1.0.0.0 条目 — CHANGELOG / download-release.json（含 market/public 副本）/ corp-butler/download-release.json / download-releases.html 等历史发版记录
- `metrics/deploy_events.jsonl` — 历史部署日志
- `docs/evidence/**` — 历史证据快照（6 个文件）
- `config/release_train.json.bak-*` — 备份文件
- `specs/tasks.md` — 已完成任务历史记录

### 13.3 mod 依赖下限（按决策保留）
- `>=1.0.0.0` — 所有 mod manifest.json 的 dependencies.xcagi 依赖下限
- `PACKAGE_DECISION.md` / `MOD_AUTHORING_GUIDE.md` — 依赖示例
- `sync-enterprise-mod-seeds.sh` / `manifest.py` docstring — 依赖示例
- `test_coverage_ramp_phase2_p3_backend.py` — 依赖检查测试输入

### 13.4 测试固件（使用 1.0.0.0 作为测试输入/初始状态）
- MODstore 测试：test_release_train / test_dr_guard_auto_rollback / test_backup_pipeline / test_public_visualization_api（current mock）/ test_agent_butler_api（current mock）/ test_public_action_board / test_strategic_layer_digest_integration / test_digest_strategic_bridge / verify_release_train_local.sh
- FHD 测试：test_version_sync.py（`_derive_toolchain_version("1.0.0.0")` 函数输入）、test_xcmax_admin_ext3.py（epoch 断言）、test_android_deliverable_contract.py（历史 versionCode 注释）

### 13.5 nginx 旧版目录（向后兼容保留）
- `nginx-xiu-ci.conf` / `nginx-xiu-ci-root.conf` — `/xcagi-v1.0.0.0/` location 块保留，旧版仍可下载
- `deploy/nginx/snippets/xcagi-cos-alias.inc.conf` — `/xcagi-v8.0.0/` LEGACY location 块保留（第三轮新增 1.0.0.1 后保留旧版）

### 13.6 脚本文档/注释示例
- `version_sync.py` — docstring 用法示例 `--version 1.0.0.0`
- `ssot_plugins/deploy_scripts.py` — fallback 版本号注释示例
- `publish_ci_workflows_to_root.py` — workflow-dispatch choices 保护逻辑注释

### 13.7 测试参数化输入（第三轮新增归类）
- `MODstore_deploy/market/src/utils/xcagiDownloadLinks.test.ts` L51/L60/L63 — `xcagi-v8.1.0` 作为版本参数化测试输入（与默认值解耦，验证函数对任意版本字符串的处理能力）

### 13.8 备份/orig 文件
- `docs/xcagi-dashboard/_agentic-bos-rollback/XCAGI-Full-Pipeline.html.orig`

### 13.9 第三方依赖版本号（与本产品版本无关）
- `成都修茈科技有限公司/package-lock.json` L582/L668/L2825 — `concat-map` 依赖版本 `0.0.1`（npm 生态版本号，保留）
- `MODstore_deploy/desktop-shell/package-lock.json` L1361 — 同上

---

## 14. 发版前待办

1. **git commit**：改动量大，建议分组提交
   - SSOT + version_sync 自动同步
   - 代码 fallback
   - CI workflows
   - mod manifest
   - 文档
   - 测试断言
   - MODstore 代码
   - 第三轮：官网/COS 部署脚本（8 个）+ desktop-shell/BRANCHING/runbook 补登记
2. **uv lock**：更新 uv.lock 版本引用
3. **打 tag**：`git tag -a FHD/v1.0.0.1 -m "Release FHD v1.0.0.1"` → `git push origin FHD/v1.0.0.1`
4. **服务器侧**（CVM 119.27.178.147）：
   - `mkdir -p /var/www/xcagi-v1.0.0.1/`
   - 部署 nginx 新配置后 `nginx -t && nginx -s reload`
   - 同步 `deploy/nginx/snippets/xcagi-cos-alias.inc.conf` 到 CVM（`bash deploy/scripts/sync-nginx-xiu-ci-snippets.sh`）
   - 更新 CVM 上 `/root/.xcagi-cos.env` 中 `COS_PREFIX=xcagi-v1.0.0.1`（如使用 COS 上传）
5. **CI 全量验证**：push 后观察 `fhd-ci-cd.yml` 全量流水线通过

---

## 15. 关键决策记录

| 决策点 | 选择 | 理由 |
|---|---|---|
| 工具链版本映射 | 1.0.0.1 → 1.0.0（自动） | `_derive_toolchain_version` 取前三段 |
| mod manifest version | 跟产品 bump 到 1.0.0.1 | 与产品版本同步 |
| mod xcagi 依赖下限 | 保留 `>=1.0.0.0` | 兼容性下限不变 |
| CI workflow default | 改为 1.0.0.1 | 新版本成为默认输入 |
| nginx 路径 | 新建 1.0.0.1 目录，旧版保留 | 旧版本仍可下载 |
| workspace rule 策略 | 去掉"恒 1.0.0.0 不 bump" | 支持版本 bump，改为"当前产品版本" |
| COS_PREFIX 默认值（第三轮）| `xcagi-v8.0.0` → `xcagi-v1.0.0.1` | 与 `VITE_XCAGI_DOWNLOAD_BASE_URL` 路径一致 |
| cos-upload-progress.sh 文件名（第三轮）| 仅保留 enterprise，删除 personal/offline | personal SKU 已冻结（见 specs/product-lines-3-plus-2.md），offline 已废弃 |
| nginx snippet LEGACY 块（第三轮）| 保留 `/xcagi-v8.0.0/` location | 老书签/老链接仍可下载，向后兼容 |
