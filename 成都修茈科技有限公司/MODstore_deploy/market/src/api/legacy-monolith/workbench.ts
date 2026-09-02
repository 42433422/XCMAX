// 工作台会话 / TTS 域端点（自 legacyMonolith.ts 拆分，方法体保持不变）
import { requestBlob, requestStreamBlob } from '../../infrastructure/http/client'
import { req } from './shared'

export const workbenchEndpoints = {
  workbenchResearchContext: (body: unknown) => req('/api/workbench/research-context', { method: 'POST', body: JSON.stringify(body) }),
  workbenchStartSession: (body: unknown) => req('/api/workbench/sessions', { method: 'POST', body: JSON.stringify(body) }),
  workbenchStartSessionWithFiles: (body: unknown, files: File[]) => {
    const fd = new FormData()
    fd.append('metadata', JSON.stringify(body || {}))
    for (const f of files || []) fd.append('files', f)
    return req('/api/workbench/sessions', { method: 'POST', body: fd })
  },
  /**
   * 工作台三档对话中的即席文件处理（Canvas Skill 模式）。
   * 轮询方式，结果通过 workbenchGetSession 查询，不持久化到数据库。
   *
   * ⚠️ 与 /api/script-workflows/sessions（SSE）是两条独立产品线：
   *   - workbenchStartScriptSession → 即席、一次性、在工作台内完成
   *   - /api/script-workflows/sessions → ScriptWorkflowComposerView 中创建可复用的命名工作流，结果持久化到 script_workflows 表
   */
  workbenchStartScriptSession: (metadata: unknown, files: File[]) => {
    const fd = new FormData()
    fd.append('metadata', JSON.stringify(metadata || {}))
    for (const f of files || []) fd.append('files', f)
    return req('/api/workbench/script-sessions', { method: 'POST', body: fd })
  },
  workbenchGetSession: (sessionId: string) => req(`/api/workbench/sessions/${encodeURIComponent(sessionId)}`),
  workbenchRetrySession: (sessionId: string) => req<{ session_id?: string; status?: string }>(`/api/workbench/sessions/${encodeURIComponent(sessionId)}/retry`, { method: 'POST' }),

  /**
   * 启动 6 阶段 AI 员工生成流水线（SSE）。
   * 推荐使用 `useAgentLoop().runEmployeeDraft()`（Bearer + Pinia 流水线快照 + EmployeeAiDraftReview）。
   * SSE `data:` 行 JSON 字段 `event` 取值包括但不限于：
   * stage_start | stage_progress | stage_done | stage_error | pipeline_done | pipeline_error
   * 对话审核扩展（可选，后端实现）：review_reply | clarification_question（正文可用 message 或 content）。
   * 审核上行（可选）：POST /api/workbench/employee-ai/draft/review-chat body `{ message, run_id }`。
   * 与 workbenchStartSession/workbenchGetSession（轮询）完全独立。
   */
  streamEmployeeAiDraft: (
    brief: string,
    opts?: { provider?: string; model?: string; suggestedId?: string },
  ): Promise<Response> =>
    fetch('/api/workbench/employee-ai/draft', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        brief,
        provider: opts?.provider || undefined,
        model: opts?.model || undefined,
        suggested_id: opts?.suggestedId || undefined,
      }),
    }),

  /** LLM 优化 system prompt，返回 {improved_prompt, diff_explanation}。 */
  refineSystemPrompt: (body: {
    current_prompt: string
    instruction: string
    role_context?: string
    provider?: string
    model?: string
  }) =>
    req('/api/workbench/employee-ai/refine-prompt', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  /** 微软在线神经 TTS（服务端 edge-tts），返回 MP3 Blob */
  workbenchEdgeTts: (text: string, voice?: string, rate?: number) =>
    requestBlob('/api/workbench/tts/edge', {
      method: 'POST',
      body: JSON.stringify({
        text,
        ...(voice ? { voice } : {}),
        ...(rate != null && Number.isFinite(rate) ? { rate } : {}),
      }),
    }),

  /** 微软在线神经 TTS 流式（chunked MP3） */
  workbenchEdgeTtsStream: (text: string, voice?: string, rate?: number) =>
    requestStreamBlob('/api/workbench/tts/edge/stream', {
      method: 'POST',
      body: JSON.stringify({
        text,
        ...(voice ? { voice } : {}),
        ...(rate != null && Number.isFinite(rate) ? { rate } : {}),
      }),
    }),
}
