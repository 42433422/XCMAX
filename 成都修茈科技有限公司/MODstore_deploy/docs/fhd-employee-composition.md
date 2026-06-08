# FHD 里「员工」由什么组成（与 MODstore 生成物对照）

FHD（XCAGI 宿主）里和「员工」相关的概念有 **至少三套**，不要混用（很多人说的「软件里的 AI 员工」其实指的是 **C**，而 MODstore「做 Mod」主要产的是 **A**）：

| 形态 | 宿主位置 / artifact | 典型用途 |
|------|---------------------|----------|
| **A. Mod 内员工** | `artifact: mod`（默认），目录 `mods/<mod_id>/` | 业务 Mod 自带多名 AI 员工：`manifest.workflow_employees` + `backend/employees/*.py` + `blueprints` 路由等 |
| **B. 独立员工包** | `artifact: employee_pack`，目录 `mods/_employees/<pack_id>/` | 全局可安装的单包员工，manifest 顶层必须有 **`employee`** 对象 |
| **C. 工作流副窗「AI 员工」** | 无独立目录；开关在 **`localStorage` key `xcagi_workflow_ai_employees`**，与画布/聊天任务面板联动 | 宿主产品里的 **纵向一整条链**：**前端**（副窗/聊天/任务面板）+ **后端**（宿主 FastAPI、工作流、意图与业务 API）+ **执行侧**（本机打印、微信星标链路、电话 Win32/ADB 等）。不是单独一个 Mod zip 能替代的「员工包」形态 |

MODstore 工作台 **「生成员工脚本」**（`employee_impls`）对应的是 **A 的一小块**：只负责 **`backend/employees/<stem>.py`** 里的 **`async def run(payload, ctx)`**；**不会**自动生成 **C** 里那套副窗开关行为，也**不是** **B** 的 `employee_pack` 交付形态。

**MODstore 侧「员工包脚手架」按部门预设默认能力**（与 FHD A/B/C 概念独立）：见 [`employee-scaffold-presets.md`](./employee-scaffold-presets.md)。

---

## A. Mod 内员工（与 `import_mod_backend_py(..., "employees/<stem>")` 一致）

### 1. Manifest：`workflow_employees`

宿主编译进内存的类型见 `FHD/app/infrastructure/mods/manifest.py` → **`ModMetadata.workflow_employees`**：`list[dict[str, Any]]`，**额外字段会原样保留**（不仅限于下列键）。

常见约定（以仓库内 `mods/longxiang-ai-assistant/manifest.json` 为例）：

- **`id`**：员工逻辑 id（与 `backend/employees/` 下 stem 对齐）
- **`label` / `panel_title` / `panel_summary`**：工作台 / 前端的展示与说明
- **`api_base_path`**（可选但真实 Mod 常用）：蓝图里 FastAPI 路由前缀，例如 `employees/system_config_agent`，与 `POST .../run` 等路径一致

画布侧还会常见 **`workflow_id` / `workflowId`** 等（由 MODstore 编排后续步骤写入），用于把名片挂到具体工作流。

### 2. 可执行代码：`backend/employees/<stem>.py`

- 由宿主 **`app.mod_sdk.mods_bus.import_mod_backend_py(mod_path, mod_id, f"employees/{stem}")`** 加载（见 `FHD/app/infrastructure/mods/mod_manager.py`：`stem` 可含子路径，实际文件为 **`backend/employees/<stem>.py`**）。
- 参考实现：`FHD/mods/smoke-emp-mod-a7086bb8/backend/blueprints.py` 中 **`_load_employee_module`** 与 **`EMPLOYEES`** 表对 `id` / `stem` 的映射。
- 约定入口：**`async def run(payload: dict, ctx: dict) -> dict`**（与 MODstore 生成提示词一致）。

### 3. 路由与调度：`backend/blueprints.py`（或其它 `backend.entry`）

- 注册 **`/employees/{employee_id}/run`**（及可选 status/start/stop）等，内部 **`import_mod_backend_py`** 再 **`await mod.run(...)`**。
- 与 **`workflow_employees[*].api_base_path`** 或路由表一致，前端 / 网关才知道打哪条 URL。

### 4. 可选：`manifest.comms.exports`

龙象示例把员工作为 **`comms.exports`** 列表里的 **`xxx.run`** 符号导出，供 Mod 间总线调用；这是 **Manifest 层契约**，不是 `.py` 文件自动替你补全的（需蓝图或人工维护）。

### 5. 可选：配置与行业

如 **`config/ai_blueprint.json`**、**`industry`**、**`config/industry_card.json`** 等，描述行业与 AI 面板行为；与「员工」是 **同一 Mod 的不同层**，不是单文件能替代的。

---

## B. 独立 `employee_pack`（全局员工包）

校验逻辑见 `FHD/app/infrastructure/mods/artifact_package.py` → **`validate_employee_pack_manifest`**：

- **`artifact`** 须为 **`employee_pack`**
- 顶层须有 **`employee` 对象**（`dict`），且 **`employee.id`** 非空
- **`scope`**：`global` 或 `host`（当前安装器主要支持 **`global`**）
- 安装路径：**`mods/_employees/<pack_id>/`**（`FHD/app/infrastructure/mods/employee_registry.py`）

`/api/mods/` 列表会把已安装 **employee_pack** 合并成与 Mod 类似的行（`type: employee_pack`，`workflow_employees` 由单个 `employee` 折成一项），见 **`ModManager.list_mods`**。

**这与「做 Mod」里生成的 `backend/employees/*.py` 不是同一种交付物**：要做 **employee_pack**，需要单独的打包与 `artifact: employee_pack` 的 manifest（MODstore 另有「做员工」等路径，与本文「Mod 内脚本」不同）。

---

## C. 工作流副窗「AI 员工」（宿主聊天 / 任务面板语境）

这是 **FHD 产品语义**下的「AI 员工」：**不是**仅指某个 `backend/employees/*.py`，而是 **前端 + 后端 + 执行环境** 在宿主里已经接好的一条业务链（你所说的「完整前后端和执行软件」主要指这一层）。

### C 在工程上大致包含哪几段

| 层次 | 做什么 | 典型落点（FHD 仓库内） |
|------|--------|-------------------------|
| **前端** | 副窗开关、与聊天页任务面板同步、自定义事件派发 | `TopAssistantFloat.vue`、`useChatView.ts`（监听 `xcagi:workflow-*`、`xcagi:workflow-ai-employees-changed`）、`workflowAiEmployees.ts`、`WorkflowEmployeeSpaceBridge.vue` 等 |
| **后端** | 意图识别、工作流节点、出货/打印/对话等业务 API、Mod 挂载的 `phone-agent` 等 HTTP 入口 | 宿主 `app` 下各路由与工作流引擎；Mod 侧 `blueprints` 与 **`/api/mod/{id}/...`** |
| **执行软件 / 本机能力** | 打印机、微信侧星标与轮询、来电监控、ADB 真机等 | 产品文档 `workflow-employee-docs.json` 里对各分支的描述（如「POST phone-agent/start → Win32 来电监控」）；依赖用户环境是否安装/授权 |

**内置四类**（`defaultWorkflowBuiltinEnabled`）：`label_print`、`shipment_mgmt`、`receipt_confirm`、`wechat_msg`——打开开关即参与星标/意图/任务面板等链路（见 `workflow-employee-docs.json`）。

**固定扩展行**（如 `wechat_phone`、`real_phone`）：由各 Mod 在 **`manifest.workflow_employees`** 里 **声明 id**，副窗再合并出开关行（`workflowAiEmployees.ts` 注释：勿在前端硬编码这两类）。

**动态行**：来自已加载 Mod 的 **`workflow_employees[].id`**，与内置 key 去重后出现在副窗（`mergeModWorkflowIds`）。

因此：**光有 `backend/employees/*.py` 和名片级 `workflow_employees`，并不等于宿主侧「副窗里那套 AI 员工」已按产品语义接好**——还需要 **manifest 条目 id 与宿主约定 id 对齐**、**电话类 `phone_agent_*` 等路径**、以及 **宿主前后端与执行环境** 对该 id 的完整接线。若你期望的是「和龙象 / sz-qsm-pro 一样在副窗能开关、能跑完整链路」，要对齐的是 **C 整条纵向链 + A 里 manifest/路由**，而不仅是 `employee_impls` 生成的 `.py`。

---

## 和 MODstore「生成员工脚本」差在哪里

| FHD 侧组成 | MODstore `employee_impls` 是否覆盖 |
|------------|-------------------------------------|
| `backend/employees/<stem>.py` 的 `run` | ✅ 主目标 |
| `manifest.workflow_employees` 名片字段 | ❌ 主要在蓝图 + **repo** 阶段写入；脚本步只消费已有 `employees` 列表 |
| `api_base_path`、与 `blueprints` 路由完全一致 | ⚠️ 依赖蓝图 LLM + **`render_suite_blueprints_py`** 等；不保证与龙象级手工 Mod 同粒度 |
| `comms.exports`、行业/蓝图 JSON | ❌ 不在 `employee_impls` 单步 |
| **employee_pack** zip + `_employees/` 安装 | ❌ 不是该步骤产物 |
| 副窗六类 / 动态工作流 AI 员工（**C**） | ❌ 不在 `employee_impls`；依赖宿主前端 + manifest `id` 与宿主业务链路 |

若你期望的是 **「和龙象一样：manifest 条目 + api_base_path + comms + 蓝图一致的一整套」**，或 **「和宿主副窗 AI 员工一样能开关、走固定/扩展链路」**，需要在产品层把需求拆到：**蓝图提示词**、**blueprints 模板**、**workflow_employees 与宿主约定 id 对齐**、**编排后人工在 Mod 制作页补齐** 或 **单独做 employee_pack 流水线**，而不是只加强「生成员工脚本」这一小段。

---

## 源码索引（FHD）

| 内容 | 路径 |
|------|------|
| Mod manifest 与 `workflow_employees` | `FHD/app/infrastructure/mods/manifest.py` |
| `employee_pack` 校验 | `FHD/app/infrastructure/mods/artifact_package.py` |
| `_employees` 安装与列表 | `FHD/app/infrastructure/mods/employee_registry.py` |
| `import_mod_backend_py` | `FHD/app/infrastructure/mods/mod_manager.py` |
| SDK 重导出 | `FHD/app/mod_sdk/mods_bus.py` |
| 迷你 Mod：加载员工 + 路由 | `FHD/mods/smoke-emp-mod-a7086bb8/backend/blueprints.py` |
| 真实多员工 manifest 示例 | `FHD/mods/longxiang-ai-assistant/manifest.json` |
| 副窗 AI 员工开关与 manifest 合并 | `FHD/frontend/src/stores/workflowAiEmployees.ts` |
| manifest 员工条目与电话路径等（TS 侧约定） | `FHD/frontend/src/utils/modWorkflowEmployees.ts` |
| 副窗六类说明（产品文案与过程） | `FHD/frontend/src/data/workflow-employee-docs.json` |

---

---

## 9. MODstore 扩展字段与 FHD 读字段对照（employee_pack）

| Manifest 字段 | 写入方（MODstore） | FHD 消费位置 |
|----------------|-------------------|--------------|
| `artifact: employee_pack` / `employee` / `scope` | 既有 | `validate_employee_pack_manifest`、安装器 |
| `xcagi_host_profile` | LLM 可选 + `xcagi_host_profile.normalize` | `validate_xcagi_host_profile_extensions`；`employee_registry.list_for_mods_api` 合并 `workflow_employee_row` 到副窗行 |
| `workflow_employees` | 生成单条（`api_base_path` 等） | `/api/mods/` 合并列表；副窗 `hydrateFromMods` |
| `backend.entry` = `blueprints` | 固定 | `load_employee_pack_routes` → `register_fastapi_routes` |
| `employee_config_v2` | LLM 或默认 | 员工 `run()` 内读 manifest；`GET /api/mods/employee-packs/{id}/config-preview` |

联调步骤见 **`docs/workbench-employee-fullstack-e2e.md`**。

---

*可与 `docs/workbench-employee-impl-flow.md`、`docs/workbench-make-mod-workflow.md` 交叉阅读。*
