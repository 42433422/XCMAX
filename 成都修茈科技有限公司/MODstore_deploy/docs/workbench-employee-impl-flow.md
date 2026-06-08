# 工作台「生成员工脚本」流程说明

本文说明 **MODstore 工作台「做 Mod」** 编排中步骤 **`employee_impls`**（界面约 **「生成员工脚本」**）的输入、输出与实现路径，便于排查耗时、失败与兜底行为。

---

## 1. 在整条编排中的位置

「做 Mod」且 **`generate_full_suite: true`**（默认）时，服务端顺序大致为：

1. `manifest`：生成蓝图 JSON  
2. `repo`：`import_mod_suite_repository` 落盘 Mod（含 manifest 中的 `workflow_employees` 名片）  
3. `industry`：行业卡片与 UI shell  
4. **`employees`**：进度上标记「创建员工骨架」——**仅瞬时更新步骤状态**；骨架数据已在 **repo** 阶段写入  
5. **`employee_impls`**：**本文描述的核心流程**  
6. `workflows`：为每名员工建画布工作流并生成图  
7. `register_packs` / `api` / 沙箱 / `complete` …

---

## 2. 入口与产物

| 项目 | 说明 |
|------|------|
| 调用方 | `modstore_server/workbench_api.py` 中 `intent == "mod"` 分支 |
| 实现函数 | `modstore_server/mod_employee_impl_scaffold.py` → `generate_mod_employee_impls_async` |
| 产物目录 | `{mod_dir}/backend/employees/` |
| 单文件命名 | `<stem>.py`，`stem = sanitize_employee_stem(员工 id)`（与宿主加载规则一致） |
| 首次初始化 | 若不存在则写入 `backend/employees/__init__.py` 占位说明 |

运行时由脚手架中的 **`render_suite_blueprints_py`** 等与宿主 **`app.mod_sdk.mods_bus.import_mod_backend_py`** 按模块加载；员工约定实现 **`async def run(payload, ctx) -> Dict[str, Any]`**。

---

## 3. 单名员工处理流程（顺序、一名接一名）

对 `employees` 列表中每一项 **`dict` 且含非空 `id`**：

1. **状态回调**（若传入 `status_hook`）  
   更新编排步骤文案，例如：`第 n/N 名员工「…」：请求模型生成实现代码…`

2. **凭证与模型**  
   使用蓝图阶段相同的 `provider` / `model`，经 `resolve_api_key`、`resolve_base_url`（OpenAI 兼容类厂商）判断是否可调上游。

3. **分支 A：具备 provider + model + api_key**  
   - 调用 **`_generate_one_employee_py`**：  
     - 用 **`_employee_brief_lines`** 拼装 user 消息：Mod id/名称/brief、行业卡、员工 label / panel_summary / capabilities / workflow 描述等。  
     - **`chat_dispatch`**：系统提示（`SYSTEM_PROMPT_EMPLOYEE_IMPL`）要求输出**完整单文件** Python，遵守 FHD `app.mod_sdk` 导入边界、`ctx["call_llm"]` 等约定。  
     - **`py_compile`** 校验生成内容；失败则第二次 **`chat_dispatch`**（`SYSTEM_PROMPT_EMPLOYEE_IMPL_REPAIR`）做语法修复。  
   - 若最终仍无合法源码：记录错误信息，进入分支 B。

4. **分支 B：无密钥或 LLM 失败**  
   - 使用 **`_fallback_employee_py`** 写入**最小可编译**实现：以 `ctx["call_llm"]` 为主的兜底逻辑，并标注为 fallback。  
   - 兜底且存在说明时，该条记入返回值的 **`errors`** 列表（同时也在 **`generated`** 中带 `fallback` / `note`）。

5. **落盘**  
   `target.write_text(source, encoding="utf-8")`。

6. **返回值条目**  
   `generated` 中记录 `employee_id`、`stem`、`path`、`fallback` 等；需要展示的失败说明进 **`errors`**。

**注意**：`employees` 里若为 `dict` 但 **`id` 为空**，该条会被 **跳过**（不写文件、不计入上述「第 n 名」进度中的有效生成数）；与 `create_mod_suite_workflows_async` 的遍历规则可能不完全一致，若蓝图员工缺 `id` 需在模型侧或后处理对齐。

---

## 4. 耗时与超时（体感「卡住」时先看这里）

- 每名员工最多 **2 次** LLM 调用（生成 + 可选修复）。  
- `chat_dispatch` 对 OpenAI 兼容接口默认单次 HTTP 超时约 **120s**（见 `llm_chat_proxy.py`）。  
- **顺序执行**：员工数 × 单次最坏耗时，总时间会线性拉长；界面应能看到「第 n/N 名员工」类 **message** 更新。

无可用密钥时走兜底，通常 **很快**，不会长时间停在「生成员工脚本」。

---

## 5. 编排结束后的数据去向

- 步骤 **`employee_impls`** 置为 **done**，摘要写入 `steps[].message`。  
- **`impl_result`**（`generated` / `errors`）进入会话 **`artifact`**，并写入蓝图扩展字段（如 `employee_impl_result`），供 Mod 制作页与审计使用。

---

## 6. 相关源码索引

| 内容 | 路径 |
|------|------|
| 编排调用与异常收口（若已合并） | `modstore_server/workbench_api.py` |
| 生成逻辑、提示词、兜底模板 | `modstore_server/mod_employee_impl_scaffold.py` |
| LLM 统一出口与超时 | `modstore_server/llm_chat_proxy.py` → `chat_dispatch` |
| 整条「做 Mod」步骤表 | `docs/workbench-make-mod-workflow.md` |

---

*文档版本：与当前仓库 `generate_mod_employee_impls_async` 行为对齐；若提示词或步骤 id 变更，请同步更新本文。*
