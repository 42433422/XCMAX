# 2026-05-04 chaos & DR dry-run + SEV2 桌面推演

> 类型：tabletop（桌面推演）+ dry-run（chaos_drill / restore_postgres 不带 `--confirm`）。
> 这不是预发 `--confirm` 演练，也不是真实生产事故。本记录的目的：把 [`sre-operating-model.md`](../../../sre-operating-model.md)、[`incident-response.md`](../../incident-response.md)、[`chaos-game-day.md`](../../chaos-game-day.md)、[`disaster-recovery.md`](../../disaster-recovery.md) 跑成可见的执行轨迹。

## 元数据

| 项 | 值 |
| --- | --- |
| 日期 | 2026-05-04 |
| 时区 | UTC+08:00 |
| 环境 | 本机 Windows 10 + Docker Desktop（仅 `xcagi-postgres` 容器在跑，没有完整 MODstore 栈） |
| MODstore_deploy Git（短） | `70fd951` |
| 参与人 | 单人独立操作（演练记录不要求人数，只要求可复现） |
| 范围 | 1 次 SEV2 桌面推演 + 4 个 chaos 场景 dry-run + PostgreSQL restore dry-run |

## 1. SEV2 桌面推演：支付代理 502 飙升

**触发条件**（假想）：Grafana `MODstore Overview` 上 `modstore_payment_proxy_requests_total{status="502"}` 在 2 分钟内从 0 飙到 30/min；同时 `payment-service /actuator/health` 返回 `DOWN`。

按 [`docs/sre-operating-model.md`](../../../sre-operating-model.md) 第 40–55 行 SEV 分级与事故流程模板填写：

| 字段 | 内容 |
| --- | --- |
| 事故等级 | SEV2（核心链路部分失败：支付代理大面积 502，登录与市场仍可用） |
| 开始时间 | T0（演练用） |
| 影响范围 | 支付下单、续费、退款；钱包余额查询不受影响 |
| 当前状态 | 502 持续，未恢复 |
| Incident Commander | 演练人 A |
| 修复执行人 | 演练人 B（与 A 可同人） |
| 沟通节奏 | 每 10 分钟在群里同步状态，直到归零 |

**5 步流程模拟**：

| 步骤 | 模板动作 | 本次推演填写 |
| --- | --- | --- |
| 1. 确认影响 | Grafana / Prometheus / 冒烟脚本 / 用户反馈 | `python scripts/sre_smoke_check.py --base-url http://127.0.0.1:8765 --payment-url http://127.0.0.1:8080 ...`；查 Grafana 5xx panel；尝试 `/api/payment/plans` |
| 2. 指派负责人 | 1 IC + 1 修复人 | A = IC，B = 修复（演练人本人兼任） |
| 3. 止血优先 | 回滚 / 限流 / 关闭高风险入口 / 切回 Java 后端 | 优先按 [`PAYMENT_GRAY_RELEASE.md`](../../../PAYMENT_GRAY_RELEASE.md) 的「回滚到 Python 支付」段执行；如未启用灰度则 `docker compose --profile app restart payment-service` |
| 4. 恢复验证 | 冒烟 + 手工验证 + 告警归零 | `sre_smoke_check`、手工 `POST /api/payment/orders` 用 sandbox 账号、Grafana firing alerts 归 0 |
| 5. 复盘 | 24h 内出时间线 / 根因 / 改进项 | 按 [`incident-response.md`](../../incident-response.md) 「复盘模板」生成单独文件 |

**推演中发现的流程缺口**（即「写过没跑过」会暴露的点）：

- `incident-response.md` 「沟通模板」缺一个**升级条件**字段（什么时候 SEV2 升 SEV1），需要补。
- `sre-operating-model.md` 没明确要求 IC 在止血时**禁止亲自改代码**，演练时应当口头约束。
- 灰度回滚一旦走 [`PAYMENT_GRAY_RELEASE.md`](../../../PAYMENT_GRAY_RELEASE.md)，需要 Java 端订单核对窗口；时间线模板没把这一步标出来，建议加。

## 2. chaos dry-run（4 场景）

按 [`chaos/README.md`](../../../../chaos/README.md) 与 [`chaos-game-day.md`](../../chaos-game-day.md) 标准步骤执行 dry-run（**未** `--confirm`）。命令、stdout 与开始/结束时间戳保存在同目录 `*.log`：

| 场景 | 期望影响 | 期望恢复 | 本次 dry-run 日志 |
| --- | --- | --- | --- |
| `payment-restart` | 支付代理短暂 502，Java target 短暂 down | `/actuator/health` UP，502 归零 | [`chaos-payment-restart-dryrun.log`](chaos-payment-restart-dryrun.log) |
| `redis-stop` | Redis target down，部分缓存 / 防重放报错或降级 | Redis healthy，FastAPI/Java 5xx 回基线 | [`chaos-redis-stop-dryrun.log`](chaos-redis-stop-dryrun.log) |
| `api-restart` | FastAPI target 短暂 down，前端 API 调用失败 | `/api/health` 与 `/health/ready` 恢复 | [`chaos-api-restart-dryrun.log`](chaos-api-restart-dryrun.log) |
| `postgres-stop` | API health database degraded，Java Hikari 连接失败 | PostgreSQL healthy，Hikari 恢复 | 未跑（生产 / 预发都属于高风险，dry-run 也按规则只记录命令；如需记录见 [`chaos/README.md`](../../../../chaos/README.md) 「生产约束」） |

每个 dry-run 都打印了 `inject` / `recover` 命令但没有真正执行；与 `chaos_drill.py` 的 `--confirm` 守卫一致。在预发执行真实 confirm 时，把对应日志改名为 `chaos-<scenario>-confirm.log` 并补充：

- 注入开始 / 恢复完成时间戳；
- 期间 Grafana 关键 panel 截图或 Prometheus 查询结果；
- 实际恢复时长与告警触发情况；
- 与「期望恢复」差异。

## 3. DR restore dry-run

执行 [`disaster-recovery.md`](../../disaster-recovery.md) 中 PostgreSQL 恢复路径（**未** `--confirm`）：

```powershell
python scripts/restore_postgres.py "$env:TEMP\fake-modstore-postgres.dump"
python scripts/restore_postgres.py "$env:TEMP\fake-modstore-postgres.dump" --clean
```

输出与时间戳：[`dr-restore-postgres-dryrun.log`](dr-restore-postgres-dryrun.log)。两次都按预期打印「Dry run only. Re-run with --confirm after verifying the target database.」并退出 0；说明：

- 守卫生效：未传 `--confirm` 时，`pg_restore` 不会执行；
- `--clean` flag 在 dry-run 阶段不影响行为，与代码 [`scripts/restore_postgres.py`](../../../../scripts/restore_postgres.py) 第 26–29 行一致；
- 真实 confirm 路径仍需在备机或预发跑一次「small-dataset confirm」，把恢复用时记入本目录。

## 4. 与 RPO / RTO 假设的差异

`disaster-recovery.md` 当前承诺：RPO 24h、支付高峰 1h；RTO 单机 2h。本次 dry-run 没有真实计时点，**所以这些数字仍未通过实测验证**。建议下一次（预发 confirm）演练把以下四个时间戳显式打印：

1. 备份产生时间（`backups/<UTC>/manifest.json`）；
2. 灾备触发时间；
3. 恢复完成时间（`pg_restore` 退出 0）；
4. 业务冒烟全绿时间（`sre_smoke_check` 全部 ok）。

`(3) - (1)` 即对应 RPO，`(4) - (2)` 即对应 RTO。本目录预留 `dr-rpo-rto-<date>.csv` 落盘格式（首列时间戳，第二列事件名）。

## 5. 改进项

| 编号 | 内容 | 负责人 | 截止 |
| --- | --- | --- | --- |
| EX-2026-05-04-1 | `incident-response.md` 「沟通模板」加 **升级条件** 字段 | TBD | 下一次 PR |
| EX-2026-05-04-2 | `sre-operating-model.md` 第 49 行附近补「IC 不直接改代码」一行 | TBD | 下一次 PR |
| EX-2026-05-04-3 | 在预发跑一次 `chaos_drill.py --scenario payment-restart --confirm`，记录到 `exercises/<date>/` 并把恢复时长贴回本表 | TBD | 1 个发布周期内 |
| EX-2026-05-04-4 | 在备机跑一次 `restore_postgres.py --confirm`（small-dataset），实测 RPO / RTO 写入 `dr-rpo-rto-*.csv` | TBD | 1 个发布周期内 |

## 引用

- 本次原始 dry-run 日志（同目录）：
  - [`chaos-payment-restart-dryrun.log`](chaos-payment-restart-dryrun.log)
  - [`chaos-redis-stop-dryrun.log`](chaos-redis-stop-dryrun.log)
  - [`chaos-api-restart-dryrun.log`](chaos-api-restart-dryrun.log)
  - [`dr-restore-postgres-dryrun.log`](dr-restore-postgres-dryrun.log)
- 上游 runbook：
  - [`docs/sre-operating-model.md`](../../../sre-operating-model.md)
  - [`docs/runbooks/incident-response.md`](../../incident-response.md)
  - [`docs/runbooks/chaos-game-day.md`](../../chaos-game-day.md)
  - [`docs/runbooks/disaster-recovery.md`](../../disaster-recovery.md)
  - [`docs/runbooks/remote-server-operations.md`](../../remote-server-operations.md)
