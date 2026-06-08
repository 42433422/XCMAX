type EmployeeConfigRecord = Record<string, any>

const DEFAULT_IDENTITY = {
  id: '',
  version: '1.0.0',
  artifact: 'employee_pack',
  name: '',
  description: '',
}

function clone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v))
}

export function createEmptyEmployeeConfigV2(opts?: {
  model?: Partial<{ provider: string; model_name: string }>
}): EmployeeConfigRecord {
  const provider = String(opts?.model?.provider ?? '').trim() || 'auto'
  const model_name = String(opts?.model?.model_name ?? '').trim() || 'auto'
  return {
    identity: clone(DEFAULT_IDENTITY),
    perception: undefined,
    memory: undefined,
    cognition: {
      agent: {
        system_prompt: '',
        role: {
          name: '',
          persona: '',
          tone: 'professional',
          expertise: [],
        },
        behavior_rules: [],
        few_shot_examples: [],
        model: {
          provider,
          model_name,
          temperature: 0.7,
          max_tokens: 4000,
          top_p: 0.9,
        },
      },
      skills: [],
    },
    actions: undefined,
    collaboration: {
      workflow: {
        workflow_id: 0,
      },
    },
    management: undefined,
    commerce: undefined,
    workflow_employees: [],
    metadata: {
      framework_version: '2.0.0',
      created_by: 'employee_authoring_v2',
    },
  }
}

const TEMPLATE_MAP: Record<string, EmployeeConfigRecord> = {
  workflow: {},
  dialog: {
    memory: {
      short_term: { context_window: 8000, session_timeout: 1800, keep_history: true },
    },
  },
  phone: {
    perception: {
      audio: { enabled: true, asr: { enabled: true, languages: ['zh-CN'] } },
    },
    actions: {
      voice_output: {
        enabled: true,
        tts: { provider: 'aliyun', voice_name: '', sample_rate: 24000 },
      },
    },
  },
  data: {
    perception: {
      data_input: { enabled: true, api_sources: [] },
    },
    actions: {
      text_output: { enabled: true, formats: ['json', 'csv'] },
    },
  },
  full: {
    perception: {
      vision: { enabled: true, supported_formats: ['png', 'jpg'] },
      document: { enabled: true, supported_formats: ['pdf', 'docx'] },
    },
    memory: {
      short_term: { context_window: 16000, session_timeout: 3600, keep_history: true },
      long_term: {
        enabled: true,
        sources: [],
        retrieval: {
          strategy: 'hybrid',
          top_k: 5,
          similarity_threshold: 0.75,
          rerank_enabled: true,
        },
      },
    },
    actions: {
      text_output: { enabled: true, formats: ['text', 'json'] },
      messaging: { enabled: true, channels: [] },
    },
    management: {
      error_handling: {
        retry_policy: { max_retries: 3, backoff: 'exponential', initial_delay_ms: 1000 },
        fallback_strategy: 'human_handoff',
        alert: { enabled: true, channels: ['email'], severity_levels: ['error', 'critical'] },
      },
    },
  },
  blank: {
    cognition: undefined,
  },
}

export function applyTemplateV2(templateId: string): EmployeeConfigRecord {
  const base = createEmptyEmployeeConfigV2()
  const patch = TEMPLATE_MAP[templateId] || TEMPLATE_MAP.workflow
  return {
    ...base,
    ...clone(patch),
    identity: {
      ...base.identity,
      ...(patch.identity || {}),
    },
    collaboration: {
      ...base.collaboration,
      ...(patch.collaboration || {}),
      workflow: {
        ...(base.collaboration?.workflow || {}),
        ...(patch.collaboration?.workflow || {}),
      },
    },
  }
}

export function upgradeLegacyToV2(inputManifest: unknown = {}): EmployeeConfigRecord {
  const legacy: EmployeeConfigRecord =
    inputManifest && typeof inputManifest === 'object' ? (inputManifest as EmployeeConfigRecord) : {}
  const c = createEmptyEmployeeConfigV2()
  c.identity.id = String(legacy.id || '').trim()
  c.identity.version = String(legacy.version || '1.0.0').trim() || '1.0.0'
  c.identity.artifact = String(legacy.artifact || 'employee_pack').trim() || 'employee_pack'
  c.identity.name = String(legacy.name || '').trim()
  c.identity.description = String(legacy.description || '').trim()
  c.cognition.agent.system_prompt = String(legacy.panel_summary || '').trim()
  const wf = Array.isArray(legacy.workflow_employees) ? legacy.workflow_employees : []
  const first = wf[0] && typeof wf[0] === 'object' ? wf[0] : {}
  const wid = Number.parseInt(String(first.workflow_id ?? first.workflowId ?? 0), 10)
  c.collaboration.workflow.workflow_id = Number.isFinite(wid) && wid > 0 ? wid : 0
  c.workflow_employees = wf
  const price = Number(legacy?.commerce?.price)
  if (legacy.industry || Number.isFinite(price)) {
    c.commerce = {
      industry: String(legacy.industry || '通用').trim() || '通用',
      price: Number.isFinite(price) ? price : 0,
    }
  }
  c.metadata = {
    framework_version: '2.0.0',
    created_by: 'migration',
    migration_from: 'v1',
  }
  return c
}

export function validateEmployeeConfigV2(config: unknown): { valid: boolean; errors: string[] } {
  const errs: string[] = []
  const c: EmployeeConfigRecord = config && typeof config === 'object' ? (config as EmployeeConfigRecord) : {}
  if (!String(c?.identity?.id || '').trim()) errs.push('缺少 identity.id')
  if (!String(c?.identity?.name || '').trim()) errs.push('缺少 identity.name')
  if (!String(c?.identity?.version || '').trim()) errs.push('缺少 identity.version')
  const wid = Number.parseInt(String(c?.collaboration?.workflow?.workflow_id || 0), 10)
  if (!(Number.isFinite(wid) && wid > 0)) errs.push('工作流心脏必填：collaboration.workflow.workflow_id')
  const tone = String(c?.cognition?.agent?.role?.tone || '')
  if (tone && !['formal', 'friendly', 'professional', 'casual'].includes(tone)) {
    errs.push('role.tone 仅支持 formal/friendly/professional/casual')
  }
  const provider = String(c?.cognition?.agent?.model?.provider || '')
  if (
    provider &&
    !['deepseek', 'openai', 'anthropic', 'local', 'auto'].includes(provider)
  ) {
    errs.push('model.provider 仅支持 deepseek/openai/anthropic/local/auto')
  }
  const model = c?.cognition?.agent?.model || {}
  const temp = Number(model.temperature)
  if (Number.isFinite(temp) && (temp < 0 || temp > 1)) errs.push('model.temperature 需在 0~1')
  const topP = Number(model.top_p)
  if (Number.isFinite(topP) && (topP < 0 || topP > 1)) errs.push('model.top_p 需在 0~1')
  const maxTokens = Number(model.max_tokens)
  if (Number.isFinite(maxTokens) && maxTokens <= 0) errs.push('model.max_tokens 需大于 0')
  const rules = c?.cognition?.agent?.behavior_rules
  if (rules != null && !Array.isArray(rules)) errs.push('behavior_rules 必须是数组')
  const examples = c?.cognition?.agent?.few_shot_examples
  if (examples != null && !Array.isArray(examples)) errs.push('few_shot_examples 必须是数组')
  const access = String(c?.collaboration?.permissions?.access_level || '')
  if (access && !['read_only', 'read_write', 'admin'].includes(access)) {
    errs.push('permissions.access_level 仅支持 read_only/read_write/admin')
  }
  if (c?.perception?.audio?.asr?.enabled && !c?.actions?.voice_output) {
    errs.push('启用 ASR 需要配置 actions.voice_output')
  }
  if (c?.memory?.long_term?.enabled && !c?.cognition?.agent) {
    errs.push('启用知识库需要配置 cognition.agent')
  }
  return { valid: errs.length === 0, errors: errs }
}
