# R22 外部标杆实测：事件内核域开源锚点（Apache Kafka）同任务集实测记录

> 标准版本：`external-anchors-v1`（`FHD/config/audit_benchmark_ssot.json`）。
> 本文是**单域单锚点的实测审计记录**，不是 18 域正式评分。

## 审计记录字段

| 字段 | 值 |
|---|---|
| standard_version | 1.0.0 |
| scoring_version | external-anchors-v1 |
| reference_versions_editions_regions | Apache Kafka 3.8.1（apache/kafka:3.8.1 官方镜像，KRaft 单节点，Apache-2.0），本地 Docker；客户端 confluent-kafka 2.15.0（librdkafka） |
| dataset_hash | 任务脚本随本文档存档（同目录 agent-langgraph-tasks / erp-erpnext-tasks） |
| task_protocol | B1 事件契约/顺序/投递语义；B2 重复投递/消费失败/死信；B3 进程重启恢复+丢失/延迟观测 |
| predeclared_metrics_and_tolerances | 50 条全量按序（精确）；未提交位移重放=原 offset 序列（精确）；重启续读追平 LEO（committed>=LEO） |
| environment | 本机 macOS Docker，单分区主题，幂等 producer |
| observed_results | B1/B2/B3 全部 PASS（见下表） |
| unknowns | 多 broker/网络分区/副本故障切换未覆盖（单节点）；商业锚点（Confluent Cloud / Solace / EventBridge）未实测 |
| domain_status | event-kernel 域开源 60 分锚点：B1/B2/B3 实测通过（E3：真实 Kafka 环境完整任务+故障恢复） |
| score | 不授予（单锚点记录） |
| auditor | agent-mac-trae |
| observed_at | 2026-09-09（Asia/Shanghai） |

## 逐任务结果

| 任务 | 对应锚点 | 结果 | 关键证据 |
|---|---|---|---|
| B1 投递语义与顺序 | event-kernel-B1 | PASS | 幂等 producer 50 条全部按序送达（header seq 单调、offset 递增） |
| B2 重复/失败/死信 | event-kernel-B2 | PASS | 手动提交模式下不提交位移→重启后原 offset 序列重放（重复投递可观测）；毒消息路由 `.dlq` 主题成功 |
| B3 重启恢复+观测 | event-kernel-B3 | PASS | 消费 10 条后关闭（模拟崩溃），同 group 新实例从提交位移续读 20 条追平 LEO=30，committed=30 零丢失 |

## 与 XCMAX 侧对照

XCMAX 同域验收见 R12（Neuro Bus 事件总线：真实 Redis Streams 多进程投递/持久化/恢复/DLQ 4/4 实测通过，
含重启 BUSYGROUP 修复）。本记录证明 Kafka 开源基线在同等必选语义（顺序投递、重放/死信、重启续读）
上行为一致，XCMAX 事件内核契约不低于该开源锚点；不据此宣称达到商业产品水平（90 分锚点未实测）。
