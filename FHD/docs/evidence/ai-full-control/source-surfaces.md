# AI 全功能入口对账：源码候选清单

本次扫描 4023 个受版本控制的 FHD 源文件，解析错误 0 个。

这些是源码声明数量，包含主机/Mod 副本及尚未确认挂载的代码，不能相加为独立功能总数，也不证明当前账号有权调用。全部条目保留源码文件与行号，详见同目录 source-surfaces.json。

| 类型 | 源码数量 | 验收状态 |
| --- | ---: | --- |
| API 声明 | 1714 | 待逐项对账 |
| 前端路由声明 | 116 | 待逐项对账 |
| Vue 事件绑定 | 2046 | 待逐项对账 |
| 文件输入候选 | 33 | 待逐项对账 |
| Mod 清单副本 | 103 | 待逐项对账 |

API 中 865 项存在动态路径或无法静态解析的挂载前缀，必须结合实际运行路由核验。注册清单中的 192 个动作不包含这些未核验声明的完整分母。

## 已定位的文件选择入口

通用页面输入执行器 useAiOpenCursor.ts 当前明确排除 input[type=file]。下列入口需逐项核对已有专用导入工具，补充用户附件到界面文件控件的身份绑定、执行与结果回读。表内保留发布副本，不能据此宣称存在同样数量的独立缺失功能。

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

- native desktop/mobile commands
- external Modstore and admin applications
- first-party package entrypoints
- dynamic route mounts and downloaded Mods
- controls generated at runtime
- account and deployment availability

## 可复核性

- 源码集合 SHA-256：`7d58db6846384cd4ce5a1bdff949c4e5d301c83a8b455285dc96d8c162a29726`
- 扫描器 SHA-256：`ceb39219815ed03f5f049188b128f7d7d2d781cae8657c677a0c35c1413af843`
- 扫描器使用 Python AST、TypeScript AST 与 Vue 模板解析器，保留动态声明的不确定性；没有运行用户业务或执行接口写入。
- 8 项解析器回归通过，覆盖多方法 API、注解路由器、动态前缀、同名局部变量、注释、原生文件输入及测试文件排除。
