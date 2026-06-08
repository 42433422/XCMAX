# 员工上架向导（工作台）与沙盒说明

面向维护者与高级用户：说明「员工创作 / 上架」页内三步向导，以及 MODstore 工作流沙盒与仓库内 **xcagi-mod-sandbox**（`docker/mod-sandbox`）的关系。

## 向导三步

| 步骤 | 界面区块 | 行为概要 |
|------|----------|----------|
| 1. 创建（compose） | 名称、描述、包文件等 | 仅本地表单与选文件；主按钮进入下一步，**不会**调用上架接口。 |
| 2. 测试与审核（testing） | 沙盒门槛、五维审核 | 通过门槛后才可拉取五维评分；**仍非最终上架**。 |
| 3. 上架信息（listing） | 行业、价格等 | 用户确认后由 `handleSubmit` 等逻辑提交目录/上架。 |

前端实现见 `market/src/views/EmployeeAuthoringView.vue`（`publishWizardStep`: `compose` → `testing` → `listing`）。

## 一键登记 vs 向导（本地 `/v1/packages`）

当目标只是把 **Mod manifest 里某条 `workflow_employees`** 落成可列在本地包目录的 **`employee_pack`**（与「导出员工包」同结构的最小 zip），而不改行业/价格、不做沙盒向导里的逐步确认时：

- 在 **Mod 源码库**（`RepositoryView`）或 **Mod 制作页**员工表旁，使用 **「一键登记」**：前端调用 `POST /api/mods/{mod_id}/register-workflow-employee-catalog`（Bearer 用户 JWT）。服务端生成 zip、跑与上架相同的沙盒审核，通过后直接 **`append_package`** 写入 Catalog，**不需要** `MODSTORE_CATALOG_UPLOAD_TOKEN`。
- **仍建议走完整向导** 若你需要：自定义包 `id`/版本策略、改价、强依赖「工作流沙盒」门槛、或员工 **依赖 Mod 内 Python 电话路由**（最小 zip 不含这些 `.py`，须用员工制作页的「导出完整 Mod」等路径）。

同一条声明再次一键登记时，若生成的 **`id` + `version`** 与已有记录相同，会 **覆盖** 该条 Catalog 记录。

## 「沙盒」的两种含义

### A. MODstore 工作流沙盒（服务端）

当包的关联 JSON 中含有效 **`workflow_id`** 时，页面提供「运行沙盒测试」，请求：

- `POST /api/workflow/{workflow_id}/sandbox-run`

由 `modstore_server` 的 `workflow_engine.run_workflow_sandbox` 做图校验与沙盒执行。这是 **应用内工作流**，与下述 Docker 镜像无自动耦合。

### B. 本地 xcagi-mod-sandbox 镜像（可选）

当 **没有** 有效 `workflow_id` 时，UI 会提示：建议在本地用 Docker 镜像 **`xcagi-mod-sandbox`** 对 Mod 做加载与路由冒烟，说明指向仓库根下的：

- `docker/mod-sandbox/README.md`

构建与运行方式以该 README 为准（仓库根执行 `build.ps1` / `build.sh`，`docker run` 挂载 mods 目录、`/health` 等）。**须由开发者在本地自行执行**；点击向导「下一步」不会启动容器或打开新标签页。

无 `workflow_id` 时，通过沙盒门槛依赖用户勾选「我已完成本地 / Docker 沙箱冒烟（或本包无需宿主 Mod 路由验证）」（诚实确认项）。

## 旧版声明（仅有 panel_summary 等、无 workflow_id）

`panel_summary` 等字段描述的是 **XCAGI 工作流员工面板文案**，不是 MODstore 里可执行工作流图的 ID。修复/补全方式：

1. 在工作台创建或打开工作流，记下 **数字 ID**，写入对应 `workflow_employees` 条目的 **`workflow_id`**（或 `workflowId`），并「保存到 manifest」。
2. 打开员工制作页时在 URL 增加 **`?link_workflow_id=<数字>`**（一次生效后会从地址栏移除），编辑器 JSON 会自动补上 `workflow_id`（若当前仍为空）。
3. 若 manifest 已在 **其它** `workflow_employees` 条目或 **`modstore.workflow_id` / `modstore_workflow_id`** 上声明了 **唯一** 的工作流 ID，页面加载关联 Mod 时会 **推断** 沙盒用 ID，并尽量 **合并进当前条目的 JSON**（便于你点保存写回）。
4. 上传的 zip 若 `manifest.json` 内可同样推断出唯一 ID，仅上传包（未关联 Mod）时也会用于「运行沙盒测试」。

## 电话类员工与 MODstore 工作流图测试

宿主侧「微信电话」等能力在 `workflow_employees` 里用 `panel_summary`、`phone_agent_base_path` 等声明；**可执行分支与 Mock 回放**依赖 MODstore 里单独维护的 **工作流图**（节点/边），并通过条目上的 **`workflow_id`（数字）** 关联。

推荐路径：

1. 在工作台 **工作流管理** 中创建/编辑图，保存到服务端。
2. 在 **Mod 制作页** 员工表「MODstore 图」列：对尚无 `workflow_id` 的行，下拉选择工作流后点 **「写入关联」**（调用 `POST /api/mods/{id}/workflow-link` 且带 `workflow_index`，合并进现有条目，不追加重复行）。也可在 JSON 里手写 `workflow_id` 后保存 manifest。
3. 在 **员工制作页** 或 **Mod 制作页（员工表）** 点击 **「拆解与沙盒测试」**，会打开 `工作流` 页并带上 `?edit=<id>&tab=sandbox`：直接进 **沙盒实验室**，可查看 **图结构摘要**、复制 **Mermaid**、选用 **运行变量预设** 后执行「仅校验图」或「沙盒运行」。
4. 五维审核里对电话路由的 HTTP 探测仍见 `package_sandbox_audit`；与上图沙盒互补，互不替代。

## 与首页「上架员工」入口的区别

首页 `HomeView` 上的「上架员工」可能打开上传/引导模态，与上述工作台内向导为不同入口；本说明仅针对 **工作台员工创作页** 内的三步流程。
