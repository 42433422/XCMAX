# 「做员工」类 C 全链路联调清单（MODstore + FHD）

本文对应已实现能力：**employee_pack** 含 `manifest.workflow_employees`、`backend/blueprints.py` + `backend/employees/<stem>.py`、`employee_config_v2`、可选 `xcagi_host_profile`；工作台可选 **pack_plus_workflow** 与 **FHD 根 URL 探测**。

---

## 1. MODstore 侧

1. 二档「做员工」→ 完成需求规划 → 制作草稿。
2. 在草稿中选择 **员工包模式**：
   - **仅员工包**：不创建画布工作流；`workflow` / `workflow_sandbox` 步骤为 **skipped**。
   - **员工包 + 画布工作流**：编排中调用 NL 生图并写回 `manifest.workflow_employees[0].workflow_id`。
3. 可选填写 **FHD 根 URL**（如 `http://127.0.0.1:8000`），或使用环境变量 `FHD_BASE_URL`；编排末尾对 `GET {base}/api/mods/` 做连通性探测（HTTP 失败不阻断成功，写入 `artifact.host_probe`；未配置则 **skipped**）。
4. **登记员工包** 仅写入本地包目录并规范化 manifest，**不会自动上架 Catalog**；成功后请到「员工制作」手动上架。
5. 成功后检查 `artifact.pack_id`、`artifact.workflow_attachment`（pack_plus 时）、`artifact.host_probe`、`artifact.quality_report`。

---

## 2. 13 步编排预期终态

| 步骤 id | 典型终态 | 说明 |
|---------|----------|------|
| spec | done | 结构化需求写入 session |
| employee_plan | done | 一站式规划 brief |
| generate | done / error | Word 提取走 AI scaffold，非 Excel 资产模式 |
| validate | done / error | 独立 manifest/Python 校验 |
| script_workflow | done / skipped / error | 非资产模式且开启 embed 时尝试生成 |
| embed_script | done / skipped | 无 script_wf 时 skipped 并说明原因 |
| workflow | done / skipped | pack_only → skipped |
| register_pack | done / error | 本地保存；失败即 error |
| workflow_sandbox | done / skipped | pack_only → skipped |
| mod_sandbox | done / error | vibe 门禁失败 → error |
| standalone_smoke | done / skipped / error | validate 失败 → error |
| host_check | done / skipped | 未配置 URL → skipped |
| complete | done | 含 quality_report |

前端进度条将 **done + skipped + error** 均计为终态（如 13/13）。

---

## 3. FHD 侧

1. 将生成的 zip 安装到 `mods/_employees/<pack_id>/`（与既有安装器一致）。
2. **重启或触发**宿主加载路由：`load_mod_routes` 会调用 `load_employee_pack_routes`，为带 `backend.entry` 的包挂载 `/api/mod/<pack_id>/employees/...`。
3. 调用 **`GET /api/mods/employee-packs/{pack_id}/config-preview`** 确认 `employee_config_v2` 摘要可读。
4. 调用 **`POST /api/mod/<pack_id>/employees/<employee_id>/run`**（body 任意 JSON）验证 `run` 与宿主 `mod_employee_complete` 注入。
5. 打开宿主前端 **/api/mods/** 列表：应出现 `type: employee_pack`，且 `workflow_employees` 首条含副窗所需 `id` / `label`；若 manifest 含 `xcagi_host_profile.workflow_employee_row`，字段会合并进该行。

---

## 4. 已知边界

- **内置四类轨道**（`label_print` 等）的完整业务链仍依赖宿主已实现逻辑；`xcagi_host_profile.builtin_track_id` 仅做契约与白名单校验。
- 宿主 **get_mod_detail** 仍只解析已注册 Mod；员工包详情以 `config-preview` 与磁盘 manifest 为准。
- 编排 **不会** 调用 `append_package` 自动上架；质量报告中的「员工包登记」指本地目录写入成功。

---

*与 [fhd-employee-composition.md](fhd-employee-composition.md)、[workbench-employee-impl-flow.md](workbench-employee-impl-flow.md) 交叉阅读。*

## 值班编制 ↔ 桌面主控

- 编制矩阵：`FHD/config/duty_roster.json`（与 MODstore `duty_roster.py` CI 对齐）
- 桌面主控：`FHD` → `/xcmax-admin` → 值班总览 / 任务下达（代理 MODstore duty-graph）
- 官网观测：`/admin/duty-employees`（可 deep link `xcagi://ops/duty` 回桌面）
- 闭环文档：[`FHD/docs/guides/OPS_CLOSURE.md`](../../../FHD/docs/guides/OPS_CLOSURE.md)
