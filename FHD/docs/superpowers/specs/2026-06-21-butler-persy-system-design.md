# 拟人 Persy 系统 — Butler 个性化人设设计

> 日期：2026-06-21
> 状态：已批准，实施中
> 范围：FHD 项目（复用现有 MemoryV2 基础设施）

## 1. 目标

为 Butler 实现「拟人化人设系统」，包含三层：

1. **身份层（Identity）**："我是谁" — 考勤管家/发货管家/忠诚伙伴等，枚举+复合身份
2. **MBTI 人格层**：底层模型，4 维倾向分数（E/I、S/N、T/F、J/P），不在 UI 显示
3. **四轴参数层（派生）**：亲切度/详细度/主动度/结构度（0-100），从 MBTI 派生，UI 可视化

身份初始由用户 MOD 所有权映射，随对话互动深度演进。四轴由对话行为模式推断（规则+embedding+LLM）。

## 2. 架构决策

- **复用现有 MemoryV2**：3 层记忆（长期画像/episodic/偏好纠正）直接复用 MemoryV2 的 entity/episodic/preference 类型，不新建记忆表
- **只新增 1 张表**：`butler_user_profiles`（身份 + MBTI + 元数据）
- **读写分离**：对话时只读 profile 生成 prompt；行为数据异步落库；cron 消费更新画像
- **MBTI 不显示**：UI 只显示派生的四轴进度条 + 身份标签
- **UI 改造现有区块**：SettingsView.vue 的「记忆库 v2」改为「拟人persy系统」，上半部分加 profile 可视化，下半部分保留 MemoryV2

## 3. 数据模型

### 新增表：`butler_user_profiles`

```python
class ButlerUserProfile(Base):
    __tablename__ = "butler_user_profiles"
    user_id: Mapped[int]  # PK, FK → users.id

    # 身份层
    identity_primary: Mapped[str]       # 原子身份枚举
    identity_composite: Mapped[str]     # 复合身份标签（LLM 生成）
    identity_vector_json: Mapped[str]   # 各原子身份亲和度 JSON

    # MBTI 层（底层，不在 UI 显示）
    mbti_ei: Mapped[int]  # 0-100, E=100
    mbti_sn: Mapped[int]  # 0-100, N=100
    mbti_tf: Mapped[int]  # 0-100, F=100
    mbti_jp: Mapped[int]  # 0-100, P=100
    mbti_type: Mapped[str]  # 派生 16 型标签
    mbti_confidence: Mapped[float]

    # 元数据
    last_inferred_at: Mapped[datetime]
    interaction_count: Mapped[int]
```

四轴不存储，运行时从 MBTI 派生。

### 复用现有表

- `chat_messages`：短期对话记忆（补齐 user 消息落库）
- MemoryV2（JSON 存储）：preference/entity/episodic 三类记忆

## 4. MBTI ↔ 四轴映射

```python
warmth = 0.7 * tf_score + 0.3 * ei_score
verbosity = 0.7 * sn_score + 0.3 * (100 - jp_score)
proactiveness = 0.7 * ei_score + 0.3 * jp_score
structuredness = 0.7 * jp_score + 0.3 * (100 - sn_score)
```

## 5. 原子身份枚举

```python
ATOMIC_IDENTITIES = [
    "考勤管家", "发货管家", "忠诚伙伴", "财务顾问",
    "运营参谋", "客服先锋", "数据侦探", "氛围管家",
    "流程教练", "战略参谋",
]
```

MBTI 16 型 → 亲和身份映射表维护在 `butler_identity_catalog.py`。

## 6. 推断流程

```
对话行为事件 → cron 消费
  ↓
规则层：行为特征 → MBTI 4 维增量
embedding 层：对话内容向量聚类 → 16 型原型比对
LLM 层：综合 → 新 MBTI 分数 + 身份演进建议
  ↓
更新 butler_user_profiles
抽取 episodic → MemoryV2 episodic 候选
检测偏好纠正 → MemoryV2 preference 候选
```

## 7. API

```
GET  /api/butler/profile         # 读当前用户 profile（身份+四轴，不含 MBTI 原始分数）
POST /api/butler/profile/infer   # 手动触发推断
```

## 8. UI

SettingsView.vue「记忆库 v2」→「拟人persy系统」：
- 上半：profile 可视化（身份标签 + 四轴进度条 + 互动轮数）
- 下半：保留现有 MemoryV2 筛选/写入/列表

## 9. 文件清单

**新增（后端）：**
- `app/db/models/butler_profile.py`
- `app/services/butler_profile_service.py`
- `app/application/butler_profile_inference.py`
- `app/application/butler_identity_catalog.py`

**新增（前端）：**
- `frontend/src/api/butlerProfile.ts`

**修改：**
- `app/db/models/__init__.py`（注册新模型）
- `app/fastapi_routes/domains/misc/routes.py`（新增端点）
- `frontend/src/views/SettingsView.vue`（UI 改造）

**测试：**
- `tests/test_services/test_butler_profile_service.py`
- `tests/test_application/test_butler_profile_inference.py`
- `frontend/src/api/butlerProfile.test.ts`
