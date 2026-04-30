# Neuro-DDD 完整迁移定义与验收标准

**版本**: 1.0  
**制定日期**: 2026-04-18  
**适用范围**: XCAGI 项目 Neuro-DDD 架构迁移  

---

## 📋 完整迁移的分层定义

### Level 1: 观测层迁移（已完成 ✅）

**目标**: 所有代码可观测、可追踪

#### 验收标准


| 层次          | 指标  | 目标值  | 当前值          | 状态  |
| ----------- | --- | ---- | ------------ | --- |
| Application | 接入率 | 100% | **100%** ✅   | 完成  |
| Services    | 接入率 | 80%  | **12.7%** ❌  | 待完成 |
| Routes      | 接入率 | 80%  | **42.9%** ⚠️ | 进行中 |
| Backend     | 接入率 | 80%  | **0%** ❌     | 未开始 |


#### 技术实现

**Application 层** (已完成):

```python
# 所有 AppService 使用装饰器
@instrument_application_service_class
class ShipmentAppService:
    def create_shipment(self, data):
        # 自动追踪：start → end/error
        pass
```

**Services 层** (待完成):

```python
# 所有 Service 使用装饰器
@instrument_service_layer_class
class OCRService:
    def recognize(self, image):
        # 自动追踪：start → end/error
        pass
```

**Routes 层** (部分完成):

```python
# FastAPI 中间件
@app.middleware("http")
async def neuro_http_middleware(request, call_next):
    # 自动发布：http.request.start/end
    pass
```

#### 完成标志

- ✅ Application 层 21 个服务全部接入
- ⚠️ Services 层 40+ 个服务接入率 > 80%
- ⚠️ Routes 层接入率 > 80%
- ⚠️ Backend 目录接入率 > 80%

---

### Level 2: 事件驱动迁移（核心）

**目标**: 核心业务逻辑从"直接调用"改为"事件驱动"

#### 验收标准


| 业务场景  | 当前模式 | 目标模式 | 优先级 |
| ----- | ---- | ---- | --- |
| 发货单创建 | 直接调用 | 事件驱动 | P0  |
| 产品管理  | 直接调用 | 事件驱动 | P0  |
| 订单处理  | 直接调用 | 事件驱动 | P0  |
| 库存扣减  | 直接调用 | 事件驱动 | P1  |
| 打印服务  | 直接调用 | 事件驱动 | P1  |
| 客户管理  | 直接调用 | 事件驱动 | P2  |


#### 技术实现

**迁移前** (直接调用):

```python
class ShipmentAppService:
    def create_shipment(self, data):
        # 1. 直接操作数据库
        shipment = self.repository.create(data)
        
        # 2. 直接调用规则引擎
        violations = self.rules_engine.validate(data)
        if not violations.is_valid:
            raise Exception("验证失败")
        
        # 3. 直接调用打印服务
        self.print_service.print(shipment)
        
        return shipment
```

**迁移后** (事件驱动):

```python
class ShipmentAppService:
    async def create_shipment(self, data):
        # 1. 发布创建事件
        event = ShipmentCreatedEvent(payload=data)
        result = await publish_event(event)
        
        # 2. 等待异步处理完成
        # - ShipmentDomain 处理验证
        # - InventoryDomain 扣减库存
        # - PrintDomain 打印单据
        
        return result
```

#### 事件链示例

```
ShipmentCreated (发布)
  ↓
  ├─→ ShipmentValidated (Domain 处理)
  ├─→ InventoryDeducted (触发库存扣减)
  ├─→ ShipmentPrinted (触发打印)
  └─→ CustomerNotified (通知客户)
```

#### 完成标志

- ✅ P0 优先级 3 个场景完成事件驱动改造
- ✅ P1 优先级 2 个场景完成事件驱动改造
- ✅ 核心业务事件链完整、可追踪
- ✅ 性能指标优于或等于原实现

---

### Level 3: 领域模型迁移（深度）

**目标**: 业务规则从"应用层"下沉到"领域层"

#### 验收标准


| 领域服务                | 当前状态 | 目标状态            | 优先级 |
| ------------------- | ---- | --------------- | --- |
| ShipmentRulesEngine | 应用层  | NeuroDomain     | P0  |
| PricingEngine       | 应用层  | NeuroDomain     | P0  |
| InventoryService    | 应用层  | InventoryDomain | P1  |
| ConversationService | 应用层  | AIDomain        | P1  |
| OCRService          | 应用层  | OCRDomain       | P2  |


#### 技术实现

**迁移前** (贫血模型):

```python
# app/domain/entities/shipment.py
class Shipment:
    def __init__(self, id, status, amount):
        self.id = id
        self.status = status  # 公有字段，可随意修改
        self.amount = amount
```

**迁移后** (富血模型):

```python
# app/domain/aggregates/shipment.py
class Shipment(AggregateRoot):
    def __init__(self, id, status, amount):
        self._id = id
        self._status = ShipmentStatus.PENDING
        self._amount = Money(amount)
        self._events = []
    
    def confirm(self):
        """领域行为：确认发货单"""
        if self._status != ShipmentStatus.PENDING:
            raise DomainException("只有待确认的发货单才能确认")
        self._status = ShipmentStatus.CONFIRMED
        self._events.append(ShipmentConfirmedEvent(self._id))
    
    def cancel(self, reason: str):
        """领域行为：取消发货单"""
        if self._status not in [ShipmentStatus.PENDING, ShipmentStatus.CONFIRMED]:
            raise DomainException("无法取消已完成的发货单")
        self._status = ShipmentStatus.CANCELLED
        self._events.append(ShipmentCancelledEvent(self._id, reason))
```

#### 完成标志

- ✅ 核心领域对象有明确的领域行为
- ✅ 业务规则封装在领域层，不在应用层
- ✅ 领域对象发布领域事件
- ✅ 应用层只负责编排，不包含业务规则

---

### Level 4: 可靠性机制（生产级）

**目标**: 达到生产级可靠性标准

#### 验收标准


| 机制   | 当前状态         | 目标状态   | 优先级 |
| ---- | ------------ | ------ | --- |
| 事件重试 | NeuroBus 已实现 | 全链路启用  | P0  |
| 死信队列 | NeuroBus 已实现 | 全链路启用  | P0  |
| 事件去重 | NeuroBus 已实现 | 全链路启用  | P0  |
| 链路追踪 | 已实现          | 全链路启用  | P1  |
| 性能监控 | 部分实现         | 完整监控面板 | P1  |
| 告警机制 | 未实现          | 完整告警规则 | P2  |


#### 技术实现

**重试机制**:

```python
# app/neuro_bus/retry_handler.py
class RetryHandler:
    async def retry_with_backoff(self, event: NeuroEvent, handler: Callable):
        for attempt in range(self.max_retries):
            try:
                return await handler(event)
            except Exception as e:
                if attempt == self.max_retries - 1:
                    await self.send_to_dead_letter(event, e)
                    raise
                await asyncio.sleep(self.backoff_factor ** attempt)
```

**死信队列**:

```python
# app/neuro_bus/dead_letter_queue.py
class DeadLetterQueue:
    def add(self, event: NeuroEvent, error: Exception):
        # 保存到数据库，供后续分析和重试
        self.repository.save(DeadLetterEvent(
            event_type=event.event_type,
            payload=event.payload,
            error=str(error),
            failed_at=datetime.now()
        ))
```

#### 完成标志

- ✅ 所有事件处理器启用重试机制
- ✅ 失败事件自动进入死信队列
- ✅ 完整的链路追踪（HTTP → App → Service → Domain）
- ✅ 实时监控面板（事件处理延迟、成功率）
- ✅ 告警规则（失败率 > 5% 告警）

---

## 🎯 完整迁移的量化指标

### 综合评分卡


| 维度                | 权重   | 目标值  | 当前值   | 得分             |
| ----------------- | ---- | ---- | ----- | -------------- |
| **Level 1: 观测层**  | 25%  | 100% | 79.0% | 19.8/25        |
| **Level 2: 事件驱动** | 30%  | 80%  | 20%   | 6.0/30         |
| **Level 3: 领域模型** | 25%  | 80%  | 10%   | 2.5/25         |
| **Level 4: 可靠性**  | 20%  | 100% | 60%   | 12.0/20        |
| **总分**            | 100% | -    | -     | **40.3/100** ❌ |


### 完整迁移的定义

**完整迁移** = Level 1 (100%) + Level 2 (80%) + Level 3 (80%) + Level 4 (100%)

**当前进度**: 40.3% （刚过起步阶段）

---

## 📊 各层次完成度详细标准

### Level 1: 观测层（当前 79%）

**完成标准** (需达到 100%):

1. ✅ **Application 层** (100% - 已完成)
  - 21 个 AppService 全部使用 `instrument_application_service_class`
  - 所有方法调用自动追踪（start/end/error）
  - 性能指标自动采集（duration_ms）
  - 错误自动上报
2. ⚠️ **Services 层** (12.7% - 待完成)
  - 40+ 个 Services 使用 `instrument_service_layer_class`
  - 核心服务优先接入（P0: 5 个）
  - 全部服务接入（P2: 40+ 个）
3. ⚠️ **Routes 层** (42.9% - 待完成)
  - FastAPI 主入口中间件（已完成）
  - backend/http_app.py 接入
  - backend/routers/xcagi_compat.py 接入
  - backend/template_api.py 接入
4. ⚠️ **Backend 层** (0% - 待完成)
  - backend 目录所有路由文件接入
  - 兼容层 API 可观测

**完成标志**: 所有层次接入率 ≥ 80%

---

### Level 2: 事件驱动（当前 20%）

**完成标准** (需达到 80%):

1. ⚠️ **P0 场景** (0% - 待完成)
  - ShipmentAppService 事件驱动改造
  - ProductAppService 事件驱动改造
  - OrderAppService 事件驱动改造
2. ⚠️ **P1 场景** (0% - 待完成)
  - InventoryService 事件驱动改造
  - PrintService 事件驱动改造
3. ⚠️ **P2 场景** (0% - 待完成)
  - CustomerService 事件驱动改造
  - 其他场景

**事件链完整性检查**:

```python
# 完整的事件链示例
ShipmentCreated 
  → ShipmentValidated (验证通过)
  → InventoryDeducted (库存扣减)
  → ShipmentPrinted (打印单据)
  → CustomerNotified (通知客户)
```

**完成标志**:

- ✅ P0 场景 100% 完成
- ✅ P1 场景 100% 完成
- ✅ P2 场景 ≥ 50% 完成
- ✅ 事件链完整、可追踪

---

### Level 3: 领域模型（当前 10%）

**完成标准** (需达到 80%):

1. ⚠️ **领域对象重构**
  - Shipment 聚合根（富血模型）
  - Product 聚合根（富血模型）
  - Order 聚合根（富血模型）
  - Customer 聚合根（富血模型）
2. ⚠️ **领域服务下沉**
  - ShipmentRulesEngine → ShipmentNeuroDomain
  - PricingEngine → ProductNeuroDomain
  - InventoryService → InventoryNeuroDomain
3. ⚠️ **业务规则封装**
  - 验证规则在领域层
  - 状态转换在领域层
  - 领域事件在领域层发布

**完成标志**:

- ✅ 核心聚合根 100% 富血模型化
- ✅ 领域服务 80% 下沉到 NeuroDomain
- ✅ 应用层不包含业务规则（只负责编排）

---

### Level 4: 可靠性（当前 60%）

**完成标准** (需达到 100%):

1. ✅ **事件重试** (80%)
  - NeuroBus 实现重试机制
  - 所有事件处理器启用重试
  - 重试策略可配置
2. ✅ **死信队列** (80%)
  - NeuroBus 实现死信队列
  - 失败事件自动进入死信队列
  - 死信事件可查询、可重试
3. ✅ **事件去重** (100%)
  - NeuroBus 实现去重机制
  - 基于 event_id 去重
  - 幂等性保证
4. ⚠️ **链路追踪** (50%)
  - 实现 neuro_trace_app_service_call
  - 实现 neuro_trace_service_call
  - 完整链路可视化
  - 性能瓶颈定位工具
5. ⚠️ **监控告警** (20%)
  - 基础指标采集
  - 监控面板（Grafana 等）
  - 告警规则配置
  - 告警通知（邮件/钉钉/微信）

**完成标志**:

- ✅ 重试、死信、去重 100% 启用
- ✅ 完整链路追踪 100% 覆盖
- ✅ 监控面板上线
- ✅ 告警机制生效

---

## 🎖️ 迁移完成度认证

### 青铜级（当前状态）

**标准**: Level 1 ≥ 60%

**权益**:

- ✅ 基础可观测性
- ✅ 性能追踪
- ✅ 错误上报

**当前进度**: 79% ✅ **已达标**

---

### 白银级

**标准**:

- Level 1 ≥ 90%
- Level 2 ≥ 40%
- Level 4 ≥ 70%

**权益**:

- ✅ 完整可观测性
- ✅ 部分事件驱动
- ✅ 生产级可靠性

**当前进度**: 未达标

---

### 黄金级

**标准**:

- Level 1 ≥ 95%
- Level 2 ≥ 70%
- Level 3 ≥ 60%
- Level 4 ≥ 90%

**权益**:

- ✅ 完整事件驱动架构
- ✅ 领域模型完善
- ✅ 高可靠性保障

**当前进度**: 未达标

---

### 钻石级（完整迁移）

**标准**:

- Level 1 ≥ 100%
- Level 2 ≥ 80%
- Level 3 ≥ 80%
- Level 4 ≥ 100%

**权益**:

- ✅ Neuro-DDD 完整落地
- ✅ 架构与业务完全融合
- ✅ 行业领先实践

**当前进度**: 40.3% ❌ **距离完整迁移还有 59.7%**

---

## 📈 迁移路线图

### 阶段 1: 补全观测层（2 周）

**目标**: Level 1 ≥ 90%

**任务**:

1. Services 层接入率 12.7% → 60% (2 周)
2. Routes 层接入率 42.9% → 80% (1 周)
3. Backend 层接入率 0% → 60% (1 周)

**验收**:

- ✅ Services 层 Neuro 调用 > 30 次
- ✅ Routes 层 Neuro 调用 > 20 次
- ✅ Backend 层 Neuro 调用 > 0

---

### 阶段 2: 事件驱动试点（3 周）

**目标**: Level 2 ≥ 40%

**任务**:

1. ShipmentAppService 事件驱动改造 (1 周)
2. ProductAppService 事件驱动改造 (1 周)
3. 性能对比与优化 (1 周)

**验收**:

- ✅ 2 个完整事件驱动用例
- ✅ 性能优于或等于原实现
- ✅ 事件链完整可追踪

---

### 阶段 3: 领域模型重构（4 周）

**目标**: Level 3 ≥ 60%

**任务**:

1. Shipment 聚合根重构 (1 周)
2. Product 聚合根重构 (1 周)
3. 领域服务下沉 (2 周)

**验收**:

- ✅ 4 个核心聚合根富血模型化
- ✅ 应用层业务规则下沉到领域层
- ✅ 领域事件完整发布

---

### 阶段 4: 全面推广（6 周）

**目标**: Level 2 ≥ 80%, Level 3 ≥ 80%

**任务**:

1. 批量迁移核心业务场景 (3 周)
2. 建立架构审查机制 (1 周)
3. 团队培训与最佳实践 (2 周)

**验收**:

- ✅ 核心业务 80% 事件驱动化
- ✅ 领域模型完善
- ✅ 团队形成使用习惯

---

### 阶段 5: 生产级可靠性（2 周）

**目标**: Level 4 ≥ 100%

**任务**:

1. 监控面板上线 (1 周)
2. 告警机制配置 (1 周)

**验收**:

- ✅ 完整监控面板
- ✅ 告警规则生效
- ✅ 7 天稳定运行

---

## 🎯 总结：什么是完整迁移？

### 一句话定义

**完整迁移** = 所有代码可观测 + 核心业务事件驱动 + 领域模型完善 + 生产级可靠性

### 量化指标


| 层次            | 目标值       | 权重       |
| ------------- | --------- | -------- |
| Level 1: 观测层  | 100%      | 25%      |
| Level 2: 事件驱动 | 80%       | 30%      |
| Level 3: 领域模型 | 80%       | 25%      |
| Level 4: 可靠性  | 100%      | 20%      |
| **综合**        | **≥ 90%** | **100%** |


### 关键标志

✅ **完整迁移完成的标志**:

1. **新开发者无需学习"两套架构"**
  - 只有一种开发模式：Neuro-DDD
  - 没有"老代码"和"新代码"之分
2. **核心业务逻辑通过事件驱动**
  - 发货单创建 → 发布事件 → 异步处理
  - 不是直接调用 Services
3. **业务规则在领域层**
  - 应用层只负责编排
  - 领域层包含所有业务规则
4. **生产级可靠性**
  - 完整的监控、告警、重试机制
  - 7x24 小时稳定运行

### 当前状态

**综合完成度**: 40.3% （青铜级）

**距离完整迁移**:

- ⚠️ 还需完成 59.7% 的工作
- ⚠️ 预计需要 15-17 周（3-4 个月）
- ⚠️ 需要持续投入和团队配合

---

**制定人**: Chief Architect  
**审核人**: Tech Team  
**下次复审**: 2026-05-02 (2 周后)