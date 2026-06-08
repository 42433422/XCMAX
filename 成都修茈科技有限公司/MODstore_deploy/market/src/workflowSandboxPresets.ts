export interface SandboxPreset {
  id: string
  label: string
  input_data: Record<string, unknown>
}

export const WORKFLOW_SANDBOX_PRESETS: SandboxPreset[] = [
  {
    id: 'minimal',
    label: '通用 · 空对象',
    input_data: {},
  },
  {
    id: 'topic',
    label: '通用 · topic 示例',
    input_data: { topic: '示例主题' },
  },
  {
    id: 'phone_wechat',
    label: '电话 / 渠道 · wechat 占位',
    input_data: {
      channel: 'wechat',
      topic: '来电意图识别',
      intent: 'answer',
      call_state: 'ringing',
    },
  },
  {
    id: 'flags',
    label: '通用 · 布尔分支占位',
    input_data: {
      approved: true,
      score: 0.85,
      retry_count: 0,
    },
  },
]

export function presetById(id: string): SandboxPreset | null {
  return WORKFLOW_SANDBOX_PRESETS.find((p) => p.id === id) || null
}
