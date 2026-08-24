# ADR-0004 Neuro Bus 启用 7 项可靠性机制（生产全开）

- 状态：已采纳（2026-07-31 前后随 Persy 记忆图谱上线收口）
- 决策者：架构负责人
- 涉及文件：
  - `app/neuro_bus/bus.py`（7 个环境开关，L107-144）
  - `app/neuro_bus/initializer.py`（启动日志声明）
  - `app/neuro_bus/deduplicator.py` / `circuit_breaker*.py` / `rate_limiter*.py` /
    `lifeline.py` / `tracer.py` / `dead_letter_queue.py` / `sla_collector.py`

## 背景

Neuro Bus 是 XCMAX 的事件/命令总线，承载 AI 引擎、意图分发、跨域事件流转。
早期只有「裸发布-订阅」，生产中暴露三类故障：

1. **重复投递**：上游重试导致同一事件被多次消费，产生重复副作用；
2. **级联故障**：下游处理器慢/挂时，上游持续堆积，拖垮整条链路；
3. **静默丢失**：消费失败的事件无落点，无法追溯、无法重放。

## 决策

为 Neuro Bus 引入 **7 项可靠性机制**，全部由环境变量开关控制，
**生产配置全部启用**（见 `app/neuro_bus/bus.py`）：

| 机制 | 环境变量 | 作用 |
|------|---------|------|
| DEDUP | `XCAGI_NEURO_BUS_DEDUP` | 事件去重，防重复消费 |
| CIRCUIT | `XCAGI_NEURO_BUS_CIRCUIT` | 熔断，下游故障时快速失败防级联 |
| RATE_LIMIT | `XCAGI_NEURO_BUS_RATE_LIMIT` | 限流，保护下游处理能力 |
| LIFELINE | `XCAGI_NEURO_BUS_LIFELINE` | 生命线/心跳，检测处理器存活 |
| TRACE | `XCAGI_NEURO_BUS_TRACE` | 全链路追踪，事件可溯源 |
| DLQ_AUTO | `XCAGI_NEURO_BUS_DLQ_AUTO` | 死信队列自动转移，失败事件不丢失 |
| SLA_LOG | `XCAGI_NEURO_BUS_SLA_LOG` | SLA 采集，延迟/超时指标落盘 |

设计要点：

1. **开关化**：每项机制独立环境变量，`_neuro_reliability_wanted()` 统一判定，
   staging 与生产可差异化默认（如 RATE_LIMIT/LIFELINE/TRACE/DLQ_AUTO/SLA_LOG
   staging 默认关、生产全开）。
2. **可观测优先**：TRACE + SLA_LOG 保证任何一次投递都可回放与度量。
3. **失败不静默**：DLQ_AUTO 确保消费失败的事件进入死信队列而非丢弃。

## 后果

- **正面**：事件链路具备去重、熔断、限流、可追溯、不丢失的完整可靠性；
  故障可定位（TRACE）、可恢复（DLQ 重放）、可度量（SLA）。
- **代价**：DEDUP/TRACE 引入额外存储与查询开销；7 个开关增加配置面，
  需文档（本 ADR）固化「生产全开」的约定。
- **约定**：生产环境 7 项全启用是硬约束，任何降级需走变更评审。

## 关联

- `app/neuro_bus/initializer.py` 启动时打印已启用机制清单
- 与 Persy 统一记忆图谱（2026-07-31 上线）同期收口
