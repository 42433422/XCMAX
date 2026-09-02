// AI 数字管家域端点（自 legacyMonolith.ts 拆分，方法体保持不变）
import { authHeaders, req } from './shared'

export const butlerEndpoints = {
  // ─── AI 数字管家 Butler ─────────────────────────────────────────────
  /** POST /api/agent/butler/corp-chat — 官网公开咨询（无需登录） */
  agentCorpChat: (payload: {
    messages: Array<{ role: string; content: unknown }>
    page_id?: string
    page_context?: string
    max_tokens?: number
    visitor_id?: string
    visitor_label?: string
  }) =>
    req('/api/agent/butler/corp-chat', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** POST /api/agent/butler/chat — 发送对话（非流式） */
  agentButlerChat: (payload: {
    messages: unknown[]
    conversation_id?: number | null
    page_context?: string
  }) =>
    req('/api/agent/butler/chat', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** POST /api/agent/butler/chat/stream — SSE 流式对话 */
  agentButlerChatStream: (
    payload: {
      messages: unknown[]
      conversation_id?: number | null
      page_context?: string
    },
    signal?: AbortSignal,
  ) => {
    const headers = new Headers(authHeaders())
    headers.set('Content-Type', 'application/json')
    headers.set('Accept', 'text/event-stream')
    return fetch('/api/agent/butler/chat/stream', {
      method: 'POST',
      headers,
      signal,
      body: JSON.stringify(payload),
    })
  },

  /** GET /api/agent/butler/skills — 获取 butler 类型的技能列表 */
  listButlerSkills: () => req('/api/agent/butler/skills'),

  /** POST /api/agent/butler/actions — 记录操作审计 */
  recordButlerAction: (payload: {
    route: string
    action: string
    args?: Record<string, unknown>
    risk: string
    status: 'success' | 'failed' | 'cancelled'
  }) =>
    req('/api/agent/butler/actions', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** PATCH /api/agent/butler/skills/:id — 更新技能激活状态 */
  updateButlerSkillActive: (id: number | string, isActive: boolean) =>
    req(`/api/agent/butler/skills/${encodeURIComponent(String(id))}`, {
      method: 'PATCH',
      body: JSON.stringify({ is_active: isActive }),
    }),

  /**
   * POST /api/agent/butler/orchestrate — 启动 vibe-coding 改写管线。
   * 返回 { session_id, status }，进度通过 workbenchGetSession 轮询。
   */
  butlerOrchestrateStart: (payload: {
    target_type: 'mod' | 'workflow' | 'employee'
    target_id: string
    brief: string
    scope?: string
    focus_paths?: string[]
    with_snapshot?: boolean
    provider?: string
    model?: string
  }) =>
    req('/api/agent/butler/orchestrate', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /**
   * POST /api/agent/butler/all-hands-report — 数字管家召集全员汇报（管理员）。
   * 让每个在岗员工自己讲：① 文件架构与工作逻辑 ② 最近问题与解决 ③ 联网+GitHub 调研后的自我优化（含联动）。
   * 返回结构化 JSON（每岗一段固定 4 节 Markdown）；阻塞至全部完成（`concurrency` 决定快慢）。
   */
  butlerAllHandsReportStartSession: (payload: {
    employee_ids?: string[]
    with_research?: boolean
    max_employees?: number
    concurrency?: number
    user_question?: string
    synthesize?: boolean
  }) =>
    req('/api/agent/butler/all-hands-report/sessions', {
      method: 'POST',
      body: JSON.stringify(payload || {}),
    }),

  /**
   * 同步版：等待全员汇报完成后一次性返回。
   * 如果前置网关超时较短，建议优先使用 butlerAllHandsReportStartSession + workbenchGetSession 轮询。
   */
  butlerAllHandsReport: (payload: {
    employee_ids?: string[]
    with_research?: boolean
    max_employees?: number
    concurrency?: number
    user_question?: string
    synthesize?: boolean
  }) =>
    req('/api/agent/butler/all-hands-report', {
      method: 'POST',
      body: JSON.stringify(payload || {}),
    }),
}
