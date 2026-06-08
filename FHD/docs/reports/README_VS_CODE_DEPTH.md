# README 概念 vs 代码：`pass` 分布与神经域实现深度（量化）

生成方式：对 `app/` 静态扫描（行数、`pass`、`@self.on`、事件类、导入关系）。**以当前仓库快照为准**。

## 1. 结论摘要

| 维度 | 观察 |
|------|------|
| README 叙事 | 强调 Neuro-DDD、多神经域、总线；根 `README.md` 已写明**以 `app/` 源码为准**。 |
| `pass` | `app/**/*.py` 中约 **252** 处独立行 `pass`；其中 **`app/domain/repositories/` 约占 30%**，多为 `Protocol`/`@abstractmethod` 的惯用写法，**不等于未实现**。 |
| 12 个 `NeuroDomain` 类 | 均在 `app/neuro_bus/register_all_neuro_domains.py` 注册；**厚度不均**（见下表）。 |
| `*_domain_handlers` | `app/neuro_bus/register_all_domains_complete.py` 中 `register_domain_handlers_only` 尝试注册 **14** 组处理器；**磁盘上仅存在 5 个** `*_domain_handlers.py`，其余在启动时 **ImportError 跳过**（见 §4）。 |
| CQRS | **出货相关**存在显式 `command` / `query` 实现文件；**非全库严格 CQRS**（见 §5）。 |

## 2. 十二个 `NeuroDomain` 与事件模型 / 处理器对照

**说明**

- **事件模型数**：对应 `app/neuro_bus/events/<领域>_events.py` 中以 `class …Event(` 声明的类型数量；`intent` / `safety` 无独立 `*_events.py`（意图多为字符串事件名 + `app/neuro_bus/events/base.py` 中的 `IntentEvent`）。
- **处理器模块**：`app/neuro_bus/domains/<stem>_domain_handlers.py`（`ai_service` → `ai_domain_handlers.py`）。
- **业务落点**：`application` 层委托（如 `get_*_application_service*`）为 **深**；仅用 `NeuroUnitOfWork` 等为 **中**；日志/指标/再发总线事件为 **浅**。

| NeuroDomain（`domain_name`） | 域模块行数 | `@self.on` 数 | 事件模型数（`*_events.py`） | 处理器文件存在 | 处理器行数 | 业务落点（粗分级） |
|-----------------------------|------------|----------------|-------------------------------|----------------|------------|-------------------|
| intent | 240 | 4 | 0（见上） | 否 | 0 | 浅（日志 + 指标 bump） |
| order | 109 | 3 | 9 | 否 | 0 | 浅（域内订阅为主） |
| inventory | 101 | 2 | 6 | **是** | 86 | **中**（`NeuroUnitOfWork`） |
| product | 97 | 1 | 6 | **是** | 311 | 浅（日志 + 总线联动） |
| customer | 99 | 2 | 6 | 否 | 0 | 浅 |
| ai_service | 135 | 2 | 6 | 否 | 0 | 浅 |
| wechat | 106 | 2 | 7 | 否 | 0 | 浅 |
| print | 111 | 2 | 6 | **是** | 71 | 浅（以日志为主） |
| ocr | 107 | 1 | 6 | **是** | 71 | 浅 |
| payment | 158 | 2 | 6 | 否 | 0 | 浅 |
| safety | 151 | 2 | 0 | 否 | 0 | 浅 |
| shipment | 82 | 7 | 7 | **是** | 243 | **深**（`get_shipment_application_service_core` 等） |

## 3. 全部领域事件文件（类型数量）

不含 `app/neuro_bus/events/base.py` 中的基类；仅统计各文件内 `class …Event(`。

| 文件 | 事件类型数 |
|------|------------|
| `order_events.py` | 9 |
| `auth_events.py` | 8 |
| `wechat_events.py` | 7 |
| `shipment_events.py` | 7 |
| `ai_events.py` | 6 |
| `conversation_events.py` | 6 |
| `customer_events.py` | 6 |
| `inventory_events.py` | 6 |
| `material_events.py` | 6 |
| `ocr_events.py` | 6 |
| `payment_events.py` | 6 |
| `print_events.py` | 6 |
| `product_events.py` | 6 |
| **合计（14 文件）** | **约 89** |

`Material` / `Conversation` 等有事件定义，但 **无对应 `NeuroDomain` 单例**于 `app/neuro_bus/register_all_neuro_domains.py`（与 README「12 域」叙事需对照理解）。

## 4. 启动时处理器注册：尝试 vs 实际文件

`register_domain_handlers_only`（`app/neuro_bus/register_all_domains_complete.py`）依次 `import` 下列注册函数；**模块不存在则 ImportError 并跳过**。

| 预期处理器模块 | 仓库内是否存在 |
|----------------|----------------|
| `product_domain_handlers` | 是 |
| `shipment_domain_handlers` | 是 |
| `order_domain_handlers` | **否** |
| `customer_domain_handlers` | **否** |
| `inventory_domain_handlers` | 是 |
| `payment_domain_handlers` | **否** |
| `ocr_domain_handlers` | 是 |
| `wechat_domain_handlers` | **否** |
| `print_domain_handlers` | 是 |
| `ai_domain_handlers` | **否** |
| `auth_domain_handlers` | **否** |
| `material_domain_handlers` | **否** |
| `conversation_domain_handlers` | **否** |

运行时入口：`app/neuro_bus/register_runtime.py`（`register_all_neuro_domains` + `register_domain_handlers_only`）。

## 5. CQRS 在代码中的落点（部分实现）

| 路径 | 角色 |
|------|------|
| `app/infrastructure/persistence/shipment_record_command_impl.py` | 写侧（命令） |
| `app/infrastructure/persistence/shipment_record_query_impl.py` | 读侧（查询） |
| `app/infrastructure/persistence/purchase_unit_query_impl.py` | 读侧（查询） |

其它聚合未见成对的 command/query 命名分裂；**不宜将全系统描述为已完成 CQRS**。

## 6. `pass` 在 `app/` 下的目录分布（约 252 处）

按 `Path.parts` 一级子目录归类（含 `@abstractmethod` 与 `except` 吞异常等所有单行 `pass`）。

| 目录桶 | `pass` 出现次数 | 涉及文件数 |
|--------|-----------------|------------|
| `app/domain/repositories/` | 75 | 6 |
| `app/infrastructure/` | 49 | 20 |
| `app/application/` | 25 | 15 |
| `app/neuro_bus/` | 24 | 15 |
| `app/fastapi_routes/` | 17 | 6 |
| `app/domain/`（除 repositories） | 6 | 5 |
| 其余 `app/*` | 56 | 40 |

**解读**：`domain/repositories` 集中度高，主要为**接口占位**；与「业务全为空实现」不是同一概念。

## 7. 复现命令（可选）

在项目根目录使用 Python 3.11+：

```bash
python -c "from pathlib import Path; import re; r=re.compile(r'^\\s+pass\\s*$', re.M); print(sum(len(r.findall(p.read_text(encoding='utf-8', errors='replace'))) for p in Path('app').rglob('*.py') if '__pycache__' not in p.parts))"
```

---

*报告生成日期：2026-04-21*
