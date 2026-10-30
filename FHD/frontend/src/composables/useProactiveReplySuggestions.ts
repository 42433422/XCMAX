import { ref, watch, type Ref } from 'vue'
import { apiFetch } from '@/utils/apiBase'

export const PROACTIVE_SUGGESTIONS_STORAGE_KEY = 'xcagi_proactive_suggestions'

export type ProactiveSuggestion = {
  id: string
  text: string
}

type ChatLikeMessage = {
  role?: string
  type?: string
  content?: string
  text?: string
}

function readEnabled(): boolean {
  try {
    return localStorage.getItem(PROACTIVE_SUGGESTIONS_STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

function writeEnabled(enabled: boolean): void {
  try {
    localStorage.setItem(PROACTIVE_SUGGESTIONS_STORAGE_KEY, enabled ? '1' : '0')
  } catch {
    /* ignore quota */
  }
}

function messageText(m: ChatLikeMessage): string {
  return String(m.content || m.text || '').trim()
}

function isAssistant(m: ChatLikeMessage): boolean {
  const role = String(m.role || m.type || '').toLowerCase()
  return role === 'assistant' || role === 'ai' || role === 'bot'
}

function isUser(m: ChatLikeMessage): boolean {
  const role = String(m.role || m.type || '').toLowerCase()
  return role === 'user' || role === 'human'
}

/** Local heuristic fallback — never auto-executes; user must pick then send. */
export function buildLocalProactiveSuggestions(messages: ChatLikeMessage[]): ProactiveSuggestion[] {
  const recent = (messages || []).slice(-8)
  const lastAi = [...recent].reverse().find(isAssistant)
  const lastUser = [...recent].reverse().find(isUser)
  const aiText = lastAi ? messageText(lastAi) : ''
  const userText = lastUser ? messageText(lastUser) : ''

  const out: string[] = []
  if (/导入|excel|表格|映射/i.test(aiText + userText)) {
    out.push('请帮我核对导入字段后再写入')
    out.push('先只预览，不要写入数据库')
    out.push('说明一下哪些列还缺映射')
  } else if (/打印|发货|出货|标签/i.test(aiText + userText)) {
    out.push('按刚才的方案开始打印前再确认一次')
    out.push('先列出待打印单据清单')
    out.push('改用另一台打印机重试')
  } else if (/客户|订单|开单/i.test(aiText + userText)) {
    out.push('帮我补全客户信息后再开单')
    out.push('先生成草稿，我确认后再提交')
    out.push('总结当前订单还缺哪些必填项')
  } else if (aiText) {
    const clip = aiText.replace(/\s+/g, ' ').slice(0, 24)
    out.push(`请就「${clip}${aiText.length > 24 ? '…' : ''}」继续说明下一步`)
    out.push('帮我总结刚才的要点成三条')
    out.push('按你的建议给出可复制的操作步骤（先不要自动执行）')
  } else {
    out.push('请继续说明下一步怎么做')
    out.push('帮我总结刚才的要点')
    out.push('给出三个可选操作，我选一个再继续')
  }

  while (out.length < 3) {
    out.push(['请继续', '换个说法再讲一遍', '先列清单再执行'][out.length] || '请继续')
  }

  return out.slice(0, 3).map((text, i) => ({ id: `local-${i}-${text.slice(0, 8)}`, text }))
}

async function fetchAiProactiveSuggestions(messages: ChatLikeMessage[], signal: AbortSignal): Promise<ProactiveSuggestion[] | null> {
  const recent = (messages || []).slice(-6).map((m) => ({
    role: isUser(m) ? 'user' : isAssistant(m) ? 'assistant' : 'system',
    content: messageText(m).slice(0, 500),
  })).filter((m) => m.content)
  if (!recent.length) return null

  const prompt =
    '根据当前对话，给出用户接下来可能回复或想做的三件事。' +
    '只返回 JSON 数组，恰好 3 条中文字符串，不要执行任何工具，不要编号外的说明。'

  try {
    const response = await apiFetch('/api/ai/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: prompt,
        messages: recent,
        stream: false,
        mode: 'proactive_suggestions',
        max_tokens: 200,
      }),
      signal,
      timeoutMs: 8_000,
    })
    if (!response.ok) return null
    const raw = await response.text()
    let data: Record<string, unknown> | null = null
    try {
      data = raw ? JSON.parse(raw) : null
    } catch {
      return null
    }
    const candidates: unknown[] = []
    const reply = String((data as any)?.data?.reply || (data as any)?.reply || (data as any)?.data?.text || (data as any)?.message || raw || '')
    const jsonMatch = reply.match(/\[[\s\S]*\]/)
    if (jsonMatch) {
      try {
        const arr = JSON.parse(jsonMatch[0])
        if (Array.isArray(arr)) candidates.push(...arr)
      } catch {
        /* fall through */
      }
    }
    if (!candidates.length && Array.isArray((data as any)?.data?.suggestions)) {
      candidates.push(...((data as any).data.suggestions as unknown[]))
    }
    const texts = candidates.map((c) => String(c || '').trim()).filter(Boolean).slice(0, 3)
    if (texts.length < 3) return null
    return texts.map((text, i) => ({ id: `ai-${i}-${text.slice(0, 8)}`, text }))
  } catch {
    return null
  }
}

export interface UseProactiveReplySuggestionsDeps {
  messages: Ref<ChatLikeMessage[]>
  messageInput: Ref<string>
  /** When false, clear chips and do not fetch. */
  enabled?: Ref<boolean>
}

/**
 * 「主动意识启用」：基于当前对话给出三条可能的下一步回复/动作；
 * 用户点选后填入输入框，**绝不自动发送或执行**。
 * Storage: xcagi_proactive_suggestions（与星标微信 xcagi_auto_refresh_starred_wechat 隔离）。
 */
export function useProactiveReplySuggestions(deps: UseProactiveReplySuggestionsDeps) {
  const enabled = deps.enabled || ref(readEnabled())
  if (!deps.enabled) {
    // Keep local ref in sync if caller did not pass one.
    enabled.value = readEnabled()
  }
  const suggestions = ref<ProactiveSuggestion[]>([])
  const loading = ref(false)
  let abort: AbortController | null = null
  let gen = 0

  function persistEnabled(next: boolean) {
    enabled.value = next
    writeEnabled(next)
    // Explicitly do NOT touch xcagi_auto_refresh_starred_wechat / wechat polling events.
  }

  function clearSuggestions() {
    suggestions.value = []
  }

  async function refreshSuggestions() {
    if (!enabled.value) {
      clearSuggestions()
      return
    }
    const token = ++gen
    abort?.abort()
    abort = new AbortController()
    loading.value = true
    try {
      const ai = await fetchAiProactiveSuggestions(deps.messages.value || [], abort.signal)
      if (token !== gen) return
      suggestions.value = ai && ai.length >= 3 ? ai : buildLocalProactiveSuggestions(deps.messages.value || [])
    } finally {
      if (token === gen) loading.value = false
    }
  }

  /** Apply chosen suggestion into the composer only — never auto-send. */
  function pickSuggestion(item: ProactiveSuggestion | string) {
    const text = typeof item === 'string' ? item : item.text
    const trimmed = String(text || '').trim()
    if (!trimmed) return
    const existing = deps.messageInput.value.trimEnd()
    deps.messageInput.value = existing ? `${existing}\n${trimmed}` : trimmed
    const input = document.getElementById('messageInput') as HTMLTextAreaElement | null
    input?.focus()
  }

  watch(
    enabled,
    (on) => {
      if (!on) {
        abort?.abort()
        clearSuggestions()
        return
      }
      void refreshSuggestions()
    },
    { immediate: true },
  )

  watch(
    () => {
      const list = deps.messages.value || []
      const last = list[list.length - 1]
      return `${list.length}:${messageText(last || {})}:${String(last?.role || last?.type || '')}`
    },
    () => {
      if (!enabled.value) return
      // Debounce lightly via microtask batching of rapid stream updates.
      window.setTimeout(() => {
        void refreshSuggestions()
      }, 400)
    },
  )

  return {
    proactiveEnabled: enabled,
    proactiveSuggestions: suggestions,
    proactiveLoading: loading,
    persistProactiveEnabled: persistEnabled,
    pickProactiveSuggestion: pickSuggestion,
    refreshProactiveSuggestions: refreshSuggestions,
    PROACTIVE_SUGGESTIONS_STORAGE_KEY,
  }
}

export { readEnabled as isProactiveSuggestionsEnabled }
