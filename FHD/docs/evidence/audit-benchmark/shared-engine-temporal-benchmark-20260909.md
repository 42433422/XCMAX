# R22 外部标杆实测：共享引擎域开源锚点（Temporal OSS）同任务集实测记录

> 标准版本：`external-anchors-v1`（`FHD/config/audit_benchmark_ssot.json`）。
> 本文是**单域单锚点的实测审计记录**，不是 18 域正式评分。

## 审计记录字段

| 字段 | 值 |
|---|---|
| standard_version | 1.0.0 |
| scoring_version | external-anchors-v1 |
| reference_versions_editions_regions | Temporal OSS（temporalio Python SDK 1.32.0，MIT；WorkflowEnvironment.start_local 内置 dev server + SQLite 持久化），本地 macOS |
| dataset_hash | 任务脚本随本文档存档（同目录 r22_defs + tasks） |
| task_protocol | B1 执行协议/状态持久化/插件接口；B2 重放+重试不虚报完成/不重做副作用；B3 执行证据与输入/产物哈希绑定 |
| predeclared_metrics_and_tolerances | 结果精确匹配；重试收敛后 attempts=3 且副作用计数=1；重放无 NondeterminismError；输入参数从历史精确还原 |
| environment | 本机 macOS（代理已清空避免 localhost 劫持），SDK 内嵌 dev server |
| observed_results | B1/B2/B3 全部 PASS（见下表） |
| unknowns | 跨 worker 分布式、版本升级历史兼容、长期运行（Temporal Cloud 级）未覆盖；商业锚点（Temporal Cloud / Camunda / Step Functions）未实测 |
| domain_status | shared-engine 域开源 60 分锚点：B1/B2/B3 实测通过（E2/E3：真实引擎、完整任务+重放） |
| score | 不授予（单锚点记录） |
| auditor | agent-mac-trae |
| observed_at | 2026-09-09（Asia/Shanghai） |

## 逐任务结果

| 任务 | 对应锚点 | 结果 | 关键证据 |
|---|---|---|---|
| B1 执行协议+持久化+插件接口 | shared-engine-B1 | PASS | 三步 activity 编排结果 `[a\|X,b\|X,c\|X]`；23 条 event history 持久化；query 可观测中间态 |
| B2 重放/重试不重做副作用 | shared-engine-B2 | PASS | flaky activity 第 3 次成功、attempts=3、side_effects 计数=1（不虚报完成、不重做）；历史重放 `replay_failure=None`（确定性通过） |
| B3 证据与输入/产物哈希绑定 | shared-engine-B3 | PASS | history 序列化 sha256=`82b6b1b3…`；输入参数 `[21]` 从 event history 精确还原 |

## 与 XCMAX 侧对照

XCMAX 同域验收见 R20（Retort 长任务恢复/重放/证据一致性：980 项全绿）。本记录证明 Temporal 开源基线在同等必选语义
（状态持久化、重放确定性、重试幂等、证据哈希绑定）上行为一致，XCMAX Retort 引擎契约不低于该开源锚点；
不据此宣称达到商业产品水平（90 分锚点未实测）。

## 环境修复记录（如实留痕）

本机 Clash 代理会劫持 localhost gRPC 连接致 dev server 卡死，实测须清空 `*_PROXY` 并设 `NO_PROXY='*'`；
SDK 沙箱要求 workflow/activity 定义在可重导入模块（非 `__main__`）；`execute_activity` 多参须用 `args=[...]`；
`RetryPolicy` 位于 `temporalio.common`；重放结果读 `replay_failure` 而非 `result()`。
