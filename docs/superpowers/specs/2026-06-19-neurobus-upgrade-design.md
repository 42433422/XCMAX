# NeuroBus 升级设计：从"看着厉害"到"真厉害"

**日期**：2026-06-19
**作者**：AI 辅助设计 + 用户决策
**状态**：待审阅
**影响范围**：`FHD/app/neuro_bus/`、`FHD/app/domain/neuro/`、`FHD/scripts/dev/`、`FHD/tests/test_neuro_bus/`

---

## 1. 背景与目标

### 1.1 现状评估

NeuroBus 是 XCMAX 自研的事件总线，72 个文件 / 11,794 行代码，具备完整的可靠性机制栈（熔断/死信/去重/限流/重试/保命通道/SLA 分层/追踪）。架构雄心 9/10，机制覆盖 8/10，但落地真实度仅 6/10，存在以下问题：

| 问题 | 严重度 | 根因 |
|------|--------|------|
| NN 策略路由是未训练占位件，`confidence=0.72` 硬编码 | 高 | 无训练闭环、无数据、无评估 |
| 自研 Tracer 无法对接 OTel 生态 | 高 | 自造 span 模型，W3C TraceContext 不兼容 |
| SLA 数字是目标值非实测值，易误导 | 中 | 无实测采集，文档未区分 |
| Redis PubSub 跨 Pod 丢消息 | 中 | fire-and-forget，无消费确认 |
| 领域文件拆分不统一 | 低 | 命名规范不一致 |

### 1.2 升级目标

将 NeuroBus 从"看着厉害"升级到"真厉害"：

- NN 路由：从占位件升级为真实训练闭环（LLM 交叉评审标注 + 离线预训练 + 在线 Bandit 微调）
- Tracer：保留接口 + OTel 底层，对接 Jaeger/Tempo 生态
- SLA：实测驱动，区分目标值与实测达标率
- 传输层：Redis PubSub → Redis Streams，消费确认 + 持久化
- 领域文件：统一拆分规范

### 1.3 非目标

- 不重写 NeuroBus 核心（`bus.py` 的优先级队列/发布订阅保持不变）
- 不迁移到 Kafka/NATS（Redis 仍是唯一传输层）
- 不做 NeuroBus 与外部 MQ 的联邦（单集群内闭环）

---

## 2. 改进项 1：NN 路由训练闭环

### 2.1 架构

```
┌─────────────────────────────────────────────────────────────┐
│  离线预训练管线                                               │
│  routing_log.jsonl → 特征提取 → LLM 交叉评审标注              │
│       → 训练 RoutingMLP → 评估(准确率/SLA提升/推理延迟)      │
│       → 产出 policy_vN.pt + manifest.json                   │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  在线推理（policy_router.py）                                 │
│  事件 → build_routing_features → predict_action_index        │
│       → RoutingDecision → ProcessorCoordinator               │
│       → 记录 (features, action, latency, sla_hit) 到 jsonl   │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  在线微调（Contextual Bandit）                                │
│  滑动窗口采样 → reward=sla_hit*0.6+success*0.4               │
│       → ε-greedy exploration(ε=0.1)                          │
│       → 增量更新 policy → 新版本 manifest → 灰度切换          │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 LLM 交叉评审标注（无人工）

**三模型独立盲标**：
- LLM-A：DeepSeek-V3
- LLM-B：GPT-4o
- LLM-C：Qwen-Max
- 各自对 1 万条 `routing_log.jsonl` 样本独立标注，输出 `{processor, reason, confidence}`

**一致性分级**：
- **gold（3/3 一致）**：直接进训练集，权重 1.0
- **silver（2/3 一致）**：进训练集，权重 0.7
- **disputed（全不一致）**：送 LLM-D（Claude-Sonnet）仲裁

**争议仲裁（无人工）**：
- LLM-D 仲裁输出最终标签 + 理由，作为 ground truth
- 仲裁结果进训练集，权重 1.0
- **规则路由交叉验证**：对比 LLM-D 仲裁与历史规则路由结果
  - 一致率 ≥ 70%：仲裁可信，disputed 全部采纳
  - 一致率 < 70%：仲裁偏离规则，disputed 样本丢弃（不进训练集）

**共同偏差检测**：
- 统计三模型在每类事件上的标签分布
- 若三模型都 >80% 选 Conscious → 存在保守偏差
- 触发 prompt 调优（加 few-shot 示例平衡）或特征工程修正

**成本**：3 × 1 万条标注 + 1 × 争议仲裁 ≈ $20-35

**Prompt 模板（三模型统一）**：
```
你是 NeuroBus 路由专家。给定事件特征，选择最优处理器级别。

处理器级别：
- reflex: <1ms，仅限简单意图（问候/确认/否定/帮助/紧急停止）
- subconscious: <10ms，异步后台任务（日志/统计/缓存更新）
- conscious: <200ms，核心业务逻辑（订单/支付/库存/客户变更）

事件特征：
- text: {event_text}
- event_type: {event_type}
- priority: {priority}
- historical_sla_hit_rate: {sla_rate}
- text_length: {len}
- keyword_hits: {keywords}

输出 JSON: {"processor": "reflex|subconscious|conscious", "reason": "...", "confidence": 0.0-1.0}
```

### 2.3 训练流程

**特征**：沿用 `features.py` 的 16 维（文本长度/关键词命中/事件类型/优先级/历史 SLA 等），不扩维。

**模型**：沿用 `RoutingMLP`（16 → 32 → 3），删除 `confidence=0.72` 硬编码，改为 softmax 输出。

**训练数据**：gold + silver + 仲裁后 disputed，按权重采样。

**评估指标**（必须全部达标才上线）：
- 路由准确率 ≥ 规则基线 +5%（以 LLM-D 仲裁结果为 ground truth）
- SLA 达标率提升 ≥ 3%（A/B 实测）
- NN 推理延迟 P99 < 2ms（CPU，单次 forward）

### 2.4 在线微调（Contextual Bandit）

**reward 信号**：`reward = sla_hit * 0.6 + success * 0.4`
- `sla_hit`：该次路由后操作是否达到 SLA 目标（0/1）
- `success`：处理器是否成功完成（0/1）

**探索策略**：ε-greedy，ε=0.1（10% 概率随机选处理器探索）

**更新机制**：
- 滑动窗口 10000 条样本
- off-policy 修正（重要性采样权重）
- 每 10000 条触发一次增量更新，产出 `policy_vN.pt`
- 新版本写入 `manifest.json`，灰度切换

### 2.5 部署策略（三阶段）

| 阶段 | 配置 | 持续 | 退出条件 |
|------|------|------|---------|
| 影子模式 | `XCAGI_ROUTING_POLICY_ENABLED=shadow` | 2 周 | 记录 NN 决策不实际路由，对比规则路由差异 ≤ 15% |
| 灰度 | `XCAGI_ROUTING_POLICY_ENABLED=1` + `XCAGI_ROUTING_POLICY_CANARY_RATIO=0.1` | 1 周 | SLA 达标率不降，错误率不升 → 扩到 50% → 100% |
| 全量 | `XCAGI_ROUTING_POLICY_ENABLED=1` | 持续 | 监控 SLA / 错误率 / 推理延迟 |

### 2.6 文件清单

**新增**：
- `scripts/dev/llm_label_ensemble.py` — 三模型并行标注调度
- `scripts/dev/llm_label_arbitrate.py` — 争议样本 LLM-D 仲裁
- `scripts/dev/analyze_label_consensus.py` — 一致性分析 + 偏差检测
- `scripts/dev/train_routing_policy.py` — 离线训练脚本
- `scripts/dev/eval_routing_policy.py` — 评估脚本
- `app/neuro_bus/routing/online_learner.py` — 在线微调器
- `tests/test_neuro_bus/test_routing_policy.py` — 训练/推理/评估单测
- `tests/test_neuro_bus/test_llm_labeling.py` — 标注管线单测

**改动**：
- `app/neuro_bus/routing/policy_nn.py` — 删除 `confidence=0.72` 硬编码，改 softmax
- `app/neuro_bus/routing/policy_router.py` — 加影子模式 + 灰度比例 + reward 记录
- `app/neuro_bus/routing/routing_log.py` — 扩展日志字段（`sla_hit` / `success` / `latency_ms`）

---

## 3. 改进项 2：Tracer OTel 底层化

### 3.1 架构

```
调用层（不改）:
  from app.neuro_bus.tracer import Tracer, Span
  tracer.start_span("event.publish")  ← 接口不变

tracer.py 内部（改底层）:
  ┌─────────────────────────────────┐
  │  Span (保留 dataclass 接口)      │
  │   - span_id/trace_id/parent_id  │
  │   - start_time/end_time/status  │
  │   - tags/events                  │
  └──────────┬──────────────────────┘
             │ 内部委托
             ▼
  ┌─────────────────────────────────┐
  │  OTel SDK (新增依赖)             │
  │   tracer = trace.get_tracer(...) │
  │   with tracer.start_as_current_span(): │
  │       otel_span.set_attribute()  │
  │       otel_span.add_event()      │
  └──────────┬──────────────────────┘
             │ 导出
             ▼
  OTel exporter → OTLP/gRPC → Jaeger/Tempo/Grafana
```

### 3.2 关键设计

**接口零改动**：`Tracer` / `Span` 公共 API 保持不变，所有调用点不改。

**底层委托**：
- `Span.__post_init__` 时创建对应 OTel span
- `Span.set_tag()` → `otel_span.set_attribute()`
- `Span.add_event()` → `otel_span.add_event()`
- `Span.finish()` → `otel_span.end()`
- `trace_id` / `span_id` 从 OTel context 读取，保证 W3C TraceContext 兼容

**新增依赖**：
- `opentelemetry-api`
- `opentelemetry-sdk`
- `opentelemetry-exporter-otlp`
- 加入 `requirements.txt` 的 `[project.optional-dependencies.observability]`

**Exporter 配置**（环境变量驱动）：
- `OTEL_EXPORTER_OTLP_ENDPOINT` → OTLP collector
- `OTEL_SERVICE_NAME=xcagi-neurobus`
- 未配置时降级为 ConsoleSpanExporter（开发环境）

**HTTP 传播**：`neuro_http_trace.py` 中间件改用 OTel 的 `OTELPropagator`（W3C TraceContext），跨服务 trace_id 自动传播。

**降级路径**：OTel SDK import 失败时，Span 退化为纯内存对象（当前行为），保证向后兼容。

### 3.3 文件清单

**改动**：
- `app/neuro_bus/tracer.py` — 内部委托 OTel SDK
- `app/neuro_bus/neuro_http_trace.py` — 改用 OTel Propagator
- `app/neuro_bus/neuro_application_instrumentation.py` — 适配 OTel context
- `requirements.txt` — 新增 OTel 依赖
- `FHD/k8s/configmap.yaml` — 新增 OTel 环境变量

**新增**：
- `tests/test_neuro_bus/test_tracer_otel.py` — OTel 集成测试

---

## 4. 改进项 3：SLA 实测驱动

### 4.1 流程

```
阶段 1: 实测采集（2 周）
  SLAMonitor 记录每次操作的实际延迟
    → sla_measurements.jsonl
    字段: level, operation, p50, p99, p999, sla_target, sla_hit

阶段 2: 报告生成
  scripts/dev/analyze_sla.py
    → 输出实测 P99 vs 目标值对照表
    → 标注哪些级别达不到目标

阶段 3: 文档标注（不调目标值）
  sla_controller.py + SLO.md + domain/README.md
  明确区分: "目标 SLO" vs "实测 P99 (2026-06-19) + 达标率"
```

### 4.2 关键设计

**采集器**：扩展 `SLAMonitor`，新增 `record_measurement(level, operation, latency_ms, sla_hit)`，写入 `metrics/sla_measurements.jsonl`。

**采集开关**：`XCAGI_NEURO_BUS_SLA_COLLECT=1`（默认关，避免生产 IO 开销）。

**文档标注原则（不调目标值）**：
- Reflex 目标保持 <1ms（保住"反射弧"卖点）
- 标注实测 P99 + 达标率，如"Reflex 目标 <1ms，实测 P99 3.2ms，达标率 92%"
- 诚实比吹牛重要，但不破坏架构隐喻

**分析脚本**：`scripts/dev/analyze_sla.py`，读取 jsonl，按 level + operation 聚合 P50/P99/P999，输出对照表 + 达标率。

**持续监控**：接入 Prometheus（已有 `xcagi_alerts`），`sla_violation_total` 指标告警。

### 4.3 文件清单

**改动**：
- `app/neuro_bus/sla_controller.py` — 新增 `record_measurement`
- `docs/SLO.md` — 区分目标值与实测值
- `app/domain/README.md` — 标注实测达标率

**新增**：
- `scripts/dev/analyze_sla.py` — SLA 分析报告
- `tests/test_neuro_bus/test_sla_collection.py` — 采集器单测

---

## 5. 改进项 4：Redis Streams 升级

### 5.1 架构

```
生产端（publish）:
  NeuroBus.publish(event)
       ↓
  RedisStreamsBridge
       ↓
  XADD neurobus:events * event_json
       (Stream 自动持久化)

消费端（subscribe）:
  消费组: neurobus-workers
  XGROUP CREATE neurobus:events neurobus-workers $ MKSTREAM

  每个 Pod 一个消费者:
  XREADGROUP GROUP neurobus-workers <consumer-id>
    COUNT 100 BLOCK 5000 STREAMS neurobus:events >
       ↓
  处理成功 → XACK neurobus:events neurobus-workers <msg-id>
  处理失败 → 重试 3 次 → XPENDING → DLQ stream
```

### 5.2 关键设计

**新文件**：`app/neuro_bus/transports/redis_streams.py`，新增 `RedisStreamsBridge`，与现有 `RedisPubSubBridge` 并存（灰度切换）。

**消息格式**：复用 `NeuroEvent.to_dict()`，XADD 字段 `payload=json`，保留 `_neuro_origin_instance` 防环。

**消费确认**：
- `XREADGROUP` 拉取 → 处理 → `XACK` 确认
- 未 ACK 的消息进入 `XPENDING`，由死信扫描器定期重投或转 DLQ
- 重试 3 次仍失败 → `XADD neurobus:dlq * event_json` + `XACK` 原消息

**重连恢复**：
- 断连时记录最后消费的 `msg-id`
- 重连后 `XREADGROUP ... STREAMS neurobus:events <last-msg-id>` 续传
- 消费组自动维护 `pending` 列表，超时（5min）未 ACK 的消息由其他消费者接管（`XAUTOCLAIM`）

**切换策略**：
- `XCAGI_NEURO_BUS_REDIS_TRANSPORT=pubsub|streams`（默认 pubsub）
- 灰度：先 staging 切 streams，跑 1 周稳定后切 production
- 保留 pubsub 代码 1 个版本周期后删除

**容量规划**：
- `MAXLEN ~ 100000`（Stream 裁剪，约 100MB 内存）
- 消费组 `neurobus-workers`，每 Pod 一个 consumer-id（hostname-pid）

### 5.3 文件清单

**新增**：
- `app/neuro_bus/transports/redis_streams.py` — Streams 桥接
- `tests/test_neuro_bus/test_redis_streams.py` — Streams 集成测试

**改动**：
- `app/neuro_bus/bus.py` — 支持 transport 切换
- `app/neuro_bus/initializer.py` — 根据 env 选择 transport

---

## 6. 改进项 5：领域文件统一拆分

### 6.1 规范

```
app/neuro_bus/domains/
├── {name}_domain.py          # 事件定义 + Domain 注册
└── {name}_domain_handlers.py # 处理器逻辑（Handler 类）
```

### 6.2 迁移清单

| 领域 | 当前状态 | 动作 |
|------|---------|------|
| ocr | 已拆 | 不动 |
| print | 已拆 | 不动 |
| shipment | 已拆 | 不动 |
| inventory | 已拆 | 不动 |
| product | 已拆 | 不动 |
| payment | 单文件 | 拆出 `payment_domain_handlers.py` |
| order | 单文件 | 拆出 `order_domain_handlers.py` |
| customer | 单文件 | 拆出 `customer_domain_handlers.py` |
| ai_service | 单文件 | 拆出 `ai_service_domain_handlers.py` |
| intent | 单文件 | 拆出 `intent_domain_handlers.py` |
| safety | 单文件 | 拆出 `safety_domain_handlers.py` |
| wechat | 单文件 | 拆出 `wechat_domain_handlers.py` |

### 6.3 拆分原则

**`domain.py` 保留**：
- 事件类定义（继承 `NeuroEvent`）
- `register_{name}_domain()` 注册函数
- Domain 元数据（名称、优先级、SLA 级别）

**`handlers.py` 迁出**：
- 所有 `@handler` 装饰的处理器函数
- 处理器依赖的服务/仓库
- 处理器单测（`tests/test_neuro_bus/test_{name}_domain_handlers.py`）

**拆分阈值**：单文件 > 300 行必须拆；< 300 行但含 ≥ 3 个处理器也拆。

**向后兼容**：`domain.py` 末尾 `from .{name}_domain_handlers import *` 保持导入兼容，调用方无需改。

### 6.4 文件清单

**新增**：7 个 `{name}_domain_handlers.py` + 对应单测

**改动**：7 个 `{name}_domain.py`（迁出处理器，加 `import *`）

---

## 7. 实施批次

### 7.1 批次划分

**批次 1（立即启动，1 周完成代码）**：
- 改进项 3：SLA 采集启动（为 NN 路由 reward 信号铺路）
- 改进项 2：Tracer OTel 底层化
- 改进项 4：Redis Streams 升级
- 改进项 5：领域文件拆分

**批次 2（批次 1 完成 + SLA 采集 2 周后启动）**：
- 改进项 1：NN 路由训练闭环
  - 依赖批次 1 的 SLA 采集数据作为 reward 信号
  - LLM 交叉评审标注（无人工）
  - 离线训练 + 影子模式 2 周 + 灰度

### 7.2 依赖关系

```
批次 1:
  SLA 采集 ──┐
  Tracer OTel │
  Redis Streams│ ← 并行，无依赖
  领域拆分 ──┘
               ↓
         SLA 数据积累 2 周
               ↓
批次 2:
  LLM 标注 → 训练 → 影子 → 灰度 → 全量
```

### 7.3 总周期

- 批次 1：1 周编码 + 1 周测试 = 2 周
- SLA 采集积累：2 周（与批次 1 测试并行）
- 批次 2：1 周标注 + 1 周训练 + 2 周影子 + 1 周灰度 = 5 周
- **总周期：约 7 周**

---

## 8. 测试策略

### 8.1 单元测试

每个改进项配套单测，遵循项目 `test-coverage-90-prompt.md` 规范：
- LLM 标注管线：mock 三模型 API，验证一致性分级逻辑
- 训练脚本：小数据集验证训练收敛
- 在线微调器：验证 ε-greedy 探索 + off-policy 修正
- Tracer OTel：验证 span 委托 + 降级路径
- SLA 采集器：验证 jsonl 写入 + 聚合分析
- Redis Streams：用 fakeredis 验证 XADD/XREADGROUP/XACK/DLQ
- 领域拆分：验证 `import *` 兼容性

### 8.2 集成测试

- NN 路由影子模式：端到端验证 NN 决策记录不实际路由
- Tracer OTel：启动 OTel collector，验证 span 导出
- Redis Streams：双 Pod 模拟，验证消费确认 + 重连恢复 + DLQ

### 8.3 回归测试

- 全量 `pytest tests/test_neuro_bus/` 通过
- 现有 196 个红灯测试不增加（理想状态下减少）
- 覆盖率棘轮不回退（行 ≥ 80%，分支 ≥ 70%）

---

## 9. 回滚策略

### 9.1 各改进项回滚

| 改进项 | 回滚方式 |
|--------|---------|
| NN 路由 | `XCAGI_ROUTING_POLICY_ENABLED` 设为空，回退规则路由 |
| Tracer OTel | 卸载 OTel 依赖，Span 退化为内存对象（降级路径已内置） |
| SLA 采集 | `XCAGI_NEURO_BUS_SLA_COLLECT=0`，停止采集 |
| Redis Streams | `XCAGI_NEURO_BUS_REDIS_TRANSPORT=pubsub`，回退 PubSub |
| 领域拆分 | `import *` 保证调用方零改动，无需回滚 |

### 9.2 紧急回滚

- 任何改进项导致生产故障 → 环境变量回退 + K8s `rollout undo`
- NN 路由灰度阶段故障 → 立即 `XCAGI_ROUTING_POLICY_ENABLED=` 清空

---

## 10. 验收标准

### 10.1 批次 1 验收

- [ ] Tracer 接口零改动，OTel span 成功导出到 collector
- [ ] SLA 采集器写入 `sla_measurements.jsonl`，`analyze_sla.py` 输出报告
- [ ] Redis Streams 在 staging 稳定运行 1 周，无消息丢失
- [ ] 7 个领域文件拆分完成，`import *` 兼容性测试通过
- [ ] 全量 `pytest tests/test_neuro_bus/` 通过
- [ ] 覆盖率棘轮不回退

### 10.2 批次 2 验收

- [ ] LLM 交叉评审标注完成，一致性报告达标（gold ≥ 60%）
- [ ] 训练的 MLP 评估指标全部达标（准确率 +5%、SLA +3%、延迟 <2ms）
- [ ] 影子模式 2 周，NN 与规则路由差异 ≤ 15%
- [ ] 灰度 10% → 50% → 100%，SLA 达标率不降
- [ ] 在线微调器产出 `policy_vN.pt`，manifest 更新
- [ ] 全量 `pytest tests/test_neuro_bus/` 通过

---

## 11. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| LLM 标注共同偏差（都偏 Conscious） | 中 | 高 | 共同偏差检测 + prompt 调优 + 特征工程 |
| Reflex SLA 实测达标率过低（<80%） | 高 | 中 | 诚实标注达标率，不调目标值；后续考虑 C 扩展优化 |
| Redis Streams 内存超限 | 低 | 中 | MAXLEN 裁剪 + 监控 stream 长度 |
| OTel SDK 性能开销 | 低 | 低 | 采样率控制（已有 `XCAGI_NEURO_BUS_TRACE_SAMPLE_RATE`） |
| 在线 Bandit 探索导致 SLA 波动 | 中 | 中 | ε=0.1 保守探索 + 灰度比例控制 |

---

## 12. 参考资料

- 现有代码：`FHD/app/neuro_bus/`
- 架构文档：`FHD/app/domain/README.md`
- CI/CD 规范：`.trae/rules/cicd-e2e-prompt.md`
- 测试规范：`.trae/rules/test-coverage-90-prompt.md`
- SLO 文档：`FHD/docs/SLO.md`
