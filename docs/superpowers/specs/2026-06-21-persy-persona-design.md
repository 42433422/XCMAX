# Persy Persona 系统设计文档

> **项目**：XCMAX（FHD 产品线）
> **目标**：为桌面端「智能对话」和手机端「小C助理」引入拟人化 persona 系统，通过 prompt 工程和模型选型调优，实现"根据用户使用风格自动适配人格"的体验。
> **日期**：2026-06-21
> **状态**：设计完成，待实现

---

## 1. 背景与目标

### 1.1 现状

| 维度 | 现状 |
|------|------|
| 桌面端「智能对话」 | Vue `ChatView.vue` + Electron 壳，Electron 只加载 Web，无独立对话逻辑 |
| 手机端「小C助理」 | Android `ChatScreen.kt`，**与桌面端共用同一后端端点** `/api/ai/chat/stream` |
| 主对话 system prompt | `app/services/conversation/api.py:449-461` — 通用"专业业务助手"，**无任何 persona/人格元素** |
| 小C助理客服通道 prompt | `app/fastapi_routes/mobile_api_extensions.py:1616` — 独立的"XCAGI 企业智能客服"prompt，走员工运行时（非主对话流） |
| 现有 persona 机制 | 仅 AI 员工体系有（`employee_config_v2.cognition.agent.role`：name/persona/tone/expertise），**主对话无 persona** |
| 未发现 | 任何"拟人化 / persy / 角色扮演"专用代码或文档 |

### 1.2 目标

1. **引入 persona 系统**：给主对话赋予可配置的人格，从"通用业务助手"升级为"有身份、有温度、懂用户的伙伴"
2. **自动推断用户偏好**：系统根据用户历史对话风格自动适配 persona，用户无感
3. **连续参数调节**：不用离散分类，用连续参数（0-1）动态调节 persona
4. **身份演进**：从"功能性管家"逐渐演变成"忠诚伙伴"
5. **两端同一人格**：桌面端和手机端共用同一 persona，后端一处改造两端生效
6. **前端零改动**：persona 在后端透明注入，桌面 Vue 和手机 Android 都不需要改

### 1.3 非目标

- 不做真正的模型 fine-tuning（只做 prompt + 模型选型调优）
- 不删除现有通用业务助手 prompt（作为 fallback 保留）
- 不做离散 persona 分类（如"专业型/亲切型"二选一）
- 不做用户手动设置 persona（完全自动推断，用户无感）

---

## 2. 整体架构

### 2.1 改造范围（一处改造，两端生效）

```
┌─────────────────────────────────────────────────────────────┐
│  桌面「智能对话」(ChatView.vue)  ──┐                         │
│                                     ├──→ /api/ai/chat/stream │
│  手机「小C助理」(ChatScreen.kt)  ──┘     （共用同一后端）     │
└─────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────┐
│  后端：app/services/conversation/                            │
│                                                              │
│  现状：api.py:449 硬编码 base_prompt（通用业务助手）          │
│                                                              │
│  改造后：                                                     │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐ │
│  │ Persona推断  │→│ Prompt生成器 │→│ 模型参数映射器    │ │
│  │ (三层管线)   │   │ (参数→文本)  │   │ (参数→temperature)│ │
│  └──────────────┘   └──────────────┘   └──────────────────┘ │
│         │                                          │         │
│         ▼                                          ▼         │
│  ┌──────────────┐                        ┌──────────────────┐│
│  │ 用户画像存储 │                        │ LLM Client (复用) ││
│  │ (Redis+DB)   │                        │ 现有 infrastructure││
│  └──────────────┘                        └──────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

### 2.2 核心改造点

| 改造点 | 位置 | 动作 |
|--------|------|------|
| 主对话 system prompt | `app/services/conversation/api.py:449-461` | 从硬编码改为动态生成（persona 参数驱动） |
| persona 推断服务 | 新增 `app/services/persona/` | 三层推断管线 |
| 用户画像持久化 | 新增 `app/infrastructure/persona/` | Redis（热数据）+ DB（冷数据） |
| prompt 生成器 | 新增 `app/services/persona/prompt_builder.py` | 参数→prompt 片段 |
| 模型参数映射 | 扩展 `app/infrastructure/llm/invoke.py` | persona 参数→temperature 等 |
| persona 领域模型 | 新增 `app/domain/persona/` | 值对象/聚合根 |
| Neuro Bus 事件 | 新增 `app/neuro_bus/events/persona_event.py` | persona 领域事件 |
| 前端 | **零改动** | 两端前端都不需要改（后端透明注入） |

### 2.3 关键原则

- **前端零改动**：桌面 Vue 和手机 Android 都不需要动，persona 在后端透明注入
- **复用现有基础设施**：LLM Client、Redis、Neuro Bus 都复用，不重复造轮子
- **旧 prompt 作为 fallback**：persona 系统异常时回退到现有通用业务助手 prompt
- **同步路径轻量，异步路径重量**：persona 推断和 prompt 生成在同步路径（必须快），画像更新和 L2/L3 推断在异步路径（不阻塞响应）

---

## 3. Persona 数据模型

persona 系统由**三个正交维度**组成，共同驱动 prompt 生成：

### 3.1 三维度概览

| 维度 | 含义 | 决定方式 | 更新频率 |
|------|------|---------|---------|
| **身份（identity）** | "我是谁"——考勤管家？发货管家？忠诚伙伴？ | 初始由企业入驻行业决定，随业务使用漂移，随关系深度演进 | 低频 |
| **关系深度（rapport）** | "我们有多熟"——0.0(陌生) ~ 1.0(忠诚) | 互动轮数 50% + 业务深度 30% + 情感信号 20% | 每轮对话后（中频） |
| **四轴风格参数** | "我怎么说话"——亲切度/详细度/主动度/结构度 | 规则层(实时) + embedding(定期) + LLM(复盘) | 每轮对话（高频） |

### 3.2 维度 A：身份（identity）

```python
@dataclass
class PersonaIdentity:
    name: str            # 如 "考勤管家" / "忠诚伙伴"
    brief: str           # 身份描述（随关系深度变化）
    business_domain: str # 业务域（attendance/shipment/product/...）
    industry: str        # 企业入驻行业（初始身份来源）
```

**身份演进**（随 rapport 连续变化）：
- rapport=0.3：`你是考勤管家，专业地服务用户，熟悉考勤业务。`
- rapport=0.7：`你是用户熟悉的考勤管家，了解他的考勤习惯和偏好。`
- rapport=1.0：`你是用户最忠诚的伙伴，最懂他的考勤需求，像老朋友一样可靠。`

**行业 → 初始身份映射**：

| 企业行业 | 初始 identity_name | business_domain |
|---------|-------------------|-----------------|
| 制造业 | 生产管家 | production |
| 零售业 | 门店管家 | retail |
| 物流业 | 运单管家 | shipment |
| 服务业 | 客户管家 | customer |
| 贸易业 | 发货管家 | shipment |
| 科技业 | 项目管家 | project |
| 未选/通用 | 业务管家 | general |

**业务漂移机制**：当用户连续 50 轮主要操作某业务域（如考勤）而非初始行业域（如零售）时，identity_name 从"门店管家"渐变到"考勤管家"。渐变过程平滑（用权重混合两个身份描述），避免突兀切换。漂移期间身份描述用模糊措辞（如"你的业务管家"）过渡，不直接切换名称。

### 3.3 维度 B：关系深度（rapport）

```python
@dataclass
class RapportScore:
    score: float  # 0.0(陌生) ~ 1.0(忠诚)
    interaction_count: int       # 累计互动轮数
    business_depth: float        # 业务深度（涉及业务域数量/操作复杂度）
    emotion_signal_count: int    # 情感信号次数（用户感谢/信任表达）
```

**计算公式**：
```
rapport_score = 0.5 * normalize(interaction_count, 0, 500)
              + 0.3 * business_depth
              + 0.2 * normalize(emotion_signal_count, 0, 50)
```
- `normalize(x, min, max)` = clamp((x - min) / (max - min), 0, 1)
- interaction_count: 0 轮=0.0, 250 轮=0.5, 500+ 轮=1.0
- business_depth: 涉及业务域数量 / 5（最多 5 个域）
- emotion_signal_count: 0 次=0.0, 50+ 次=1.0

**冷启动默认值**：rapport = 0.3（友好默认，而非 0.0 冷漠）

**rapport 对四轴的软偏移**：
```
rapport=0.0 → 无偏移
rapport=0.5 → warmth +0.1, proactivity +0.1
rapport=1.0 → warmth +0.2, proactivity +0.2, detail +0.1
```

**软偏移规则**：只调整"默认值"，用户行为信号强烈时以用户为准。如用户连续 10 轮都用祈使句，warmth 锁定低位，rapport 再高也不抬。

### 3.4 维度 C：四轴风格参数

```python
@dataclass
class PersonaAxes:
    warmth: float       # 亲切度（T/F）0=就事论事 / 1=有温度
    detail: float       # 详细度（S/N）0=概括方向 / 1=具体步骤
    proactivity: float  # 主动度（E/I）0=问什么答什么 / 1=主动建议
    structure: float    # 结构度（J/P）0=灵活对话 / 1=结构化清单
```

**MBTI 映射**：
- warmth ← T/F（Thinking/Feeling）
- detail ← S/N（Sensing/Intuition，S=具体细节→detail高，N=概括直觉→detail低）
- proactivity ← E/I（Extroversion/Introversion，E=主动→proactivity高）
- structure ← J/P（Judging/Perceiving，J=结构化→structure高）

**推断机制**：三层管线（见第 4 节）

---

## 4. 三层推断管线

### 4.1 管线总览

```
用户发消息
    │
    ▼
L1 规则层（实时，每轮更新，零成本）
    │
    ▼ （写入用户画像，作为"实时层"）
L2 embedding 层（定期，每 10 轮触发，发现隐藏模式）
    │
    ▼ （校准 L1 的实时值，写入用户画像"模式层"）
L3 LLM 层（定期复盘，每 20 轮或会话结束时触发）
    │
    ▼
最终四轴值 = L1实时(0.4) + L2模式(0.3) + L3校准(0.3)
```

### 4.2 L1 规则层（实时）

- **触发**：每轮对话同步执行
- **输入**：用户当前消息 + 最近 N 轮历史
- **规则示例**：
  - 消息长度 ≤10 字 → detail 倾向低
  - 含 emoji/语气词（哈/呢/呀/哦）→ warmth 倾向高
  - 祈使句（帮我/查下/弄一下）→ warmth 倾向低
  - 问句比例高 → proactivity 倾向低
  - 含编号/列表（1. 2. 3.）→ structure 倾向高
  - "详细说说/展开讲讲" → detail 倾向高
  - "简单点/长话短说" → detail 倾向低
- **输出**：四轴瞬时值（0-1）+ 置信度
- **延迟**：<1ms
- **实现**：纯内存计算，无 IO

### 4.3 L2 embedding 层（定期）

- **触发**：每 10 轮异步执行
- **输入**：用户最近 50 条消息的 embedding 向量
- **流程**：
  1. 调外部 embedding API（DeepSeek/智谱，零硬件）
  2. 存入 Redis（key: `persona:emb:{user_id}`）
  3. K-means 聚类（k=3-5，CPU 毫秒级）
  4. 聚类中心映射到四轴参数空间（用预标注校准表）
- **输出**：四轴模式值（0-1）+ 模式标签（如"简洁务实型"）
- **延迟**：~200ms（异步，不阻塞对话）
- **作用**：发现规则捕捉不到的长期风格模式
- **硬件成本**：零（外部 API + 现有 Redis + CPU 聚类）

### 4.4 L3 LLM 层（定期复盘）

- **触发**：每 20 轮或会话结束时异步执行
- **输入**：用户最近 20 轮对话摘要 + L1/L2 当前四轴值
- **流程**：
  1. 用小模型（deepseek-chat）分析对话风格
  2. 输出四轴校准值 + 理由（JSON 格式）
  3. 与 L1/L2 加权融合（L3 权重 0.3，L1+L2 0.7）
- **输出**：最终四轴值 + 解释（可追溯为什么是这个值）
- **延迟**：~1-2s（异步，不阻塞对话）
- **作用**：校准规则和 embedding 的偏差，处理复杂语境

### 4.5 三层融合公式

```
final_warmth = 0.4 * L1_warmth + 0.3 * L2_warmth + 0.3 * L3_warmth
final_detail = 0.4 * L1_detail + 0.3 * L2_detail + 0.3 * L3_detail
... (proactivity, structure 同理)

# 软偏移：rapport 基线偏移只影响"默认值"，用户信号强烈时锁定
if user_signal_strength(warmth) > 0.7:  # 用户行为明确
    final_warmth = final_warmth  # 不偏移
else:
    final_warmth = clamp(final_warmth + rapport_offset_warmth, 0, 1)
```

### 4.6 冷启动处理

| 场景 | 处理 |
|------|------|
| 新用户首轮 | L1 规则提取当前消息信号；L2/L3 无数据跳过；四轴 = L1 值；rapport = 0.3（友好默认） |
| 新用户前 10 轮 | 仅 L1 实时推断；四轴 = L1 值；rapport 渐进计算 |
| 10 轮后 | L2 开始触发；四轴 = L1(0.5) + L2(0.5) |
| 20 轮后 | L3 开始触发；四轴 = L1(0.4) + L2(0.3) + L3(0.3) |

### 4.7 异常容错

- embedding API 失败 → 跳过 L2，用 L1+L3
- LLM 调用失败 → 跳过 L3，用 L1+L2
- 三层全失败 → 回退到 rapport 基线默认值（不阻塞对话）

---

## 5. Prompt 生成器 + 模型参数映射

### 5.1 Prompt 生成器

最终 system_prompt = 身份段 + 风格段 + 业务上下文段 + 安全段（≤400 字）

**身份段**（由 identity + rapport 生成，~80 字）：
```
你是{identity_name}，{identity_brief}。
```

**风格段**（由四轴参数映射到具体指令句，~120 字）：

| 四轴 | 参数范围 | 映射指令句 |
|------|---------|-----------|
| warmth | ≥0.7 | "用口语化表达，可适度寒暄，像朋友聊天" |
| warmth | 0.4-0.7 | "语气友好但不啰嗦，保持专业" |
| warmth | <0.4 | "就事论事，直接给结论，不寒暄" |
| detail | ≥0.7 | "详细解释，给出具体步骤和原因" |
| detail | 0.4-0.7 | "适度详细，关键点说清楚" |
| detail | <0.4 | "简洁回答，惜字如金" |
| proactivity | ≥0.7 | "主动提建议和下一步，不等用户问" |
| proactivity | 0.4-0.7 | "回答后可附带一个相关建议" |
| proactivity | <0.4 | "问什么答什么，不主动延伸" |
| structure | ≥0.7 | "用编号列表/分点组织回答" |
| structure | 0.4-0.7 | "重要信息分点，其余段落化" |
| structure | <0.4 | "自然段落对话，不强求结构" |

**业务上下文段**（复用现有 `_build_context_prompt`，~150 字）：
- 会话意图、工具线索、待确认项、最近操作等（现有逻辑不变）

**安全段**（固定，~50 字）：
```
如果不确定，诚实告知。涉及订单/支付/删除操作时需用户确认。
```

**长度控制**：
- 身份段 ~80 字 + 风格段 ~120 字 + 业务上下文段 ~150 字 + 安全段 ~50 字 = ~400 字
- 比现状（~200 字）增加 ~200 字，token 成本增加可控（约 +50 tokens/轮）
- 若业务上下文段超长（如 Excel 绑定场景），自动压缩风格段（只保留最强信号轴的指令）

### 5.2 模型参数映射

```python
def map_to_llm_params(warmth, detail, proactivity, structure, rapport):
    return {
        "temperature": 0.3 + warmth * 0.4,        # 0.3-0.7，亲切度高→更有创造力
        "max_tokens": int(300 + detail * 700),     # 300-1000，详细度高→更长
        "top_p": 0.9 - structure * 0.2,            # 0.7-0.9，结构度高→更聚焦
        "frequency_penalty": proactivity * 0.3,    # 0-0.3，主动度高→更多样表达
        "presence_penalty": 0,                     # 固定
    }
```

| persona 参数 | 影响的推理参数 | 逻辑 |
|-------------|---------------|------|
| warmth ↑ | temperature ↑ | 更有"人情味"，表达更多样 |
| detail ↑ | max_tokens ↑ | 允许更长回答 |
| structure ↑ | top_p ↓ | 更聚焦，减少发散 |
| proactivity ↑ | frequency_penalty ↑ | 避免重复，主动延伸 |

### 5.3 与现有 base_prompt 的关系

```python
# 现状（api.py:449-461）：
base_prompt = "你是一个专业的业务助手..."  # 硬编码
system_prompt = base_prompt + context_prompt

# 改造后：
persona = await persona_service.get_user_persona(user_id, recent_messages)
system_prompt = persona_prompt_builder.build(
    identity=persona.identity,
    rapport=persona.rapport,
    axes=persona.axes,
    context_prompt=self._build_context_prompt(context),  # 复用现有
)
llm_params = persona_param_mapper.map(persona.axes, persona.rapport)

# Fallback：persona 服务异常时回退到旧 base_prompt
if persona is None:
    system_prompt = LEGACY_BASE_PROMPT + context_prompt
    llm_params = DEFAULT_LLM_PARAMS
```

---

## 6. 执行方面

### 6.1 对话执行流程

```
用户消息到达 /api/ai/chat/stream
    │
    ▼
1. 加载用户画像（Redis 优先，DB 回源）
   persona = await persona_service.get(user_id)
   若无 → 冷启动默认值（rapport=0.3, 四轴=0.5）
    │
    ▼
2. L1 规则层实时推断（同步，<1ms）
   axes_l1 = rule_inferencer.infer(msg, history)
    │
    ▼
3. 融合最终 persona（L1 + L2缓存 + L3缓存）
   final_axes = fuse(L1, L2_cache, L3_cache) + rapport 软偏移
    │
    ▼
4. 生成 system_prompt + llm_params
   prompt = prompt_builder.build(persona, ctx)
   params = param_mapper.map(persona)
    │
    ▼
5. 调用 LLM（复用现有 LLM Client）
   response = llm_client.chat(prompt, params)
    │
    ▼
6. 异步更新画像（不阻塞响应）
   - 更新互动轮数（rapport 输入）
   - 更新业务域计数（身份漂移依据）
   - 更新情感信号计数（rapport 输入）
   - 每 10 轮触发 L2 embedding（异步）
   - 每 20 轮触发 L3 LLM 复盘（异步）
    │
    ▼
流式返回给前端（桌面 Vue / 手机 Android 透明接收）
```

**关键原则**：persona 推断和 prompt 生成在**同步路径**（必须快），画像更新和 L2/L3 推断在**异步路径**（不阻塞响应）。

### 6.2 业务工具调用

persona 四轴影响**工具调用的呈现方式**，不影响工具是否调用（由 IntentMixin 决定）：

| persona 信号 | 对工具调用的影响 |
|-------------|----------------|
| proactivity ≥0.7 | 查询类工具调用后，主动追加"要不要也查一下相关的 X？" |
| structure ≥0.7 | 工具返回结果用表格/编号列表呈现 |
| detail ≥0.7 | 工具结果附带解释（如"这个订单状态是已发货，意味着..."） |
| warmth ≥0.7 | 工具失败时用安抚语气（"别急，我再试试"）而非冷冰冰报错 |

**集成点**：在 `app/services/conversation/handlers.py` 的 `HandlersMixin` 中，工具结果格式化时注入 persona 风格包装。

### 6.3 Neuro Bus 集成

新增 persona 领域事件，接入现有 Neuro Bus：

```python
# app/neuro_bus/events/persona_event.py（新增）
@dataclass
class PersonaUpdated:
    user_id: str
    axes: PersonaAxes  # 四轴值
    rapport: float
    identity: str
    source: str  # "l1" | "l2" | "l3" | "fusion"
    trace_id: str
```

**发布时机**：
- L1 每轮发布（轻量）
- L2/L3 触发时发布（重量）
- 身份漂移时发布（重要，需监控）

**SLA 分层**：
- L1 规则推断 → Reflex 通道（1ms 内完成）
- 画像加载 → Subconscious 通道（10ms 内完成）
- L2/L3 异步推断 → Conscious 通道（200ms 内完成，不阻塞对话）

**Conscious 处理器感知 persona**：`app/domain/neuro/cognition/conscious_llm_handler.py` 的 `_DEFAULT_SYSTEM_PROMPT` 改为从 persona 服务动态获取，而非硬编码。

### 6.4 性能与监控

**性能预算**：

| 环节 | 预算 | 策略 |
|------|------|------|
| 画像加载 | <5ms | Redis 缓存，TTL 1h，DB 回源 |
| L1 规则推断 | <1ms | 纯内存计算 |
| Prompt 生成 | <2ms | 模板拼接，无 IO |
| L2 embedding | <500ms | 异步，不阻塞 |
| L3 LLM 复盘 | <2s | 异步，不阻塞 |
| **同步路径总增量** | **<10ms** | 对话延迟几乎无感 |

**监控指标**（接入现有 Prometheus）：
- `persona_l1_infer_duration_seconds`（L1 推断延迟）
- `persona_l2_l3_trigger_total`（L2/L3 触发次数）
- `persona_fallback_total`（回退到旧 prompt 的次数，告警阈值 >5%）
- `persona_rapport_distribution`（用户 rapport 分布直方图）
- `persona_identity_drift_total`（身份漂移次数）

**A/B 测试框架**：
- 用 `user_id % 100` 分桶
- 0-49 桶：persona 系统开启
- 50-99 桶：旧通用 prompt（对照组）
- 监控两组的对话满意度、平均轮数、复访率

---

## 7. 持久化与用户画像存储

### 7.1 Redis（热数据，TTL 1h）

```
key: persona:profile:{user_id}
value: {
  axes: {warmth, detail, proactivity, structure},  # 融合后的最终值
  axes_l1: {...},  # L1 最新值
  axes_l2: {...},  # L2 最新值
  axes_l3: {...},  # L3 最新值
  rapport: 0.3,
  identity: {name, brief, business_domain, industry},
  interaction_count: 0,
  business_domain_counts: {attendance: 0, shipment: 0, ...},
  emotion_signal_count: 0,
  updated_at: timestamp
}
```

### 7.2 DB（冷数据，持久化）

```sql
-- 表: persona_profile
CREATE TABLE persona_profile (
  user_id VARCHAR(64) PRIMARY KEY,
  industry VARCHAR(32) NOT NULL,
  identity_name VARCHAR(64) NOT NULL,
  identity_brief TEXT NOT NULL,
  business_domain VARCHAR(32) NOT NULL,
  rapport_score FLOAT NOT NULL DEFAULT 0.3,
  warmth FLOAT NOT NULL DEFAULT 0.5,
  detail FLOAT NOT NULL DEFAULT 0.5,
  proactivity FLOAT NOT NULL DEFAULT 0.5,
  structure FLOAT NOT NULL DEFAULT 0.5,
  interaction_count INT NOT NULL DEFAULT 0,
  business_domain_counts JSON NOT NULL DEFAULT '{}',
  emotion_signal_count INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- 表: persona_event_log（事件日志，用于审计和 L3 复盘）
CREATE TABLE persona_event_log (
  id BIGSERIAL PRIMARY KEY,
  user_id VARCHAR(64) NOT NULL,
  event_type VARCHAR(32) NOT NULL,  -- 'l1_infer' | 'l2_cluster' | 'l3_review' | 'identity_drift' | 'rapport_update'
  event_data JSON NOT NULL,
  trace_id VARCHAR(64),
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  INDEX idx_user_created (user_id, created_at)
);
```

### 7.3 embedding 向量存储

```
Redis key: persona:emb:{user_id}
value: List[float]  # 最近 50 条消息的 embedding 向量列表
TTL: 7 天
```

---

## 8. 与现有代码集成点

| 现有代码 | 改造动作 |
|---------|---------|
| `app/services/conversation/api.py:449-461` | `base_prompt` 改为调 `persona_prompt_builder.build()`，旧 prompt 作为 fallback |
| `app/services/conversation/manager.py` | `AIConversationService` 注入 `PersonaService` 依赖 |
| `app/infrastructure/llm/invoke.py` | `chat_completion_openai_format` 接收 persona 推理参数 |
| `app/domain/neuro/cognition/conscious_llm_handler.py:37` | `_DEFAULT_SYSTEM_PROMPT` 改为动态获取 |
| `app/services/conversation/handlers.py` | 工具结果格式化注入 persona 风格 |
| `app/fastapi_routes/mobile_api_extensions.py:1616` | 小C助理客服通道也接入 persona（可选） |
| 新增 `app/services/persona/` | persona 推断服务（三层管线） |
| 新增 `app/infrastructure/persona/` | 画像持久化、embedding 客户端 |
| 新增 `app/neuro_bus/events/persona_event.py` | persona 领域事件 |
| 新增 `app/domain/persona/` | persona 领域模型（值对象/聚合根） |

---

## 9. 新增模块结构

```
app/
├── domain/persona/                    # 领域模型
│   ├── __init__.py
│   ├── entities.py                    # PersonaProfile 聚合根
│   ├── value_objects.py               # PersonaAxes, PersonaIdentity, RapportScore
│   └── repositories.py                # PersonaProfileRepository 接口
├── services/persona/                  # 应用服务
│   ├── __init__.py
│   ├── persona_service.py             # PersonaService 主服务
│   ├── rule_inferencer.py             # L1 规则推断
│   ├── embedding_inferencer.py        # L2 embedding 推断
│   ├── llm_inferencer.py              # L3 LLM 推断
│   ├── axes_fuser.py                  # 三层融合
│   ├── rapport_calculator.py          # 关系深度计算
│   ├── identity_resolver.py           # 身份解析 + 漂移
│   ├── prompt_builder.py              # Prompt 生成器
│   └── param_mapper.py                # 模型参数映射
├── infrastructure/persona/            # 基础设施
│   ├── __init__.py
│   ├── persona_repository_impl.py     # 画像持久化（Redis+DB）
│   ├── embedding_client.py            # 外部 embedding API 客户端
│   └── models.py                      # DB ORM 模型
├── neuro_bus/events/
│   └── persona_event.py               # persona 领域事件
└── fastapi_routes/
    └── (无新增路由，persona 在对话流内透明注入)
```

---

## 10. 测试策略

### 10.1 单元测试

| 模块 | 测试重点 |
|------|---------|
| `rule_inferencer.py` | 每条规则的触发条件、边界值、多规则叠加 |
| `embedding_inferencer.py` | API 失败容错、聚类结果映射 |
| `llm_inferencer.py` | JSON 解析、异常容错、权重融合 |
| `axes_fuser.py` | 三层权重计算、软偏移锁定逻辑 |
| `rapport_calculator.py` | 多维度加权、归一化、冷启动默认值 |
| `identity_resolver.py` | 行业映射、业务漂移阈值、平滑过渡 |
| `prompt_builder.py` | 四轴→指令句映射、长度控制、压缩策略 |
| `param_mapper.py` | 参数映射公式、边界值 |

### 10.2 集成测试

| 场景 | 测试重点 |
|------|---------|
| 首次对话 | 冷启动默认值、L1 推断、prompt 生成 |
| 10 轮对话 | L2 触发、融合权重切换 |
| 20 轮对话 | L3 触发、三层融合 |
| 50 轮业务漂移 | 身份平滑过渡 |
| persona 服务异常 | fallback 到旧 prompt |
| embedding API 失败 | 跳过 L2，用 L1+L3 |
| LLM 调用失败 | 跳过 L3，用 L1+L2 |

### 10.3 覆盖率要求

遵循项目 90% 覆盖率铁律：
- 新增模块行覆盖率 ≥ 90%
- 分支覆盖率 ≥ 85%
- 全量口径（`source=["app"]`），禁止窄 include
- 禁止 `pragma: no cover` 滥用

---

## 11. 上线策略

### 11.1 A/B 灰度

- 用 `user_id % 100` 分桶
- 0-49 桶：persona 系统开启
- 50-99 桶：旧通用 prompt（对照组）
- 监控两组的对话满意度、平均轮数、复访率

### 11.2 监控告警

- `persona_fallback_total` 告警阈值 >5%（persona 系统异常率）
- `persona_l1_infer_duration_seconds` p99 >5ms（L1 推断过慢）
- `persona_identity_drift_total` 突增（身份频繁漂移）

### 11.3 回滚方案

- 通过 feature flag 一键关闭 persona 系统，回退到旧 base_prompt
- Redis 画像数据保留，不影响回滚后再次开启

---

## 12. 关键约束

1. **前端零改动**：桌面 Vue 和手机 Android 都不需要动
2. **复用现有基础设施**：LLM Client、Redis、Neuro Bus 都复用
3. **旧 prompt 作为 fallback**：persona 系统异常时回退
4. **同步路径 <10ms**：persona 推断和 prompt 生成不阻塞对话
5. **连续参数调节**：四轴和 rapport 都是 0-1 连续值，不做离散分类
6. **软偏移规则**：rapport 偏移不覆盖用户强信号
7. **冷启动友好**：rapport=0.3 而非 0.0
8. **业务漂移平滑**：50 轮阈值，模糊措辞过渡
9. **prompt ≤400 字**：控制 token 成本
10. **三层容错**：任一层失败不阻塞对话

---

## 13. 未决事项

无。所有核心决策已在 brainstorming 阶段确认。

---

**设计确认记录**：
- 2026-06-21：brainstorming 完成，用户确认"一次性全做"
- 待用户审查本文档后转入 writing-plans 创建实现计划
