# R22 外部标杆实测：Agent 编排域开源锚点（LangGraph）同任务集实测记录

> 标准版本：`external-anchors-v1`（`FHD/config/audit_benchmark_ssot.json`）。
> 本文是**单域单锚点的实测审计记录**，不是 18 域正式评分。

## 审计记录字段

| 字段 | 值 |
|---|---|
| standard_version | 1.0.0 |
| scoring_version | external-anchors-v1 |
| source_sha / main_sha | 见提交历史（feat/audit-roadmap-r01-r22） |
| reference_versions_editions_regions | LangGraph OSS 1.2.11（PyPI 稳定版，MIT），本地 venv（python3.11），SqliteSaver 检查点 |
| dataset_hash | 任务脚本随本文档存档（同目录 agent-langgraph-tasks-20260909.py） |
| task_protocol | B1 状态持久化+暂停恢复；B2 人工审批绑定实际动作；B3 重试/恢复不重复副作用 |
| predeclared_metrics_and_tolerances | 状态值精确匹配；审批拒绝=零副作用、批准=一次副作用；重试收敛后 effects 计数=1 |
| environment | 本机 macOS venv，SQLite 检查点文件 |
| observed_results | B1/B2/B3 全部 PASS（见下表） |
| unknowns | 商业锚点（Copilot Studio / Agentforce / Maestro）未实测；多 worker 分布式场景未覆盖（本记录为单进程检查点语义） |
| domain_status | agent-orchestration 域开源 60 分锚点：B1/B2/B3 实测通过（E2/E3：真实库、完整任务、故障恢复） |
| score | 不授予（单锚点记录） |
| auditor | agent-mac-trae |
| observed_at | 2026-09-09（Asia/Shanghai） |

## 逐任务结果

| 任务 | 对应锚点 | 结果 | 关键证据 |
|---|---|---|---|
| B1 状态持久化+恢复 | agent-orchestration-B1 | PASS | 两步图执行后关闭连接、重开新 SqliteSaver 按 thread_id 完整恢复 `{trace:[a,b], value:11}` |
| B2 审批绑定动作 | agent-orchestration-B2 | PASS | `interrupt()` 在执行前挂起；拒绝→executed=False；批准→executed=True（副作用严格绑定审批决定） |
| B3 重试不重复副作用 | agent-orchestration-B3 | PASS | 前两次抛错、第三次成功；effects 计数=1、attempts=3（恢复收敛且无重复执行） |

## 与 XCMAX 侧对照

XCMAX 同域验收见 R11（Agent 审批/暂停恢复/重复执行防护：并发 CAS 竞态证明 SQLite+PG 双栈，172 项全绿）。
本记录证明 LangGraph 开源基线在同等必选语义（持久化恢复、审批绑定、幂等重试）上行为一致，
XCMAX 的编排契约不低于该开源锚点；不据此宣称达到商业产品水平（90 分锚点未实测）。
