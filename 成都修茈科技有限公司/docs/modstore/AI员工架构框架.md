# AI 员工架构框架（AI Employee Framework）

> **版本**: v2.0  
> **设计目标**: 构建一个类人化的 AI 员工能力模型，支持模块化组合、向后兼容、易扩展

---

## 一、架构总览

### 1.1 设计理念

将 AI 员工视为一个**"数字人"**，具备类似人类的完整能力栈：

```
┌─────────────────────────────────────────────────┐
│                  🧑 AI 员工                        │
│                                                   │
│  ┌───────────────────────────────────────────┐  │
│  │  🛡️ 管理层（Self-Management）              │  │
│  │  定时调度 | 异常处理 | 安全合规 | 性能监控  │  │
│  └───────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────┐  │
│  │  🤝 协作层（Collaboration）                 │  │
│  │  工作流 | 任务交接 | 人机协作 | 权限管理    │  │
│  └───────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────┐  │
│  │  🖐️ 行动层（Action）                        │  │
│  │  文本 | 语音 | RPA | API | 消息 | 报表     │  │
│  └───────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────┐  │
│  │  🧠 认知层（Cognition）                     │  │
│  │  Agent | Skill | 决策 | 推理 | 生成        │  │
│  └───────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────┐  │
│  │  💾 记忆层（Memory）                        │  │
│  │  上下文 | 知识库 | 用户画像 | 经验积累      │  │
│  └───────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────┐  │
│  │  👁️ 感知层（Perception）                    │  │
│  │  视觉 | 听觉 | 文档 | 数据 | 事件监听      │  │
│  └───────────────────────────────────────────┘  │
│                                                   │
│  ┌───────────────────────────────────────────┐  │
│  │  🆔 身份层（Identity）                      │  │
│  │  名称 | 描述 | 头像 | 行业 | 价格          │  │
│  └───────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

### 1.2 核心原则

1. **模块化**: 每层能力独立配置，可按需启用/禁用
2. **向后兼容**: 旧版员工包无需修改即可运行
3. **渐进增强**: 从简单工作流到全能员工，平滑升级
4. **类型安全**: 完整的 TypeScript 类型定义和 JSON Schema 校验
5. **生态开放**: 支持第三方 Skill、声音、知识库接入

---

## 二、完整数据结构定义

### 2.1 TypeScript 类型定义

```typescript
// ==================== 基础身份层 ====================

interface EmployeeIdentity {
  /** 员工唯一标识 */
  id: string;
  /** 版本号 (semver) */
  version: string;
  /** 包类型 */
  artifact: 'employee_pack' | 'mod';
  /** 员工名称 */
  name: string;
  /** 员工描述 */
  description: string;
  /** 图标 (base64 或 URL) */
  icon?: string;
  /** 标签 */
  tags?: string[];
  /** 作者信息 */
  author?: {
    name: string;
    email?: string;
    url?: string;
  };
  /** 创建时间 */
  created_at?: string;
  /** 更新时间 */
  updated_at?: string;
}

// ==================== 感知层 ====================

interface PerceptionConfig {
  /** 视觉输入 */
  vision?: {
    enabled: boolean;
    /** 支持的图片格式 */
    supported_formats: string[];
    /** 是否支持视频 */
    video_support?: boolean;
    /** 是否支持屏幕截图 */
    screen_capture?: boolean;
    /** OCR 配置 */
    ocr?: {
      enabled: boolean;
      languages: string[];
    };
  };
  
  /** 听觉输入 */
  audio?: {
    enabled: boolean;
    /** 语音转文字 (ASR) */
    asr?: {
      enabled: boolean;
      model?: string;
      languages: string[];
    };
    /** 声纹识别 */
    voiceprint?: {
      enabled: boolean;
    };
    /** 情绪识别 */
    emotion_detection?: boolean;
  };
  
  /** 文档输入 */
  document?: {
    enabled: boolean;
    supported_formats: string[];
    max_file_size_mb?: number;
    batch_processing?: boolean;
  };
  
  /** 数据输入 */
  data_input?: {
    enabled: boolean;
    /** API 数据源 */
    api_sources?: Array<{
      name: string;
      url: string;
      method: 'GET' | 'POST';
      auth?: AuthConfig;
    }>;
    /** 数据库连接 */
    database?: Array<{
      type: 'mysql' | 'postgres' | 'mongodb' | 'redis';
      host: string;
      port: number;
      database: string;
    }>;
    /** 文件监听 */
    file_watch?: {
      enabled: boolean;
      watch_paths: string[];
      file_extensions: string[];
    };
  };
  
  /** 事件监听 */
  event_listener?: {
    enabled: boolean;
    events: string[];
    /** Webhook 配置 */
    webhooks?: Array<{
      name: string;
      url: string;
      secret?: string;
    }>;
  };
}

// ==================== 记忆层 ====================

interface MemoryConfig {
  /** 短期记忆（上下文窗口） */
  short_term?: {
    /** 上下文窗口大小 (tokens) */
    context_window: number;
    /** 会话超时 (秒) */
    session_timeout: number;
    /** 是否保留对话历史 */
    keep_history: boolean;
    /** 最大历史轮数 */
    max_history_rounds?: number;
  };
  
  /** 长期记忆（知识库） */
  long_term?: KnowledgeBaseConfig;
  
  /** 用户画像 */
  user_profiles?: {
    enabled: boolean;
    /** 画像维度 */
    dimensions: string[];
    /** 更新策略 */
    update_strategy: 'realtime' | 'batch' | 'manual';
  };
  
  /** 经验积累 */
  experience?: {
    enabled: boolean;
    /** 成功/失败案例存储 */
    case_storage: boolean;
    /** 自动优化 */
    auto_optimize: boolean;
    /** 反馈学习 */
    feedback_learning: boolean;
  };
  
  /** 标签系统 */
  tagging?: {
    enabled: boolean;
    auto_tag: boolean;
    tag_categories: string[];
  };
}

interface KnowledgeBaseConfig {
  enabled: boolean;
  /** 知识来源 */
  sources: Array<{
    source_id: string;
    name: string;
    type: 'document' | 'url' | 'database' | 'api' | 'qna';
    /** 文件路径或 URL */
    paths: string[];
    /** 分块配置 */
    chunk_size?: number;
    chunk_overlap?: number;
    /** 更新频率 */
    update_frequency?: 'daily' | 'weekly' | 'manual';
  }>;
  /** 检索配置 */
  retrieval: {
    strategy: 'vector' | 'keyword' | 'hybrid';
    /** 返回数量 */
    top_k: number;
    /** 相似度阈值 */
    similarity_threshold: number;
    /** 是否启用重排序 */
    rerank_enabled: boolean;
  };
}

// ==================== 认知层 ====================

interface CognitionConfig {
  /** Agent 核心配置 */
  agent: AgentConfig;
  /** 技能模块 */
  skills: SkillConfig[];
  /** 决策引擎 */
  decision_engine?: {
    enabled: boolean;
    rules: DecisionRule[];
  };
}

interface AgentConfig {
  /** 系统提示词 */
  system_prompt: string;
  /** 角色定义 */
  role: {
    name: string;
    persona: string;
    tone: 'formal' | 'friendly' | 'professional' | 'casual';
    expertise: string[];
  };
  /** 行为规则 */
  behavior_rules: Array<{
    rule_id: string;
    name: string;
    description: string;
    priority: 'high' | 'medium' | 'low';
    action: 'filter' | 'enforce' | 'warn' | 'reject';
  }>;
  /** Few-Shot 示例 */
  few_shot_examples: Array<{
    input: string;
    output: string;
    explanation?: string;
  }>;
  /** 模型配置 */
  model: {
    provider: 'deepseek' | 'openai' | 'anthropic' | 'local';
    model_name: string;
    temperature: number;
    max_tokens: number;
    top_p: number;
    /** 是否启用流式输出 */
    stream?: boolean;
  };
}

interface SkillConfig {
  /** 技能 ID */
  skill_id: string;
  /** 技能名称 */
  skill_name: string;
  /** 技能版本 */
  version: string;
  /** 技能类型 */
  type: 'document_processing' | 'data_processing' | 'image_recognition' | 
        'audio_processing' | 'network_request' | 'business_logic' | 'custom';
  /** 技能配置 */
  config: Record<string, any>;
  /** 依赖项 */
  dependencies?: string[];
  /** 是否启用 */
  enabled: boolean;
}

interface DecisionRule {
  rule_id: string;
  name: string;
  condition: string;
  action: string;
  priority: number;
}

// ==================== 行动层 ====================

interface ActionConfig {
  /** 文本输出 */
  text_output?: {
    enabled: boolean;
    formats: string[];
    templates?: Array<{
      name: string;
      content: string;
    }>;
  };
  
  /** 语音输出 */
  voice_output?: VoiceOutputConfig;
  
  /** RPA 自动化 */
  rpa?: {
    enabled: boolean;
    actions: Array<{
      action_id: string;
      type: 'click' | 'type' | 'navigate' | 'screenshot' | 'file_operation';
      config: Record<string, any>;
    }>;
  };
  
  /** 消息推送 */
  messaging?: {
    enabled: boolean;
    channels: Array<{
      channel: 'email' | 'sms' | 'wechat' | 'dingtalk' | 'feishu' | 'webhook';
      config: Record<string, any>;
    }>;
  };
  
  /** API 调用 */
  api_calls?: Array<{
    name: string;
    url: string;
    method: 'GET' | 'POST' | 'PUT' | 'DELETE';
    auth?: AuthConfig;
    headers?: Record<string, string>;
    timeout?: number;
    retry?: {
      max_retries: number;
      backoff: 'linear' | 'exponential';
    };
  }>;
  
  /** 报表生成 */
  reporting?: {
    enabled: boolean;
    formats: ('pdf' | 'excel' | 'ppt' | 'chart')[];
    templates?: string[];
  };
}

interface VoiceOutputConfig {
  enabled: boolean;
  /** 声音克隆配置 */
  voice_cloning?: {
    voice_id: string;
    voice_name: string;
    settings: {
      speed: number;
      pitch: number;
      emotion: 'neutral' | 'enthusiastic' | 'professional' | 'gentle';
      language: string;
    };
  };
  /** TTS 配置 */
  tts?: {
    provider: 'azure' | 'aliyun' | 'custom';
    voice_name: string;
    sample_rate: number;
  };
}

// ==================== 协作层 ====================

interface CollaborationConfig {
  /** 工作流编排 */
  workflow?: {
    /** 工作流 ID */
    workflow_id?: number;
    /** 工作流索引 */
    workflow_index?: number;
    /** 节点配置 */
    nodes?: Array<{
      node_id: string;
      type: string;
      config: Record<string, any>;
    }>;
    /** 边配置 */
    edges?: Array<{
      from: string;
      to: string;
      condition?: string;
    }>;
  };
  
  /** 任务交接 */
  handoff?: {
    enabled: boolean;
    /** 交接条件 */
    conditions: string[];
    /** 交接目标 */
    targets: string[];
  };
  
  /** 进度同步 */
  progress_sync?: {
    enabled: boolean;
    /** 更新频率 */
    update_interval: number;
    /** 通知渠道 */
    notification_channels: string[];
  };
  
  /** 人机协作 */
  human_collaboration?: {
    enabled: boolean;
    /** 需要人工确认的场景 */
    require_approval: string[];
    /** 超时交接 */
    timeout_handoff: boolean;
    timeout_seconds: number;
  };
  
  /** 权限管理 */
  permissions?: {
    access_level: 'read_only' | 'read_write' | 'admin';
    data_scope: string[];
    operation_whitelist: string[];
    operation_blacklist: string[];
  };
}

// ==================== 管理层 ====================

interface ManagementConfig {
  /** 定时调度 */
  scheduler?: {
    enabled: boolean;
    jobs: Array<{
      job_id: string;
      name: string;
      cron: string;
      action: string;
      config?: Record<string, any>;
    }>;
    /** 事件触发器 */
    event_triggers?: string[];
  };
  
  /** 异常处理 */
  error_handling?: {
    /** 重试策略 */
    retry_policy: {
      max_retries: number;
      backoff: 'linear' | 'exponential';
      initial_delay_ms: number;
    };
    /** 降级策略 */
    fallback_strategy: 'retry' | 'skip' | 'human_handoff' | 'default_response';
    /** 告警配置 */
    alert: {
      enabled: boolean;
      channels: string[];
      severity_levels: ('info' | 'warning' | 'error' | 'critical')[];
    };
  };
  
  /** 安全策略 */
  security?: {
    /** 数据脱敏 */
    data_masking: {
      enabled: boolean;
      fields: string[];
    };
    /** 审计日志 */
    audit_log: boolean;
    /** 速率限制 */
    rate_limit: {
      requests_per_minute: number;
      requests_per_hour: number;
    };
    /** 访问控制 */
    access_control: {
      allowed_ips?: string[];
      require_auth: boolean;
    };
  };
  
  /** 性能监控 */
  performance?: {
    enabled: boolean;
    metrics: string[];
    /** 自动优化 */
    auto_optimize: boolean;
    /** 监控面板 */
    dashboard_url?: string;
  };
}

// ==================== 商业化层 ====================

interface CommerceConfig {
  /** 行业 */
  industry: string;
  /** 价格 */
  price: number;
  /** 定价模型 */
  pricing_model?: 'one_time' | 'subscription' | 'usage_based';
  /** 试用配置 */
  trial?: {
    enabled: boolean;
    duration_days: number;
    feature_limits: Record<string, any>;
  };
  /** 批量折扣 */
  bulk_discount?: Array<{
    min_quantity: number;
    discount_rate: number;
  }>;
}

// ==================== 完整员工配置 ====================

interface EmployeeConfig {
  /** 基础身份 */
  identity: EmployeeIdentity;
  /** 感知层 (可选) */
  perception?: PerceptionConfig;
  /** 记忆层 (可选) */
  memory?: MemoryConfig;
  /** 认知层 (可选) */
  cognition?: CognitionConfig;
  /** 行动层 (可选) */
  actions?: ActionConfig;
  /** 协作层 (可选) */
  collaboration?: CollaborationConfig;
  /** 管理层 (可选) */
  management?: ManagementConfig;
  /** 商业化 (可选) */
  commerce?: CommerceConfig;
  /** 兼容旧版工作流声明 */
  workflow_employees?: Array<Record<string, any>>;
  /** 元数据 */
  metadata?: {
    framework_version: string;
    created_by: string;
    migration_from?: string;
  };
}
```

---

## 三、向后兼容策略

### 3.1 旧版 Manifest 自动升级

```typescript
// 旧版 Manifest (v1)
interface LegacyManifest {
  id: string;
  version: string;
  artifact: string;
  name: string;
  description: string;
  industry?: string;
  commerce?: { price: number };
  workflow_employees?: Array<any>;
  panel_summary?: string;
  phone_agent_base_path?: string;
}

// 升级函数
function upgradeManifest(legacy: LegacyManifest): EmployeeConfig {
  return {
    identity: {
      id: legacy.id,
      version: legacy.version,
      artifact: legacy.artifact as any,
      name: legacy.name,
      description: legacy.description,
    },
    cognition: {
      agent: {
        system_prompt: legacy.panel_summary || '',
        role: {
          name: legacy.name,
          persona: '',
          tone: 'professional',
          expertise: [],
        },
        behavior_rules: [],
        few_shot_examples: [],
        model: {
          provider: 'deepseek',
          model_name: 'deepseek-chat',
          temperature: 0.7,
          max_tokens: 4000,
          top_p: 0.9,
        },
      },
      skills: [],
    },
    collaboration: {
      workflow: legacy.workflow_employees?.[0]?.workflow_id ? {
        workflow_id: legacy.workflow_employees[0].workflow_id,
        workflow_index: 0,
      } : undefined,
    },
    commerce: legacy.commerce || legacy.industry ? {
      industry: legacy.industry || '通用',
      price: legacy.commerce?.price || 0,
    } : undefined,
    workflow_employees: legacy.workflow_employees,
    metadata: {
      framework_version: '2.0.0',
      created_by: 'migration',
      migration_from: 'v1',
    },
  };
}
```

### 3.2 兼容性规则


| 旧版字段                    | 新版位置                            | 兼容策略               |
| ----------------------- | ------------------------------- | ------------------ |
| `id`                    | `identity.id`                   | 直接映射               |
| `version`               | `identity.version`              | 直接映射               |
| `name`                  | `identity.name`                 | 直接映射               |
| `description`           | `identity.description`          | 直接映射               |
| `workflow_employees[]`  | `collaboration.workflow`        | 提取第一条的 workflow_id |
| `panel_summary`         | `cognition.agent.system_prompt` | 作为系统提示词            |
| `phone_agent_base_path` | `actions.voice_output`          | 转为语音配置             |
| `industry`              | `commerce.industry`             | 直接映射               |
| `commerce.price`        | `commerce.price`                | 直接映射               |


### 3.3 运行时兼容检查

```typescript
function validateEmployeeConfig(config: any): { valid: boolean; errors: string[] } {
  const errors: string[] = [];
  
  // 必填字段检查
  if (!config.identity?.id) errors.push('缺少 identity.id');
  if (!config.identity?.name) errors.push('缺少 identity.name');
  if (!config.identity?.version) errors.push('缺少 identity.version');
  
  // 版本兼容处理
  if (!config.metadata?.framework_version) {
    // 旧版 manifest，自动升级
    console.warn('检测到旧版 manifest，将自动升级至 v2.0 格式');
  }
  
  // 模块依赖检查
  if (config.perception?.audio?.asr?.enabled && !config.actions?.voice_output) {
    errors.push('启用 ASR 需要配置语音输出');
  }
  
  if (config.memory?.long_term?.enabled && !config.cognition?.agent) {
    errors.push('知识库需要配置 Agent');
  }
  
  return {
    valid: errors.length === 0,
    errors,
  };
}
```

---

## 四、员工包目录结构

### 4.1 新版员工包结构

```
employee_pack/
├── manifest.json                 # 员工配置清单（必须）
├── README.md                     # 员工说明文档
├── icon.png                      # 员工图标（可选）
│
├── agent/                        # Agent 配置（可选）
│   ├── system_prompt.txt         # 系统提示词
│   ├── behavior_rules.json       # 行为规则
│   └── few_shot_examples.json    # 示例对话
│
├── skills/                       # 技能模块（可选）
│   ├── doc_analyzer/
│   │   ├── skill.json            # 技能配置
│   │   └── handler.py            # 技能处理代码
│   └── data_transformer/
│       ├── skill.json
│       └── handler.py
│
├── knowledge/                    # 知识库（可选）
│   ├── documents/                # 文档来源
│   │   ├── manual.pdf
│   │   └── faq.docx
│   └── config.json               # 知识库配置
│
├── voice/                        # 声音配置（可选）
│   ├── samples/                  # 声音样本
│   │   ├── sample1.mp3
│   │   └── sample2.mp3
│   └── config.json               # TTS/克隆配置
│
├── integrations/                 # API 集成（可选）
│   └── config.json               # 集成配置
│
├── workflow/                     # 工作流（可选）
│   └── workflow.json             # 工作流定义
│
└── tests/                        # 测试用例（可选）
    ├── sandbox_test.json
    └── fixtures/
```

### 4.2 旧版员工包结构（兼容）

```
old_employee_pack/
├── manifest.json                 # 旧版 manifest
├── main.py                       # 主逻辑
├── config.json                   # 配置文件
└── README.md                     # 说明文档
```

**兼容策略**: 运行时自动识别，旧版结构通过 `upgradeManifest()` 转换后加载。

---

## 五、核心接口定义

### 5.1 员工生命周期

```typescript
interface EmployeeLifecycle {
  /** 创建员工 */
  create(config: EmployeeConfig): Promise<EmployeeInstance>;
  
  /** 加载员工 */
  load(employeeId: string): Promise<EmployeeInstance>;
  
  /** 初始化（加载所有模块） */
  initialize(instance: EmployeeInstance): Promise<void>;
  
  /** 执行任务 */
  execute(instance: EmployeeInstance, task: TaskInput): Promise<TaskOutput>;
  
  /** 测试员工 */
  test(instance: EmployeeInstance, testSuite: TestSuite): Promise<TestResult>;
  
  /** 更新员工 */
  update(instance: EmployeeInstance, config: Partial<EmployeeConfig>): Promise<void>;
  
  /** 停用员工 */
  deactivate(instance: EmployeeInstance): Promise<void>;
}
```

### 5.2 模块接口

```typescript
// 感知模块
interface PerceptionModule {
  initialize(config: PerceptionConfig): Promise<void>;
  processInput(input: InputData): Promise<ProcessedData>;
}

// 记忆模块
interface MemoryModule {
  initialize(config: MemoryConfig): Promise<void>;
  store(key: string, value: any): Promise<void>;
  retrieve(key: string): Promise<any>;
  search(query: string): Promise<SearchResult[]>;
}

// 认知模块
interface CognitionModule {
  initialize(config: CognitionConfig): Promise<void>;
  process(input: string, context: Context): Promise<string>;
  addSkill(skill: SkillConfig): Promise<void>;
}

// 行动模块
interface ActionModule {
  initialize(config: ActionConfig): Promise<void>;
  execute(action: ActionRequest): Promise<ActionResponse>;
}

// 协作模块
interface CollaborationModule {
  initialize(config: CollaborationConfig): Promise<void>;
  triggerWorkflow(workflowId: number, input: any): Promise<WorkflowResult>;
  handoff(task: TaskData): Promise<void>;
}

// 管理模块
interface ManagementModule {
  initialize(config: ManagementConfig): Promise<void>;
  schedule(job: ScheduleJob): Promise<void>;
  handleError(error: Error): Promise<void>;
  getMetrics(): Promise<MetricsData>;
}
```

### 5.3 API 端点

```
# 员工管理
POST   /api/employees                    # 创建员工
GET    /api/employees                    # 员工列表
GET    /api/employees/{id}               # 员工详情
PUT    /api/employees/{id}               # 更新员工
DELETE /api/employees/{id}               # 删除员工

# 员工测试
POST   /api/employees/{id}/test          # 沙盒测试
GET    /api/employees/{id}/test/status   # 测试状态
POST   /api/employees/{id}/audit         # 五维审核

# 模块管理
POST   /api/employees/{id}/skills        # 添加技能
DELETE /api/employees/{id}/skills/{sid}  # 移除技能
POST   /api/employees/{id}/knowledge     # 更新知识库
POST   /api/employees/{id}/voice         # 配置声音

# 市场与上架
POST   /api/employees/{id}/publish       # 上架员工
GET    /api/market/employees             # 商店列表
GET    /api/market/employees/{id}        # 商店详情

# 兼容旧版
POST   /api/migrate/manifest              # 旧版 manifest 升级
GET    /api/migrate/status                # 迁移状态查询
```

---

## 六、员工类型预设模板

### 6.1 模板定义

```typescript
// 模板 1：简单工作流员工
const TemplateWorkflow: Partial<EmployeeConfig> = {
  identity: { artifact: 'employee_pack' },
  collaboration: {
    workflow: { workflow_id: null },
  },
};

// 模板 2：对话型 Agent
const TemplateAgent: Partial<EmployeeConfig> = {
  identity: { artifact: 'employee_pack' },
  cognition: {
    agent: {
      system_prompt: '',
      role: { name: '', persona: '', tone: 'professional', expertise: [] },
      behavior_rules: [],
      few_shot_examples: [],
      model: { provider: 'deepseek', model_name: 'deepseek-chat', temperature: 0.7, max_tokens: 4000, top_p: 0.9 },
    },
    skills: [],
  },
  memory: {
    short_term: { context_window: 8000, session_timeout: 1800, keep_history: true },
  },
};

// 模板 3：电话客服员工
const TemplatePhoneAgent: Partial<EmployeeConfig> = {
  identity: { artifact: 'employee_pack' },
  perception: {
    audio: { enabled: true, asr: { enabled: true, languages: ['zh-CN'] } },
  },
  cognition: {
    agent: { /* 同上 */ },
    skills: [],
  },
  actions: {
    voice_output: { enabled: true, voice_cloning: { voice_id: '', voice_name: '', settings: { speed: 1.0, pitch: 0, emotion: 'professional', language: 'zh-CN' } } },
  },
  memory: {
    long_term: { enabled: true, sources: [], retrieval: { strategy: 'hybrid', top_k: 5, similarity_threshold: 0.75, rerank_enabled: true } },
  },
};

// 模板 4：数据处理员工
const TemplateDataProcessor: Partial<EmployeeConfig> = {
  identity: { artifact: 'employee_pack' },
  perception: {
    data_input: { enabled: true, api_sources: [], file_watch: { enabled: false, watch_paths: [], file_extensions: [] } },
  },
  cognition: {
    agent: { /* 同上 */ },
    skills: [{ skill_id: 'data_transformer', skill_name: '数据转换器', version: '1.0.0', type: 'data_processing', config: {}, enabled: true }],
  },
  actions: {
    text_output: { enabled: true, formats: ['json', 'csv', 'excel'] },
  },
  management: {
    scheduler: { enabled: false, jobs: [] },
  },
};

// 模板 5：全能型员工
const TemplateFullStack: Partial<EmployeeConfig> = {
  identity: { artifact: 'employee_pack' },
  perception: { vision: { enabled: true, supported_formats: ['png', 'jpg'] }, audio: { enabled: true }, document: { enabled: true, supported_formats: ['pdf', 'docx'] }, data_input: { enabled: true }, event_listener: { enabled: false } },
  memory: { short_term: { context_window: 16000, session_timeout: 3600, keep_history: true }, long_term: { enabled: true, sources: [], retrieval: { strategy: 'hybrid', top_k: 5, similarity_threshold: 0.75, rerank_enabled: true } } },
  cognition: { agent: { /* 完整配置 */ }, skills: [] },
  actions: { text_output: { enabled: true, formats: ['text', 'json'] }, voice_output: { enabled: false }, messaging: { enabled: true, channels: [] }, api_calls: [], reporting: { enabled: false } },
  collaboration: { workflow: { workflow_id: null }, human_collaboration: { enabled: true, require_approval: [], timeout_handoff: true, timeout_seconds: 300 } },
  management: { scheduler: { enabled: false }, error_handling: { retry_policy: { max_retries: 3, backoff: 'exponential', initial_delay_ms: 1000 }, fallback_strategy: 'human_handoff', alert: { enabled: true, channels: ['email'], severity_levels: ['error', 'critical'] } }, security: { data_masking: { enabled: true, fields: ['phone', 'id_card'] }, audit_log: true, rate_limit: { requests_per_minute: 60, requests_per_hour: 1000 } }, performance: { enabled: true, metrics: ['response_time', 'success_rate'], auto_optimize: true } },
};
```

### 6.2 模板选择器交互

```
┌─────────────────────────────────────────┐
│  🚀 选择员工模板                          │
│                                         │
│  ○ 简单工作流员工                         │
│    适用：自动化任务编排                    │
│    包含：工作流关联                        │
│                                         │
│  ○ 对话型 Agent                          │
│    适用：智能客服、问答助手                │
│    包含：Agent 配置 + 上下文记忆           │
│                                         │
│  ○ 电话客服员工                          │
│    适用：电话接听、语音交互                │
│    包含：ASR/TTS + 声音克隆 + 知识库       │
│                                         │
│  ○ 数据处理员工                          │
│    适用：数据清洗、报表生成                │
│    包含：数据接入 + 处理技能 + 定时任务     │
│                                         │
│  ○ 全能型员工                            │
│    适用：复杂业务场景                      │
│    包含：全部模块                          │
│                                         │
│  ○ 空白模板                              │
│    适用：从零开始自定义                    │
│                                         │
│         [ 确认选择 ]                      │
└─────────────────────────────────────────┘
```

---

## 七、前端架构设计

### 7.1 组件结构

```
EmployeeAuthoringView/
├── EmployeeWizard.vue              # 向导主容器
│
├── steps/
│   ├── Step0_TemplateSelect.vue    # 模板选择（新增）
│   ├── Step1_Identity.vue          # 身份配置
│   ├── Step2_Perception.vue        # 感知配置（新增）
│   ├── Step3_Memory.vue            # 记忆配置（新增）
│   ├── Step4_Cognition.vue         # 认知配置（新增）
│   │   ├── AgentConfig.vue
│   │   ├── SkillSelector.vue
│   │   └── DecisionRules.vue
│   ├── Step5_Actions.vue           # 行动配置（新增）
│   │   ├── VoiceConfig.vue
│   │   ├── MessagingConfig.vue
│   │   └── APIConfig.vue
│   ├── Step6_Collaboration.vue     # 协作配置（原工作流）
│   ├── Step7_Management.vue        # 管理配置（新增）
│   ├── Step8_Testing.vue           # 测试与审核（保留）
│   └── Step9_Listing.vue           # 上架信息（保留）
│
├── components/
│   ├── StepNavigation.vue          # 步骤导航
│   ├── ModuleToggle.vue            # 模块开关
│   ├── SkillCard.vue               # 技能卡片
│   ├── VoicePreview.vue            # 声音试听
│   └── TestReport.vue              # 测试报告
│
└── composables/
    ├── useEmployeeWizard.ts        # 向导状态管理
    ├── useManifestMigration.ts     # Manifest 迁移
    └── useModuleValidation.ts      # 模块校验
```

### 7.2 状态管理

```typescript
// composables/useEmployeeWizard.ts
import { ref, computed } from 'vue'
import type { EmployeeConfig } from '@/types/employee'

export function useEmployeeWizard() {
  const currentStep = ref(0)
  const selectedTemplate = ref('')
  const config = ref<EmployeeConfig>({
    identity: { id: '', version: '1.0.0', artifact: 'employee_pack', name: '', description: '' },
  })
  const stepValidation = ref<Record<number, boolean>>({
    0: false, // 模板选择
    1: false, // 身份
    2: true,  // 感知（可选）
    3: true,  // 记忆（可选）
    4: false, // 认知
    5: true,  // 行动（可选）
    6: true,  // 协作（可选）
    7: true,  // 管理（可选）
    8: false, // 测试
    9: false, // 上架
  })
  
  const steps = [
    { id: 0, title: '选择模板', icon: '🚀', required: true },
    { id: 1, title: '基础信息', icon: '🆔', required: true },
    { id: 2, title: '感知能力', icon: '👁️', required: false },
    { id: 3, title: '记忆配置', icon: '💾', required: false },
    { id: 4, title: '认知能力', icon: '🧠', required: true },
    { id: 5, title: '行动能力', icon: '🖐️', required: false },
    { id: 6, title: '协作编排', icon: '🤝', required: false },
    { id: 7, title: '自我管理', icon: '🛡️', required: false },
    { id: 8, title: '测试审核', icon: '🧪', required: true },
    { id: 9, title: '上架发布', icon: '📦', required: true },
  ]
  
  function applyTemplate(templateId: string) {
    // 根据模板初始化配置
    selectedTemplate.value = templateId
    // ... 应用模板逻辑
  }
  
  function nextStep() {
    if (stepValidation.value[currentStep.value]) {
      currentStep.value++
    }
  }
  
  function prevStep() {
    if (currentStep.value > 0) {
      currentStep.value--
    }
  }
  
  return {
    currentStep,
    config,
    steps,
    stepValidation,
    applyTemplate,
    nextStep,
    prevStep,
  }
}
```

---

## 八、扩展示例

### 8.1 添加自定义 Skill

```typescript
// 定义新 Skill
const myCustomSkill: SkillConfig = {
  skill_id: 'email_sender',
  skill_name: '邮件发送器',
  version: '1.0.0',
  type: 'network_request',
  config: {
    smtp_host: 'smtp.example.com',
    smtp_port: 587,
    auth: {
      username_env: 'EMAIL_USER',
      password_env: 'EMAIL_PASS',
    },
  },
  enabled: true,
}

// 添加到员工配置
config.value.cognition?.skills.push(myCustomSkill)
```

### 8.2 配置定时任务

```typescript
// 添加定时报表任务
config.value.management = {
  scheduler: {
    enabled: true,
    jobs: [
      {
        job_id: 'daily_report',
        name: '每日报表',
        cron: '0 9 * * *',
        action: 'generate_daily_report',
        config: {
          format: 'pdf',
          recipients: ['manager@example.com'],
        },
      },
    ],
    event_triggers: ['file_uploaded', 'data_updated'],
  },
}
```

### 8.3 配置异常处理

```typescript
// 添加异常处理策略
config.value.management = {
  error_handling: {
    retry_policy: {
      max_retries: 3,
      backoff: 'exponential',
      initial_delay_ms: 1000,
    },
    fallback_strategy: 'human_handoff',
    alert: {
      enabled: true,
      channels: ['email', 'wechat'],
      severity_levels: ['error', 'critical'],
    },
  },
}
```

---

## 九、迁移指南

### 9.1 旧版员工迁移步骤

1. **备份现有员工包**
  ```bash
   cp -r mods/_employees/old_pack mods/_employees/old_pack_backup
  ```
2. **运行迁移工具**
  ```bash
   npm run migrate:employee -- --id old_pack --output new_manifest.json
  ```
3. **检查迁移结果**
  ```bash
   cat new_manifest.json | jq .
  ```
4. **测试新员工**
  - 上传新版员工包
  - 运行沙盒测试
  - 确认功能正常
5. **上架新版**
  - 填写商业化信息
  - 提交审核
  - 发布上架

### 9.2 自动化迁移脚本

```javascript
// scripts/migrate-manifest.js
import { readFileSync, writeFileSync } from 'fs'
import { upgradeManifest } from '../src/utils/manifestMigration.js'

const legacyManifest = JSON.parse(readFileSync('manifest.json', 'utf-8'))
const newConfig = upgradeManifest(legacyManifest)

writeFileSync('manifest-v2.json', JSON.stringify(newConfig, null, 2))
console.log('迁移完成！')
```

---

## 十、版本路线图

### Phase 1: 基础架构（当前）

- ✅ 完整类型定义
- ✅ 向后兼容策略
- ✅ 员工包结构规范
- ⏳ 前端向导组件

### Phase 2: 核心模块（1-2 个月）

- ⏳ Agent 配置模块
- ⏳ Skill 市场基础版
- ⏳ 知识库配置
- ⏳ 声音克隆集成

### Phase 3: 高级功能（3-4 个月）

- ⏳ 多模态感知
- ⏳ RPA 自动化
- ⏳ 定时调度
- ⏳ 异常处理框架

### Phase 4: 生态建设（5-6 个月）

- ⏳ Skill 市场完整版
- ⏳ 员工模板库
- ⏳ 性能监控面板
- ⏳ 自动化迁移工具

---

## 十一、总结

本架构框架实现了：

1. **类人化能力模型**: 感知→记忆→认知→行动→协作→管理，完整覆盖"数字员工"能力栈
2. **向后兼容**: 旧版员工包无需修改，运行时自动升级
3. **模块化设计**: 按需启用各能力模块，灵活组合
4. **类型安全**: 完整 TypeScript 定义 + JSON Schema 校验
5. **易扩展**: 开放 Skill、声音、知识库接入接口
6. **预设模板**: 5 种常用员工类型模板，开箱即用

基于此框架，你可以快速创建从简单工作流到全能员工的各类 AI 员工，无需担心兼容性问题，同时保留未来扩展的充足空间。