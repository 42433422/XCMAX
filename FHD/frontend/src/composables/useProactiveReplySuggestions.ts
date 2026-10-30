import { ref, watch, type Ref } from 'vue'

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

export interface UseProactiveReplySuggestionsDeps {
  messages: Ref<ChatLikeMessage[]>
  messageInput: Ref<string>
  enabled?: Ref<boolean>
  isLoading?: Ref<boolean>
  scopeKey?: Ref<string>
}

/** Suggestions stay local; choosing one only fills the composer. */
export function useProactiveReplySuggestions(deps: UseProactiveReplySuggestionsDeps) {
  const enabled = deps.enabled || ref(readEnabled())
  const suggestions = ref<ProactiveSuggestion[]>([])
  const loading = ref(false)

  function refreshSuggestions() {
    suggestions.value = enabled.value && !deps.isLoading?.value
      && deps.messages.value.some(isAssistant)
      ? buildLocalProactiveSuggestions(deps.messages.value) : []
  }

  function persistEnabled(next: boolean) {
    enabled.value = next
    writeEnabled(next)
  }

  function pickSuggestion(item: ProactiveSuggestion | string) {
    if (!enabled.value) return
    const text = (typeof item === 'string' ? item : item.text).trim()
    if (!text) return
    const existing = deps.messageInput.value.trimEnd()
    deps.messageInput.value = existing ? `${existing}\n${text}` : text
    document.getElementById('messageInput')?.focus()
  }

  watch([enabled, () => deps.isLoading?.value, () => {
    const list = deps.messages.value
    const last = list[list.length - 1]
    return `${list.length}:${messageText(last || {})}:${last?.role || last?.type || ''}`
  }], refreshSuggestions, { immediate: true })
  watch(() => deps.scopeKey?.value, () => { suggestions.value = [] }, { flush: 'sync' })

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
