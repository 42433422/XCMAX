# Neuro-DDD 迁移路线图

**版本**: 1.0  
**日期**: 2026-04-18  
**状态**: 规划中

---

## 一、现状深度分析

### 1.1 迁移状态分层

```
┌─────────────────────────────────────────────────────────────────────┐
│                         架构层次迁移状态                              │
├─────────────────────────────────────────────────────────────────────┤
│  Level 5 │ Routes 层          │ 3/7 (42.9%) │ 装饰器路由已接入        │
│  Level 4 │ Application 层    │ 20/20 有追踪 │ 0% 事件驱动            │
│  Level 3 │ Services 层        │ 4/51 (7.8%) │ 仅追踪装饰器           │
│  Level 2 │ Domain 层          │ 73.1%       │ 领域定义完整            │
│  Level 1 │ NeuroBus 核心     │ 99.6%       │ 基础设施就绪            │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 关键发现

**"已迁移"的真相：**

- `instrument_service_layer_class` = 只是加了**追踪包装**
- `instrument_application_service_class` = 只是加了**追踪包装**
- **没有使用 NeuroBus 事件总线**
- **没有真正的事件驱动架构**

**业务代码现状：**

```python
# 当前模式（直接调用）
class ProductAppService:
    def create_product(self, data):
        return self._products_service.create_product(data)  # 直接调用

# 目标模式（事件驱动）
class ProductAppService:
    def create_product(self, data):
        event = ProductCreatedEvent(data)
        self._neuro_bus.publish(event)  # 发布事件
        return {"success": True, "event_id": event.id}
```

---

## 二、迁移目标定义

### 2.1 真正迁移的标准


| 层次          | 当前状态  | 目标状态                    | 判断标准              |
| ----------- | ----- | ----------------------- | ----------------- |
| Routes      | 装饰器接入 | **事件发布**                | 路由函数发布 NeuroEvent |
| Application | 追踪包装  | ** orchestration + 事件** | 用例编排通过事件驱动        |
| Services    | 追踪包装  | **事件处理器**               | 服务方法订阅事件而非直接调用    |
| Domain      | 定义完整  | **领域事件完整**              | 领域对象发出领域事件        |


### 2.2 成功指标

- **事件流转率**: 80% 业务操作通过 NeuroBus 流转
- **领域覆盖率**: 100% 核心领域（Shipment/Order/Product）接入
- **响应时间**: P99 < 200ms（ReflexArc 模式 < 10ms）
- **系统吞吐量**: > 1000 events/sec

---

## 三、分阶段迁移路线图

### Phase 1: 试点验证 (第 1-2 周)

**目标**: 选择 1 个高频用例，完成端到端迁移，验证架构可行性

**选择用例**: `ProductAppService.create_product` (产品创建)

**理由**:

- 高频操作（管理后台核心功能）
- 相对独立（依赖少）
- 有现成追踪（ProductsService 已 instrument）
- 失败影响可控

**具体任务**:


| 任务                     | 工作量 | 负责人       | 产出     |
| ---------------------- | --- | --------- | ------ |
| 定义 ProductCreatedEvent | 2h  | Architect | 事件定义类  |
| 创建 ProductDomain 处理器   | 4h  | Backend   | 事件处理器  |
| 重构 ProductAppService   | 4h  | Backend   | 事件发布代码 |
| 集成测试                   | 4h  | QA        | 测试用例   |
| 性能基准                   | 2h  | DevOps    | 性能报告   |


**验收标准**:

```python
# 重构后代码示例
class ProductAppService:
    def create_product(self, data: Dict) -> Dict:
        # 1. 创建领域事件
        event = ProductCreatedEvent(
            payload=data,
            source="product_app_service",
            priority=EventPriority.NORMAL
        )
        
        # 2. 发布到 NeuroBus
        self._neuro_bus.publish(event)
        
        # 3. 等待处理结果（异步）
        result = self._wait_for_result(event.id, timeout=5.0)
        
        return {
            "success": True,
            "event_id": event.id,
            "product_id": result.get("product_id")
        }
```

---

### Phase 2: 核心领域迁移 (第 3-6 周)

**目标**: 核心业务 50% 接入 Neuro-DDD

**优先级排序**:

```
P0 (第3-4周): Product + Shipment
├── ProductDomain (产品域)
│   ├── ProductCreatedEvent
│   ├── ProductUpdatedEvent
│   ├── ProductDeletedEvent
│   └── ProductImportedEvent
│
└── ShipmentDomain (发货单域)
    ├── ShipmentCreatedEvent
    ├── ShipmentItemAddedEvent
    ├── ShipmentPrintedEvent
    └── ShipmentCancelledEvent

P1 (第5周): Order + Customer
├── OrderDomain (订单域)
└── CustomerDomain (客户域)

P2 (第6周): Inventory + Print
├── InventoryDomain (库存域)
└── PrintDomain (打印域)
```

**迁移模式**:

```python
# 模式一：Application 层发布事件（推荐）
class ShipmentAppService:
    def create_shipment(self, unit_name, items):
        event = ShipmentCreatedEvent(unit_name=unit_name, items=items)
        self._bus.publish(event, domain="shipment")
        return self._await_result(event)

# 模式二：Services 层订阅事件
class ShipmentService:
    @on_event("shipment.created")
    def handle_create(self, event):
        shipment = Shipment.create(event.unit_name)
        for item in event.items:
            shipment.add_item(item)
        self._repository.save(shipment)
```

---

### Phase 3: 系统级迁移 (第 7-12 周)

**目标**: 核心业务 80% 以上接入

**任务分解**:


| 周次    | 领域            | 关键事件                                | 预期产出     |
| ----- | ------------- | ----------------------------------- | -------- |
| 7     | PaymentDomain | PaymentCreated, PaymentCompleted    | 支付流程事件化  |
| 8     | OCRDomain     | OCRTaskSubmitted, OCRCompleted      | OCR 异步处理 |
| 9     | WeChatDomain  | MessageReceived, MessageSent        | 微信消息事件化  |
| 10    | AIDomain      | IntentRecognized, ResponseGenerated | AI 对话事件化 |
| 11-12 | ReflexArc 优化  | 高频路径 < 10ms                         | 性能调优     |


---

### Phase 4: 生态建设 (第 13-16 周)

**目标**: 形成团队标准，建立开发者体验

**任务**:

1. **脚手架工具**: `neuro-cli generate event-handler`
2. **可视化工具**: 事件流追踪 Dashboard
3. **最佳实践文档**: 《Neuro-DDD 开发指南》
4. **培训计划**: 团队内部技术分享

---

## 四、迁移阻力与应对策略

### 4.1 识别核心阻力


| 阻力       | 严重程度 | 应对策略                     |
| -------- | ---- | ------------------------ |
| **学习成本** | 高    | 1对1导师制 + 代码模板            |
| **业务压力** | 高    | 并行开发（新业务用 Neuro，旧业务逐步迁移） |
| **测试成本** | 中    | 自动化测试 + 影子流量验证           |
| **性能担忧** | 中    | 基准测试 + ReflexArc 快速路径    |
| **回滚风险** | 中    | 特性开关（Feature Flag）       |


### 4.2 风险控制策略

```python
# 特性开关模式
class ProductAppService:
    def create_product(self, data):
        if self._use_neuro_ddd():
            # Neuro-DDD 路径
            return self._create_via_event(data)
        else:
            # 传统路径（兜底）
            return self._products_service.create_product(data)
```

---

## 五、投资回报分析

### 5.1 投入估算


| 阶段      | 人天         | 成本估算          |
| ------- | ---------- | ------------- |
| Phase 1 | 10 人天      | ¥ 15,000      |
| Phase 2 | 30 人天      | ¥ 45,000      |
| Phase 3 | 40 人天      | ¥ 60,000      |
| Phase 4 | 20 人天      | ¥ 30,000      |
| **总计**  | **100 人天** | **¥ 150,000** |


### 5.2 预期收益


| 收益项     | 量化指标        | 时间框架 |
| ------- | ----------- | ---- |
| 开发效率提升  | +30%        | 6个月后 |
| 系统响应速度  | P99 < 200ms | 3个月后 |
| 故障恢复时间  | MTTR -50%   | 6个月后 |
| 新功能上线速度 | +40%        | 6个月后 |
| 技术债务减少  | 统一架构        | 长期   |


---

## 六、下一步行动

### 立即行动项（本周内）

- **决策确认**: 是否启动 Phase 1 试点？
- **人员分配**: 确定试点负责人（建议 1 名架构师 + 1 名后端）
- **环境准备**: 创建 feature/neuro-migration 分支
- **基线测试**: 记录当前 Product 创建性能基准

### 风险预警

⚠️ **如果不启动迁移**:

- 技术债务持续累积（维护两套架构）
- 架构文档继续沦为摆设
- 团队技术分裂加剧
- 前期投入的 450+ 小时架构设计沉没成本

---

**准备就绪，等待执行指令。**

---

**文档版本**: v1.0  
**最后更新**: 2026-04-18  
**审核人**: Chief Architect