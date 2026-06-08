/**
 * 字段级 AI 助手。
 *
 * 暴露 assist(field, kind, value) → patch，用于 Inspector 面板每个字段旁的
 * "AI 优化" 按钮：refine-prompt / suggest-skills / explain。
 */

import { ref } from 'vue'
import { api } from '../api'
import { getAccessToken } from '../infrastructure/storage/tokenStore'

export type FieldAiKind = 'refine-prompt' | 'suggest-skills' | 'explain' | 'generate-identity'

export interface FieldAiResult {
  value: string
  explanation?: string
  suggestions?: unknown[]
}

export function useFieldAi() {
  const loading = ref(false)
  const error = ref('')

  async function assist(
    kind: FieldAiKind,
    value: string,
    ctx?: {
      roleContext?: string
      instruction?: string
      provider?: string
      model?: string
    },
  ): Promise<FieldAiResult | null> {
    loading.value = true
    error.value = ''
    try {
      if (kind === 'refine-prompt') {
        const res = await api.refineSystemPrompt({
          current_prompt: value,
          instruction: ctx?.instruction || '请优化这段 system prompt，使其更专业、更清晰',
          role_context: ctx?.roleContext,
          provider: ctx?.provider,
          model: ctx?.model,
        }) as Record<string, unknown>
        return {
          value: String(res?.improved_prompt || value),
          explanation: String(res?.diff_explanation || ''),
        }
      }

      if (kind === 'explain') {
        // Lightweight: use chat stream for a single completion
        const explanation = await singleChatCompletion(
          `请用一句话说明这段配置的作用：\n${value}`,
        )
        return { value, explanation }
      }

      return { value }
    } catch (e: unknown) {
      error.value = (e as Error)?.message || String(e)
      return null
    } finally {
      loading.value = false
    }
  }

  return { assist, loading, error }
}

async function singleChatCompletion(prompt: string): Promise<string> {
  const token = getAccessToken()
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers['Authorization'] = `Bearer ${token}`

  const resp = await fetch('/api/llm/chat/stream', {
    method: 'POST',
    headers,
    body: JSON.stringify({ messages: [{ role: 'user', content: prompt }], stream: false }),
  })
  if (!resp.ok) return ''
  const data = (await resp.json()) as { choices?: Array<{ message?: { content?: string } }>; content?: string }
  const choices = data?.choices
  return String(choices?.[0]?.message?.content ?? data?.content ?? '')
}
