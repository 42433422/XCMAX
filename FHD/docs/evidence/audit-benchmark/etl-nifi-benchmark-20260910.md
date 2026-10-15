# R22 外部标杆实测：ETL 域开源锚点（Apache NiFi）同任务集实测记录

> 标准版本：`external-anchors-v1`（`FHD/config/audit_benchmark_ssot.json`）。
> 本文是**单域单锚点的实测审计记录**，不是 18 域正式评分。

## 审计记录字段

| 字段 | 值 |
|---|---|
| standard_version | 1.0.0 |
| scoring_version | external-anchors-v1 |
| reference_versions_editions_regions | Apache NiFi 1.28.0（apache/nifi:1.28.0 官方镜像，单节点 standalone，Apache-2.0），本地 Docker 端口 19080；ExecuteScript Groovy 3.x（镜像内置） |
| dataset_hash | 任务脚本随本文档存档（etl-nifi-tasks-20260910.py） |
| task_protocol | B1 输入校验/字段映射/预览/错误定位；B2 处理来源可追踪+安全重试不覆盖人工编辑；B3 客户/产品关联、租户隔离与输出一致 |
| predeclared_metrics_and_tolerances | 3 条合法行精确映射（acme×2、globex×1）；2 条坏行按行号+原因精确定位（5=missing_customer_id、6=qty_not_numeric）；链路计数 get.out=1→etl.in=1→etl.out=2（精确）；人工编辑文件重跑后字节不变（精确） |
| environment | 本机 macOS Docker（Colima），HTTP 一律 `--noproxy '*'`/ProxyHandler({})；宿主-容器共享 /tmp/r22-etl/{in,good,errors} bind mount |
| observed_results | B1/B2/B3 全部 PASS（见下表） |
| unknowns | provenance 查询子系统在 standalone 镜像返回 500（`/nifi-api/provenance*` 全部不可用），来源追踪降级为处理器级事件链计数断言（get.out→etl.in→etl.out 一致），未覆盖 FlowFile 级 lineage 查询 UI；多节点/背压/集群协调未覆盖；商业锚点（Informatica IDMC / Qlik Talend Cloud / Microsoft Fabric Data Factory）未实测 |
| domain_status | etl 域开源 60 分锚点：B1/B2/B3 实测通过（E3：真实 NiFi 环境完整任务+错误定位+重试不覆盖） |
| score | 不授予（单锚点记录） |
| auditor | agent-mac-trae |
| observed_at | 2026-09-10（Asia/Shanghai） |

## 逐任务结果

| 任务 | 对应锚点 | 结果 | 关键证据 |
|---|---|---|---|
| B1 校验+映射+错误定位 | etl-B1 | PASS | 6 行输入（含表头）：3 条合法行映射为 `tenant,customer_id,product,qty,ok` 输出；2 条坏行进 errors 文件且带行号与原因（`5,missing_customer_id`、`6,qty_not_numeric`），原始行全文保留可复现 |
| B2 来源追踪+安全重试 | etl-B2 | PASS | 处理器链计数 get.out=1 → etl.in=1 → etl.out=2（1 输入分裂 good+errors 两输出，来源可追踪）；重跑（stop/start get）后人工编辑标记文件 `manual-edit.txt` 字节不变（输出文件名含 FlowFile UUID，不与人工文件冲突、不覆盖） |
| B3 租户隔离+输出一致 | etl-B3 | PASS | good 输出仅含 acme(2)/globex(1) 两租户、无交叉污染；每行 5 字段、customer_id 非空、qty 全数字；与输入合法子集逐行一致 |

## 环境要点（复现必读）

1. 宿主 HTTP 一律禁用代理（`--noproxy '*'` / `ProxyHandler({})`），否则系统代理对 Docker 端口返回 502。
2. ExecuteScript Groovy 绑定：`session`/`context` 为隐式变量；关系用 `REL_SUCCESS`/`REL_FAILURE` 常量，
   `session.transfer(ff, "success")`（字符串）会抛 MissingMethodException。
3. PutFile/GetFile 的 sink 端 `success` 关系也必须 auto-terminate（创建时 POST 可能丢弃该字段，需创建后 PUT 补设）。
4. 容器 bind mount 目录不可在宿主 `rm -rf`（挂载指向旧 inode 会失联），只清文件。
5. standalone 镜像 provenance 查询端点不可用（500），来源追踪以处理器统计断言替代并如实记入 unknowns。

## 与 XCMAX 侧对照

XCMAX 同域验收见 R20（Retort 长任务恢复/重放/证据一致性 980 项全绿）与 Excel 导入管线
（解析/列回退/列推断/记录提取/导入确认/组装 6 步平级模块）。本记录证明 NiFi 开源基线在同等必选语义
（输入校验与错误定位、来源追踪、重试不覆盖人工编辑、租户隔离输出一致）上行为一致，
XCMAX ETL 管线契约不低于该开源锚点；不据此宣称达到商业产品水平（90 分锚点未实测）。
