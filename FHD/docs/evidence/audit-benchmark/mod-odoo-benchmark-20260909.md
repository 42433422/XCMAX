# R22 外部标杆实测：Mod SDK 域开源锚点（Odoo 18 Community）同任务集实测记录

> 标准版本：`external-anchors-v1`（`FHD/config/audit_benchmark_ssot.json`）。
> 本文是**单域单锚点的实测审计记录**，不是 18 域正式评分。

## 审计记录字段

| 字段 | 值 |
|---|---|
| standard_version | 1.0.0 |
| scoring_version | external-anchors-v1 |
| reference_versions_editions_regions | Odoo 18.0 Community（odoo:18 官方镜像 18.0-20260908，LGPL-3.0），本地 Docker（postgres:16 配套） |
| dataset_hash | 任务脚本随本文档存档（同目录 mod-odoo-tasks） |
| task_protocol | B1 模块清单/依赖/生命周期/卸载边界；B2 共享宿主账号数据隔离；B3 升级保留配置+运行版本可查 |
| predeclared_metrics_and_tolerances | 安装/卸载状态精确转移；跨公司 search=0 且直读 AccessError；升级后配置值精确保留 |
| environment | 本机 macOS Docker，单库 r22，odoo shell 执行 |
| observed_results | B1/B2/B3 全部 PASS（见下表） |
| unknowns | 商业锚点（Salesforce Platform / Atlassian Forge / Shopify Apps）未实测；模块签名/分发回执链（XCMAX 必选）不在 Odoo 能力范围，另由 R13 验收覆盖 |
| domain_status | mod-sdk 域开源 60 分锚点：B1/B2/B3 实测通过（E3：真实软件环境完整任务） |
| score | 不授予（单锚点记录） |
| auditor | agent-mac-trae |
| observed_at | 2026-09-09（Asia/Shanghai） |

## 逐任务结果

| 任务 | 对应锚点 | 结果 | 关键证据 |
|---|---|---|---|
| B1 生命周期+依赖边界 | mod-sdk-B1 | PASS | calendar 安装→installed、卸载→uninstalled 状态机精确；manifest 依赖 `[base, mail]` 声明可查 |
| B2 账号数据隔离 | mod-sdk-B2 | PASS | 仅授权 Co B 的用户跨公司 search=0、直读抛 AccessError（company_id 记录规则） |
| B3 升级保留配置 | mod-sdk-B3 | PASS | survey 升级后 `r22.module_setting=keep-me` 保留；`installed_version=18.0.3.7` 可查 |

## 环境修复记录（如实留痕）

Odoo 18 镜像无 `note` 模块（改用 calendar/survey）；已卸载模块（removed 态）拒绝重装属 Odoo 设计；
`res.users` 组字段为 `groups_id`（非 group_ids）。

## 与 XCMAX 侧对照

XCMAX 同域验收见 R13（Mod 授权加载/升级/撤销/账户隔离：253 项全绿）。本记录证明 Odoo Community 开源基线
在同等必选语义（生命周期状态机、账号隔离、升级保配置）上行为一致，XCMAX Mod SDK 契约不低于该开源锚点；
不据此宣称达到商业产品水平（90 分锚点未实测）。
