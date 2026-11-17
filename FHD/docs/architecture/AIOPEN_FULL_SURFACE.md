# AIOPEN 全景开放（全知全能）技术方案

> 状态：待评审（Proposal）
> 范围：AIOPEN 开放面从「10 个手写工具 + 路径前缀白名单」升级为「可检索的系统地图 + 自动生成的受控能力 + 可回放的操作证据」。
> 不在本文范围：Mod 开发规范、员工包运行时、发布流水线。
>
> 本文不替代 [`docs/aiopen.md`](../aiopen.md)：那份文档面向**接入方**（如何配置 MCP、如何拿 Key），
> 生命周期随客户端变化；本文面向**实现与评审**（能力模型、权限矩阵、接口与迁移），
> 生命周期随服务端契约变化。两者互相链接，不重复内容。

## 1. 目标与非目标

### 1.1 目标

外部 AI 连接 AIOPEN 后，应当依次获得三种能力：

| 能力 | 定义 | 验收方式 |
|---|---|---|
| **知** | 能查到系统里存在哪些能力、实体、字段、页面、员工包与权限范围 | 任意业务域都能通过 `knowledge_search` 检索到对应 operation，并能读到完整语义卡片 |
| **懂** | 每个能力带使用时机、副作用、前置条件、返回形状与示例 | 目录中 operation 的语义覆盖率可度量，未覆盖项进入待办 |
| **做** | 能以最小权限执行，危险动作进入审批，执行留痕且可回放 | 越权调用被拒绝并记录；危险动作必须产生审批单；每次调用可从审计表还原 |

### 1.2 非目标（明确不做）

1. **不做跨租户全能**：任何工具、资源、检索结果都按调用主体（租户 + 用户）过滤，不提供绕过隔离的入口。
2. **不做无审批的危险动作**：删除、退款、发布、授权变更、代登录等必须走既有审批中心，AI 只能发起。
3. **不做「所有 REST 全量镜像成工具」**：自动生成只作为目录来源，对外暴露面必须经过精选层（见 3.3）。
4. **不记录业务载荷**：审计只存路径模板、参数指纹与结果状态，不存字段值（与 CodeQL 4021 修复口径一致）。

## 2. 现状与差距

### 2.1 现状

| 组件 | 位置 | 现状 |
|---|---|---|
| 工具定义 | [`definitions.py`](../../app/application/aiopen/definitions.py) | 10 个手写工具：`api_catalog` / `api_call` / `chat` / `capability_loop` / `ui_*` |
| 白名单 | 同上 `CAPABILITY_ROUTE_PREFIXES` | 26 个路径前缀，面板布尔开关 |
| 路由策略 | [`route_policy.py`](../../app/application/aiopen/route_policy.py) | 前缀匹配，无方法级、无读写分级 |
| 工具分发 | [`dispatch.py`](../../app/application/aiopen/dispatch.py) | 名称匹配 → 线程执行 / 光标派发 |
| 鉴权 | [`runtime.py`](../../app/application/aiopen/runtime.py) | 单一 `X-AIOPEN-Key`，无主体、无 scope、无过期 |
| 计量 | [`usage.py`](../../app/application/aiopen/usage.py) | `usage.jsonl` 记录调用，无主体与操作回放 |
| 前端操控 | [`useAiOpenCursor.ts`](../../frontend/src/composables/useAiOpenCursor.ts) | CSS selector + 5 个动作，无稳定引用、无等待/断言 |
| 协议 | [`service.py`](../../app/application/aiopen/service.py) | MCP 仅 `initialize` / `tools/list` / `tools/call` / `ping`，无 Resources / Prompts |

### 2.2 差距（按影响排序）

1. **没有数据面**：MCP 无 Resources，AI 只能靠工具调用拼结果，无法「先读全局再动手」。
2. **目录是手写的**：新增业务域必须改代码，开放面永远滞后于真实路由。
3. **无边界的万能代理**：`api_call` 可发任意方法，安全边界只剩下前缀布尔值。
4. **UI 能力停在「能点」**：无稳定元素引用、无等待与断言，复杂页面流程不可靠。
5. **无法度量「全」**：没有覆盖率指标，无法回答「到底开放了多少」。
6. **鉴权无法表达最小权限**：一把全局 Key 等于全量授权。

## 3. 目标架构

```
┌──────────────────────────────────────────────────────────────┐
│ 接入层  MCP Streamable HTTP / REST                            │
│ principal(tenant,user) · scopes · 过期 · 审计主体              │
├──────────────────────────────────────────────────────────────┤
│ 知识层  系统地图（operations / schema / pages / employees）     │
│         语义 overlay · knowledge_search · MCP Resources        │
├──────────────────────────────────────────────────────────────┤
│ 执行层  生成式 operation 工具（工具集 / 风险分级 / 审批桥）      │
│         api_call 逃生舱（scope 内 + 全量审计）                  │
│         UI ref 通道（快照 / 点击 / 输入 / 等待 / 断言 / 截图）    │
│         复合能力（行动手册，人工审核入库）                       │
├──────────────────────────────────────────────────────────────┤
│ 观测层  调用台账 · 覆盖度指标 · 失败聚类 → 反向补全              │
└──────────────────────────────────────────────────────────────┘
```

### 3.1 接入层

**主体解析**：每个 Key 绑定 `key_id / tenant_id / subject / scopes[] / expires_at`。
运行时 Key 与 `AIOPEN_API_KEY` 环境变量并存，后者作为兼容入口，默认授予 `catalog:read` + 只读业务 scope。

**MCP 能力扩充**（在现有 JSON-RPC 方法上新增）：

| 方法 | 用途 |
|---|---|
| `resources/list` | 列出可读资源（目录、实体字典、页面说明） |
| `resources/templates/list` | 列出参数化资源模板 |
| `resources/read` | 读取单个资源 URI |
| `prompts/list` / `prompts/get` | 提供「开单」「对账」等常用流程提示模板（可选，P3） |

**协议版本**：维持 `2024-11-05` 与 `2025-03-26` 双声明，新增能力通过 `initialize.result.capabilities` 声明 `resources`，旧客户端不受影响。

**鉴权路线**：短期 Key + scope + 过期；中期以 OAuth 2.1（PKCE + Resource Indicator）替换长期静态 Key，MCP 规范要求见参考项。

### 3.2 知识层（知 + 懂）

**目录构建器**（新增 `app/application/aiopen/catalog_builder.py`）：

- 输入：FastAPI 应用的路由表（`app.routes`）与其 OpenAPI schema。
- 输出：`OperationCatalogEntry[]`，每条包含：

```json
{
  "operation_id": "orders.create",
  "tool_name": "orders_create",
  "method": "POST",
  "path": "/api/orders",
  "tags": ["orders"],
  "summary": "创建订单",
  "risk": "write",
  "scope": "write:orders",
  "toolset": "orders",
  "params": [{"name": "body", "in": "body", "schema_ref": "OrderCreate"}],
  "response_schema_ref": "OrderOut",
  "deprecated": false
}
```

**风险分级规则**（确定性默认值，overlay 可覆盖）：

| 规则 | 风险 |
|---|---|
| `GET` / `HEAD` 且无路径参数 | `read` |
| `GET` 带路径参数 | `read` |
| `POST` / `PUT` / `PATCH` | `write` |
| `DELETE`、路径含 `batch` / `bulk` / `refund` / `publish` / `grant` / `revoke` / `reset` / `impersonate` | `danger` |
| 路径前缀 `/api/aiopen/panel`、`/api/keys`、`/api/admin/`、`/internal/` | `exclude`（永不暴露） |

**语义 overlay**（新增 `app/application/aiopen/overlay/*.yaml`，与代码同仓评审）：

```yaml
- operation_id: orders.create
  when_to_use: "客户确认商品与数量后创建订单。"
  side_effects: ["写订单表", "触发库存预占", "产生审计事件"]
  preconditions: ["客户已建档", "商品已上架"]
  returns: "订单号与待支付状态"
  examples:
    - args: { customer_id: "C001", items: [{ sku: "A1", qty: 2 }] }
      note: "标准单品下单"
  related: [orders.pay, print.job.create]
```

overlay 是「懂」的唯一增量来源；构建器负责「有什么」，overlay 负责「怎么用」。

**MCP Resources**（新增 `app/application/aiopen/resources.py`，URI 路由器）：

| URI | 内容 |
|---|---|
| `xcmax://catalog/operations` | operation 全量目录（可分页参数） |
| `xcmax://catalog/operation/{operation_id}` | 单个 operation 卡片（含 overlay 合并结果） |
| `xcmax://catalog/schema/{entity}` | 实体字段字典（类型、枚举、必填、关联） |
| `xcmax://catalog/page/{route}` | 页面能力：路由、关键元素语义、可用操作（需前端路由单一事实源，P3 实现） |
| `xcmax://catalog/employee/{employee_id}` | 员工包能力清单（来自 `employee_config_v2`） |
| `xcmax://catalog/permissions` | 当前主体的 scope 与可见工具集 |

**检索工具**（新增 MCP tool `knowledge_search`）：

```json
{
  "name": "knowledge_search",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {"type": "string"},
      "kind": {"type": "string", "enum": ["operation", "schema", "page", "employee", "all"], "default": "all"},
      "limit": {"type": "integer", "default": 10}
    },
    "required": ["query"]
  }
}
```

实现：名称/描述/参数名/overlay 文本的加权匹配。P0 复用已锁定依赖 scikit-learn 的
TF-IDF（字符 n-gram，兼容中文）做余弦相似度，索引按目录签名缓存；**不一次返回全量目录**。

### 3.3 执行层（做）

**生成式工具与精选层**：

- 生成：每个非 `exclude` operation 生成一个工具，名称 `{domain}_{action}`，schema 来自 OpenAPI。
- 精选：`default` 工具集（对应 GitHub MCP 的默认集）只放高频只读与少量安全写操作；其余按需开启。
- 工具集：按 tags 分组（`orders` / `products` / `knowledge` / `employees` / `ui` / `admin`），可在 Key 上收窄。

**`api_call` 保留为逃生舱**：可调任意 scope 内路径，但受方法白名单、scope 校验与全量审计约束，且不可调用 `exclude` 路由。

**危险动作审批桥**（新增 `app/application/aiopen/approval_bridge.py`）：

```
AI 调 danger 工具 → 生成审批单（复用审批中心） → 返回
{"success": false, "code": "APPROVAL_REQUIRED", "approval_id": "..."}
审批通过后，AI 用 approval_id 重放同一调用 → 执行并记录审批来源
```

**UI 通道升级**（改动 `useAiOpenCursor.ts` + `cursor_hub.py`）：

| 动作 | 现状 | 目标 |
|---|---|---|
| `snapshot` | CSS selector + 文本 + 位置 | 无障碍树 + 稳定 `ref`（如 `e12`），附带角色/名称/状态 |
| `click` / `type` | selector 或文本 | 优先 `ref`，保留 selector 作为兜底 |
| 新增 | — | `ui_wait`（元素/文本/网络空闲）、`ui_verify`（可见/文本/值断言）、`ui_select`、`ui_upload`、`ui_screenshot`、`ui_press_key`、`ui_scroll_into_view` |
| 审计 | 无 | 每次动作记录 `session_id` + `ref` + 动作 + 结果，可回放 |

**复合能力**：把多步流程（如「建单 → 审核 → 打印」）声明为高阶工具，来源是 AI 起草 + 人工审核入库的 YAML，运行时可被逐条调用与回滚。

### 3.4 观测层

**审计记录**（扩展现有 `usage.jsonl`）：

```json
{
  "ts": "2026-11-17T10:00:00Z",
  "key_id": "k_01",
  "principal": "user:u_123",
  "tenant_id": "t_9",
  "tool": "orders_create",
  "operation_id": "orders.create",
  "method": "POST",
  "path_template": "/api/orders",
  "scope": "write:orders",
  "risk": "write",
  "status": 200,
  "latency_ms": 132,
  "args_hash": "sha256:...",
  "approval_id": null,
  "session_id": null
}
```

**覆盖度指标**（新增 `GET /api/aiopen/coverage`）：

- `exposed_ratio`：非 exclude operation 中被工具化的比例
- `described_ratio`：有 overlay 语义的比例
- `called_ratio`：近 30 天被调用过的比例
- `ui_route_coverage`：前端路由中具备可操作语义的比例
- `denied_calls` / `approval_required` / `failed_calls` 计数

**闭环**：失败调用按 `operation_id + status` 聚类，自动产出待办：缺语义、缺工具、缺 scope、UI 无 ref。

## 4. 权限矩阵

scope 形式：`<级别>:<域>`，另有两个控制面 scope。

| 操作类型 | 所需 scope | 只读 Key | 标准 Key | 管理员 Key |
|---|---|---|---|---|
| 读目录 / 资源 | `catalog:read` | ✓ | ✓ | ✓ |
| `GET` 业务数据 | `read:<domain>` | ✓ | ✓ | ✓ |
| `POST/PUT/PATCH` | `write:<domain>` | ✗ | ✓ | ✓ |
| `DELETE` / 批量 / 退款 / 发布 | `danger:<domain>` + 审批单 | ✗ | ✗ | ✓ + 审批 |
| UI 操控 | `ui:control` | ✗ | ✓（远程操控开关开） | ✓ |
| 目录/Key 管理 | `admin:catalog` | ✗ | ✗ | ✓ |

补充规则：

1. 只读 Key 即使显式点名写工具也在分发前剔除（对应 GitHub `--read-only` 优先语义）。
2. 所有数据查询在路由层叠加租户过滤，AIOPEN 不提供关闭开关。
3. `exclude` 路由不出现在目录、不可调用，仅管理员面板可见其存在。

## 5. 接口清单

### 5.1 MCP

| 名称 | 类型 | 说明 | 阶段 |
|---|---|---|---|
| `knowledge_search` | tool | 目录检索 | P0 |
| `operation_describe` | tool | 单 operation 语义卡片 | P0 |
| `api_catalog` | tool | 保留，改为返回工具集摘要 + 分页，不再是全量清单 | P0 |
| `api_call` | tool | 保留，加 scope/风险校验 | P0 |
| `chat` / `capability_loop` / `ui_sessions` | tool | 保留 | — |
| `xcmax://catalog/*` | resource | 见 3.2 | P0 |
| `<domain>_<action>` | tool | 自动生成的 operation 工具 | P1 |
| `ui_wait` / `ui_verify` / `ui_select` / `ui_upload` / `ui_screenshot` / `ui_press_key` | tool | UI 能力补齐 | P2 |
| `workflow_*` | tool | 复合能力 | P3 |

### 5.2 REST

| 端点 | 说明 |
|---|---|
| `GET /api/aiopen/catalog/operations?q=&toolset=&risk=&limit=&offset=` | 目录分页与过滤 |
| `GET /api/aiopen/catalog/operations/{operation_id}` | 语义卡片 |
| `GET /api/aiopen/catalog/schema/{entity}` | 实体字段字典 |
| `GET /api/aiopen/coverage` | 覆盖度指标 |
| `GET /api/aiopen/audit?tool=&principal=&since=` | 审计查询（LAN 门禁内） |
| `POST /api/aiopen/keys` | 创建带 scope 与过期的 Key（LAN 门禁内） |

### 5.3 内部模块

```
app/application/aiopen/
├── catalog_builder.py   # 路由/OpenAPI → OperationCatalogEntry
├── overlay/             # 语义 YAML（与代码同仓评审）
├── resources.py         # xcmax:// URI 路由
├── policy.py            # scope + 风险 + 租户校验
├── approval_bridge.py   # 危险动作 → 审批中心
├── tools_generated.py   # 生成式工具注册与 schema 下发
├── audit.py             # 结构化审计（扩展 usage.py）
└── coverage.py          # 覆盖度指标
```

现有 `definitions.py` 退化为「内置工具 + 精选默认集声明」，不再承担全量目录职责。

## 6. 分期与验收

### P0 知先行（无写风险）

- 交付：`catalog_builder`、`resources.py`、`knowledge_search`、`operation_describe`、Key scope 骨架、只读强制。
- 验收：
  - 目录 operation 数 > 0 且每条都有 `risk` 与 `scope`；
  - `resources/read` 可读取 5 类 URI；
  - 只读 Key 调用写工具返回 `SCOPE_DENIED`；
  - `coverage` 返回 `described_ratio`；
  - 单测：`tests/test_aiopen_catalog.py`、`tests/test_aiopen_resources.py`。

### P1 做（受控执行）

- 交付：生成式工具、default 工具集、`policy` 校验、审批桥、审计扩展。
- 验收：
  - 生成工具数 = 非 exclude operation 数；
  - 危险工具调用返回 `APPROVAL_REQUIRED` 并生成审批单；
  - 每次调用产生一条不含量值的审计记录；
  - 旧 10 个工具行为不变（回归测试通过）。

### P2 UI 全能

- 交付：a11y 快照 + ref、`ui_wait`/`ui_verify`/`ui_select`/`ui_upload`/`ui_screenshot`、动作审计。
- 验收：
  - 同一页面连续两次快照的 ref 稳定；
  - 表单填写 + 提交在无 selector 依赖下完成；
  - 动作可按 session 回放。

### P3 懂与闭环

- 交付：overlay 覆盖、复合能力、覆盖度仪表盘、失败聚类待办。
- 验收：
  - `described_ratio` 达到约定门槛（建议 ≥ 80%）；
  - 至少 3 个复合能力经人工审核入库并可执行；
  - 失败聚类能自动生成待办条目。

## 7. 兼容与回滚

- 开关：`AIOPEN_SURFACE_V2=1` 启用新目录与生成工具；关闭时回到现有 10 工具，行为完全一致。
- 目录只读：P0 阶段新能力均为只读，出问题可直接关闭开关，不影响业务写入路径。
- 数据兼容：`usage.jsonl` 新字段向后兼容，旧记录按缺失处理。
- 权限回滚：scope 校验失败一律拒绝（fail-closed），不使用「默认放行」兜底。

## 8. 风险

| 风险 | 影响 | 应对 |
|---|---|---|
| 目录自动生成把内部路由暴露 | 越权面扩大 | `exclude` 规则先于生成执行；目录测试断言白名单外不可见 |
| 工具数量过多导致模型选错 | 调用准确率下降 | default 工具集 + `knowledge_search` 按需发现 |
| 语义 overlay 维护成本 | 覆盖率上不去 | 覆盖度看板 + 失败聚类驱动补齐，不追求一次全量 |
| UI ref 与前端组件更新脱节 | 操控失败 | ref 由运行时快照生成，不做静态映射；失败回退 selector |
| 审批桥重复发起 | 重复执行 | `approval_id` 幂等，同单号同参数只执行一次 |

## 9. 参考实现对照

| 参考 | 采用的部分 | 不采用的部分 |
|---|---|---|
| GitHub MCP Server | 工具集分组、`read-only` 优先、请求级收窄、Resources 随工具集提供 | 直接照搬其产品域划分 |
| Playwright MCP | a11y 快照 + ref、能力分组、危险能力单独暴露、trace 回放 | 以像素/坐标为主的视觉模式 |
| FastMCP OpenAPI Provider | 以路由表为事实源、RouteMap 式映射与排除、operationId 命名 | 全量 REST 直接镜像为工具 |
| Claude Tool Search / Composio Tool Router | 按需检索、单端点、托管鉴权、审计 | 第三方 SaaS 集成目录 |
| MCP 授权规范 | OAuth 2.1、scope、Resource Indicator、最小权限 | 立即全量替换现有 Key 机制 |
