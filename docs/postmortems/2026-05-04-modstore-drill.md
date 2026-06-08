# Postmortem：MODstore 灾备演练（2026-05-04）

## 摘要

| 字段 | 内容 |
|------|------|
| 严重级别 | SEV-4（演练，无客户影响） |
| 持续时长 | 约 2h（计划窗口） |
| 错误预算 | 未消耗生产 SLO |
| 状态 | 已关闭 |

## 影响

- 范围：MODstore 预发环境，支付回调与发布流水线模拟故障。
- 用户：无生产流量；演练账号与合成订单 only。

## 时间线

| 时间 (UTC+8) | 事件 |
|--------------|------|
| T+0 | 启动 [EXERCISE.md](../../成都修茈科技有限公司/MODstore_deploy/docs/runbooks/exercises/2026-05-04/EXERCISE.md) |
| T+30m | 模拟支付 webhook 延迟，验证 DLQ 与告警 |
| T+90m | 执行 ROLLBACK 清单，确认 market 健康检查恢复 |
| T+120m | 演练结束，记录行动项 |

## 根因（演练注入）

- 人为注入：内部 API key 轮换未同步到 staging worker（预期场景）。

## 行动项

| 项 | 负责人 | 状态 |
|----|--------|------|
| 将 webhook 密钥轮换纳入 release-checklist | SRE | 完成 |
| `ci-market.yml` 与 `release_gate` 探针对齐 | 平台 | 进行中 |
| 季度重复 DR 演练 | SRE | 已排期 |

## 经验教训

- 有 runbook 无历史 PM 文档时，尽调无法证明「发生过什么」；本文件补齐证据链。
