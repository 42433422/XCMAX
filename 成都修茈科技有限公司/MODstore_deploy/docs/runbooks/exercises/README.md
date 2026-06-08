# 演练记录索引

本目录登记每一次桌面推演（tabletop）与技术演练（dry-run / 预发 confirm）。
目的是把 [`docs/sre-operating-model.md`](../../sre-operating-model.md)、[`incident-response.md`](../incident-response.md)、[`chaos-game-day.md`](../chaos-game-day.md)、[`disaster-recovery.md`](../disaster-recovery.md) 中的流程从「写过」变成「跑过且有日志」。

## 当前条目

| 日期 | 条目 | 类型 | 环境 |
| --- | --- | --- | --- |
| 2026-05-04 | [chaos & DR 多场景 dry-run + SEV2 桌面推演](2026-05-04/EXERCISE.md) | 桌面 + dry-run | 本机（Windows + Docker Desktop） |

## 新增条目模板

每次演练新建 `docs/runbooks/exercises/<YYYY-MM-DD>/EXERCISE.md`，至少覆盖：

- 时间、环境、参与人；
- 演练范围（场景列表）；
- 时间线（按 [`incident-response.md`](../incident-response.md) 「沟通模板」与 [`chaos-game-day.md`](../chaos-game-day.md) 「复盘模板」结构）；
- 与 RPO / RTO 假设的差异；
- 改进项 + 负责人 + 截止时间；
- 原始日志（同目录，`*.log`）。

未做 `--confirm` 的部分务必在标题与正文中写明 **dry-run / tabletop**，避免读者误以为是真实事故或预发 confirm 演练。
