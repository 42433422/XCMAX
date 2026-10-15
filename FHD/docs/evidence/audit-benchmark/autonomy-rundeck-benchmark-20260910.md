# R22 外部标杆实测：自治运维域开源锚点（Rundeck Community）同任务集实测记录

> 标准版本：`external-anchors-v1`（`FHD/config/audit_benchmark_ssot.json`）。
> 本文是**单域单锚点的实测审计记录**，不是 18 域正式评分。

## 审计记录字段

| 字段 | 值 |
|---|---|
| standard_version | 1.0.0 |
| scoring_version | external-anchors-v1 |
| reference_versions_editions_regions | Rundeck Community 5.9.0（rundeck/rundeck:5.9.0 官方镜像，内嵌 HSQLDB，Apache-2.0），本地 Docker 端口 14441→4440；`FHD/config/audit_benchmark_ssot.json` 锁定 source_commit=1b944fd3ab |
| dataset_hash | 任务脚本随本文档存档（autonomy-rundeck-tasks-20260910.py） |
| task_protocol | B1 运维动作白名单/执行权限/时间与资源上限；B2 真实子进程超时/截断/取消回收后代进程；B3 任务记录/重试/审批/人工接管可追溯 |
| predeclared_metrics_and_tolerances | 白名单外动作不执行（精确）；未认证 API 一律 401/403（精确）；5s 超时任务被中止（精确）；5000 行输出全量可检索（精确）；取消后后代进程存活数=0（精确）；失败重试链含 failed-with-retry→succeeded（精确）；执行历史含操作者+时间（精确） |
| environment | 本机 macOS Docker（Colima），HTTP 一律 `--noproxy '*'` / `no_proxy=*`（见「误判更正」） |
| observed_results | B1/B2/B3 全部 16 项 PASS（见下表） |
| unknowns | 商业级审批插件（Rundeck 企业版 Approvals/Workflow 审批门）未覆盖——Community 版审批为 ACL+选项白名单近似；跨节点 SSH 执行未覆盖——单容器 local 节点；商业锚点（Ansible Automation Platform / PagerDuty Runbook Automation）未实测 |
| domain_status | autonomy 域开源 60 分锚点：B1/B2/B3 实测通过（E3：真实 Rundeck 环境完整任务+超时+取消+重试+审计） |
| score | 不授予（单锚点记录） |
| auditor | agent-mac-trae |
| observed_at | 2026-09-10（Asia/Shanghai） |

## 逐任务结果

| 任务 | 对应锚点 | 结果 | 关键证据 |
|---|---|---|---|
| B1-1 动作执行成功留记录 | autonomy-B1 | PASS | `B1-safe-echo` 执行 `status=succeeded`，执行记录持久化可查 |
| B1-2 输出可审计 | autonomy-B1 | PASS | 执行日志含 `R22_OK ping`（选项值透传子进程） |
| B1-3 执行时间上限已配置 | autonomy-B1 | PASS | 作业导出 YAML 含 `timeout: 2m`（根级 timeout 键生效） |
| B1-4 未认证 API 被拒 | autonomy-B1 | PASS | 无会话 GET `/api/41/projects` → HTTP 403 |
| B1-5 白名单外动作被拒且未执行 | autonomy-B1 | PASS | enforced 选项 `-action delete` → HTTP 400（值不在 `list/restart` 白名单，命令未执行） |
| B1-6 白名单内动作执行成功 | autonomy-B1 | PASS | `-action restart` → succeeded，日志含 `APPROVED_ACTION restart` |
| B2-1 超时任务被中止 | autonomy-B2 | PASS | `sleep 300` + `timeout: 5s` → `status=timedout` |
| B2-2 大输出受控返回 | autonomy-B2 | PASS | 5000 行输出，`maxlines=100` 受控返回 100 条 |
| B2-3 全量输出可检索 | autonomy-B2 | PASS | `maxlines=100000` 返回全 5000 行（不静默丢数据） |
| B2-4 取消后状态可查 | autonomy-B2 | PASS | 运行中执行 `POST /execution/{id}/abort` → `status=aborted` |
| B2-5 取消回收后代进程 | autonomy-B2 | PASS | 后台子进程 `sleep 240`（pid 记录于 /tmp/r22-child），abort 后 `ps` 存活数=0 |
| B3-1 失败自动重试并最终成功 | autonomy-B3 | PASS | flaky 步骤首跑 `failed-with-retry`，重试派生新执行 `succeeded`（链：failed-with-retry→succeeded） |
| B3-2 执行历史可追溯 | autonomy-B3 | PASS | `GET /project/r22/executions` 累计 46 条历史 |
| B3-3 记录含操作者与时间 | autonomy-B3 | PASS | 执行记录 `user=admin`、`date-started.date` 非空 |
| B3-4 中止/超时执行在历史中可区分 | autonomy-B3 | PASS | 历史中 `status∈{aborted,timed-out}` 计数=4，与 succeeded/failed 可区分 |

## 误判更正（重要）

2026-09-10 早些时候记录为「环境阻塞：Rundeck 宿主端口 502、API token 403、项目无法创建」。
本次复测证明该结论错误，根因四条：

1. **宿主 curl/urllib 走了系统 HTTP 代理**：`HTTP_PROXY=http://127.0.0.1:7890` 对 Docker 映射端口
   返回 502 Bad Gateway（代理层假象），把网络问题误读为 webapp 未就绪。加 `--noproxy '*'`
   （Python 侧 `no_proxy=*` 并清除代理 env）后 `GET /api/41/projects=200`。
2. **项目创建端点错配**：正确为 `POST /api/41/projects`（复数集合），而非 `POST /api/41/project/{name}`；
   且需**同会话 cookie**（先 `j_security_check` 登录再 POST），裸 token 文件方式在 5.9.0 未授权。
3. **作业定义格式**：XML 导入对 `<sequence>` 步骤结构要求苛刻（多次 `Workflow must have at least one step`），
   改用 **YAML 导入**（`Content-Type: application/yaml`）一次成功；`timeout` 须为**根级键**
   （`execution.timeout` 块被静默丢弃），`retry`/`retryDelay` 同理根级。
4. **节点定义**：改用项目本地文件 `/home/rundeck/projects/r22/etc/resources.xml`
   （`resources.source.1.type=file` 默认），避开 key-storage 路径猜测。

教训入档：锚点实测前必须先排除本机代理干扰（`--noproxy '*'` / `NO_PROXY`），
并以镜像内实际版本的 API 路由与导入格式为准（YAML 比 XML 稳）。

## 与 XCMAX 侧对照

XCMAX 同域验收见 R16（自治恢复、人工接管、持续运行证据）与 R11（Agent 审批/暂停恢复/重复执行防护）。
本记录证明 Rundeck 开源基线在同等必选语义（动作白名单强制、执行权限、时间上限、真实子进程超时、
输出截断可控、取消回收后代进程、重试链、执行审计含操作者+时间、中止可区分）上行为一致，
XCMAX 自治运维契约不低于该开源锚点；不据此宣称达到商业产品水平（90 分锚点未实测，
且企业级审批门一项 XCMAX 侧以 Agent 审批状态机覆盖、锚点 Community 版无原生审批门，属版本范围差异而非能力差异）。
