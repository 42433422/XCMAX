# AI 全功能入口对账：源码候选清单

本次扫描 4070 个受版本控制的 FHD 源文件，解析错误 0 个。

这些是源码声明数量，包含主机/Mod 副本及尚未确认挂载的代码，不能相加为独立功能总数，也不证明当前账号有权调用。全部条目保留源码文件与行号，详见同目录 source-surfaces.json。

| 类型 | 源码数量 | 验收状态 |
| --- | ---: | --- |
| API 声明 | 1711 | 待逐项对账 |
| 前端路由声明 | 116 | 待逐项对账 |
| Vue 事件绑定 | 2051 | 待逐项对账 |
| 文件输入候选 | 33 | 待逐项对账 |
| Mod 清单副本 | 103 | 待逐项对账 |
| Electron IPC 注册或调用声明 | 56 | 待运行时及 AI 执行验收 |
| preload 暴露对象 | 1 | 待逐成员验收 |

API 中 865 项存在动态路径或无法静态解析的挂载前缀，必须结合实际运行路由核验。注册清单中的 194 个动作不包含这些未核验声明的完整分母。

## 已定位的文件选择入口

已新增 software.files / software.set_files 通用文件选择链路，但不等于全部入口业务验收通过。下列入口需逐项核对已有专用导入工具，补充用户附件到界面文件控件的身份绑定、执行与结果回读。表内保留发布副本，不能据此宣称存在同样数量的独立缺失功能。

| 源码位置 | 控件判定 |
| --- | --- |
| `XCAGI/mods/attendance-industry/frontend/views/HomeView.vue:23` | native_file_input |
| `XCAGI/mods/taiyangniao-pro/frontend/views/HomeView.vue:25` | native_file_input |
| `XCAGI/mods/xcagi-erp-domain-bridge/frontend/views/CustomersView.vue:45` | native_file_input |
| `XCAGI/mods/xcagi-erp-domain-bridge/frontend/views/LabelEditorView.vue:11` | native_file_input |
| `XCAGI/mods/xcagi-erp-domain-bridge/frontend/views/ProductsView.vue:10` | native_file_input |
| `XCAGI/mods/xcagi-erp-domain-bridge/frontend/views/TemplatePreviewView.vue:31` | native_file_input |
| `XCAGI/mods/xcagi-erp-domain-bridge/frontend/views/traditional-mode/TmToolbar.vue:29` | native_file_input |
| `XCAGI/mods/xcagi-office-employee-pack-bridge/frontend/views/ToolsView.vue:108` | dynamic_input_type |
| `XCAGI/mods/xcagi-planner-bridge/frontend/views/ChatView.vue:166` | native_file_input |
| `frontend/src/components/FileImport.vue:30` | native_file_input |
| `frontend/src/components/InputDialog.vue:10` | dynamic_input_type |
| `frontend/src/components/chat/ChatInputToolbar.vue:67` | native_file_input |
| `frontend/src/components/etl/ShipmentEtlDockingCenter.vue:21` | native_file_input |
| `frontend/src/components/kitten/KittenAnalyzerView.vue:166` | native_file_input |
| `frontend/src/components/persy/PersyImportDrawer.vue:50` | native_file_input |
| `frontend/src/components/shell/LegacyFloatPanels.vue:47` | native_file_input |
| `frontend/src/components/template/FileUploadStep.vue:25` | native_file_input |
| `frontend/src/views/AdminEntitlementsView.vue:50` | dynamic_input_type |
| `frontend/src/views/ChatView.vue:182` | native_file_input |
| `frontend/src/views/LoginView.vue:189` | dynamic_input_type |
| `frontend/src/views/ProductsView.vue:10` | native_file_input |
| `frontend/src/views/ProductsView.vue:132` | dynamic_input_type |
| `frontend/src/views/RegisterView.vue:201` | dynamic_input_type |
| `frontend/src/views/RegisterView.vue:221` | dynamic_input_type |
| `frontend/src/views/SettingsView.vue:19` | native_file_input |
| `mods/taiyangniao-pro/frontend/views/HomeView.vue:25` | native_file_input |
| `mods/xcagi-erp-domain-bridge/frontend/views/CustomersView.vue:45` | native_file_input |
| `mods/xcagi-erp-domain-bridge/frontend/views/LabelEditorView.vue:11` | native_file_input |
| `mods/xcagi-erp-domain-bridge/frontend/views/ProductsView.vue:10` | native_file_input |
| `mods/xcagi-erp-domain-bridge/frontend/views/TemplatePreviewView.vue:31` | native_file_input |
| `mods/xcagi-erp-domain-bridge/frontend/views/traditional-mode/TmToolbar.vue:29` | native_file_input |
| `mods/xcagi-office-employee-pack-bridge/frontend/views/ToolsView.vue:108` | dynamic_input_type |
| `mods/xcagi-planner-bridge/frontend/views/ChatView.vue:166` | native_file_input |

## 仍需补齐的分母

- native IPC runtime registration and execution; mobile commands
- external Modstore and admin applications
- first-party package entrypoints
- dynamic route mounts and downloaded Mods
- controls generated at runtime
- account and deployment availability

## 可复核性

- 源码集合 SHA-256：`807f66cc70bc1ba0b76f55de948f539fb593f7831c712be54edd65065567e9d1`
- 扫描器 SHA-256：`ceb39219815ed03f5f049188b128f7d7d2d781cae8657c677a0c35c1413af843`
- 扫描器使用 Python AST、TypeScript AST 与 Vue 模板解析器，保留动态声明的不确定性；没有运行用户业务或执行接口写入。
- 8 项解析器回归通过，覆盖多方法 API、注解路由器、动态前缀、同名局部变量、注释、原生文件输入及测试文件排除。

## 桌面原生入口对账

基于 TypeScript AST 识别 electron 命名导入及命名空间导入（包含别名），忽略注释与同名非 Electron 对象。CommonJS require、变量转发和运行时生成注册尚未覆盖；每项运行时状态及 AI 执行状态均为 unverified。不能将注册和调用相加为独立功能数。

| 通道 | 主进程注册位置 | 渲染端声明位置 |
| --- | --- | --- |
| `xcagi:capture-screenshot` | `desktop/ipc-handlers.ts:194` (handle) | `desktop/preload.ts:32` (invoke) |
| `xcagi:check-for-updates` | `desktop/ipc-handlers.ts:82` (handle) | `desktop/preload.ts:9` (invoke) |
| `xcagi:clipboard-read-text` | `desktop/ipc-handlers.ts:148` (handle) | `desktop/preload.ts:23` (invoke) |
| `xcagi:clipboard-write-text` | `desktop/ipc-handlers.ts:149` (handle) | `desktop/preload.ts:24` (invoke) |
| `xcagi:consume-bootstrap-session-hint` | `desktop/ipc-handlers.ts:69` (handle) | `desktop/preload.ts:7` (invoke) |
| `xcagi:consume-deep-link` | `desktop/ipc-handlers.ts:168` (handle) | `desktop/preload.ts:28` (invoke) |
| `xcagi:consume-release-notes` | `desktop/ipc-handlers.ts:191` (handle) | `desktop/preload.ts:31` (invoke) |
| `xcagi:deep-link` | 本扫描未发现 | `desktop/preload.ts:35` (on) |
| `xcagi:download-update` | `desktop/ipc-handlers.ts:84` (handle) | `desktop/preload.ts:11` (invoke) |
| `xcagi:export-support-bundle` | `desktop/ipc-handlers.ts:81` (handle) | `desktop/preload.ts:8` (invoke) |
| `xcagi:get-app-identity` | `desktop/ipc-handlers.ts:74` (handle) | 本扫描未发现 |
| `xcagi:get-auto-launch` | `desktop/ipc-handlers.ts:162` (handle) | `desktop/preload.ts:26` (invoke) |
| `xcagi:get-data-dir` | `desktop/ipc-handlers.ts:68` (handle) | `desktop/preload.ts:6` (invoke) |
| `xcagi:get-update-status` | `desktop/ipc-handlers.ts:83` (handle) | `desktop/preload.ts:10` (invoke) |
| `xcagi:install-update` | `desktop/ipc-handlers.ts:88` (handle) | `desktop/preload.ts:12` (invoke) |
| `xcagi:offline-query` | `desktop/ipc-handlers.ts:126` (handle) | `desktop/preload.ts:18` (invoke) |
| `xcagi:open-kellai-desktop` | `desktop/ipc-handlers.ts:80` (handle) | `desktop/preload.ts:14` (invoke) |
| `xcagi:open-path` | `desktop/ipc-handlers.ts:154` (handle) | `desktop/preload.ts:25` (invoke) |
| `xcagi:pairing-qr` | `desktop/ipc-handlers.ts:45` (handle) | `desktop/preload.ts:13` (invoke) |
| `xcagi:report-error` | `desktop/ipc-handlers.ts:175` (handle) | `desktop/preload.ts:30` (invoke)<br>`desktop/preload.ts:59` (invoke) |
| `xcagi:screenshot-captured` | 本扫描未发现 | `desktop/preload.ts:41` (on) |
| `xcagi:secure-delete` | `desktop/ipc-handlers.ts:144` (handle) | `desktop/preload.ts:21` (invoke) |
| `xcagi:secure-get` | `desktop/ipc-handlers.ts:140` (handle) | `desktop/preload.ts:19` (invoke) |
| `xcagi:secure-list` | `desktop/ipc-handlers.ts:145` (handle) | `desktop/preload.ts:22` (invoke) |
| `xcagi:secure-set` | `desktop/ipc-handlers.ts:141` (handle) | `desktop/preload.ts:20` (invoke) |
| `xcagi:set-auto-launch` | `desktop/ipc-handlers.ts:163` (handle) | `desktop/preload.ts:27` (invoke) |
| `xcagi:set-badge` | `desktop/ipc-handlers.ts:93` (handle) | `desktop/preload.ts:15` (invoke) |
| `xcagi:show-notification` | `desktop/ipc-handlers.ts:104` (handle) | `desktop/preload.ts:17` (invoke) |
| `xcagi:update-event` | 本扫描未发现 | `desktop/preload.ts:51` (on) |
| `xcagi:voice-invoke` | 本扫描未发现 | `desktop/preload.ts:46` (on) |

preload 对象 `xcagiDesktop` 的静态成员：platform, versions, getDataDir, consumeBootstrapSessionHint, exportSupportBundle, checkForUpdates, getUpdateStatus, downloadUpdate, installUpdate, getPairingQrPayload, openKellaiDesktop, setBadge, showNotification, offlineQuery, secureGet, secureSet, secureDelete, secureList, clipboardReadText, clipboardWriteText, openPath, getAutoLaunch, setAutoLaunch, consumeDeepLink, reportError, consumeReleaseNotes, captureScreenshot, onDeepLink, onScreenshotCaptured, onVoiceInvoke, onUpdateEvent。成员中包括属性和事件订阅，不等于全部是可执行动作。
