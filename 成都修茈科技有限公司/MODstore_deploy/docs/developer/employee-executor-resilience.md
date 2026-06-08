# AI 员工执行器弹性与观测（`employee_executor`）

MODstore 的 [`employee_executor`](../../modstore_server/employee_executor.py) 在 **同一 Python 进程内**顺序执行感知 → 认知（LLM）→ `actions.handlers`。这里没有独立的「Skill 操作系统进程」，因此运维文档里应避免写「重启 Skill 进程」；应使用下面这组术语。

## 术语

| 说法 | 含义 |
|------|------|
| **重试（retry）** | 对**短时/transient**失败（超时、连接复位、429、503 等）在同一请求内有限次再次调用认知层。 |
| **降级（degrade）** | handler 或整条链路在失败后返回部分结果、跳过非关键步骤，或依赖既有兜底（如 agent 不可用时由别处处理）。 |
| **熔断 / 目录级处置** | 连续失败达到阈值时由 [`employee_health_scan`](../../modstore_server/employee_health_scan.py) 等对目录条目告警或下架，与单次任务内重试互补。 |
| **负载感知** | 通过指标表 [`EmployeeExecutionMetric`](../../modstore_server/models.py)、结构化日志与可选进程内并发槽观察吞吐；扩展部署时再引入队列深度等指标。 |

目录级自愈（下架坏包）与健康巡检配置见 `employee_health_scan` 模块文档字符串。

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `MODSTORE_EXECUTOR_MAX_CONCURRENT` | （空） | 大于 `0` 时，进程内用线程信号量限制**同时执行**的 `execute_employee_task` 数量（单 worker 内有效；多 worker 各自计数）。 |
| `MODSTORE_COGNITION_TRANSIENT_RETRIES` | `1` | 认知层在判定为 transient 的错误后**额外**重试次数（0–2）；总尝试次数 = 1 + 该值。 |
| `MODSTORE_EXECUTOR_LOG_DETAIL` | `0` | 设为 `1`/`true` 时在完成日志中附带 handler 列表等字段。 |

## 事件：`employee.execution.recovery`

当认知层因 transient 错误触发重试并最终成功时，执行器会通过 [`incident_bus`](../../modstore_server/incident_bus.py) 发布 **`employee.execution.recovery`**（已在 [`EVENT_TYPES`](../../modstore_server/integrations/ops_action_handlers.py) 注册），供 `EmployeeTriggerBinding` 或 Redis Stream 订阅方消费（例如记入风险评估或运维台账）。

**Payload 字段（约定）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `employee_id` | string | 员工包 id |
| `task` | string | 任务摘要（截断） |
| `recovery_action` | string | 固定为 `cognition_retry`（后续可扩展） |
| `success` | bool | 本次恢复流程是否以成功结束 |
| `original_error` | string | 首次失败错误信息（截断） |
| `attempts` | int | 总尝试次数 |

与「文档变更」无关的恢复事件**不会**触发 `doc_change`；与 `mods-and-eskill-curator` 的联动应通过绑定该事件类型或下游聚合服务完成。
