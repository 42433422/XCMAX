import { nextTick, ref, watch } from 'vue'
import { ApiError } from '@/api'
import chatApi from '@/api/chat'
import { BRAIN_AGENT_SESSION_KEY } from './brainStatic'

/** Agent 控制台对话逻辑（拆分自 BrainView.vue，逻辑不变） */
export function useBrainAgentChat({ pushActivity }) {
  const agentScrollRef = ref(null)
  const agentMessages = ref([])
  const agentInput = ref('')
  const agentSending = ref(false)
  const brainAgentSessionId = ref('')
  let brainAgentMsgSeq = 0

  function nextBrainAgentMsgId() {
    brainAgentMsgSeq += 1
    return `brain-agent-${brainAgentMsgSeq}`
  }

  function readBrainAgentSessionId() {
    try {
      const s = window.sessionStorage.getItem(BRAIN_AGENT_SESSION_KEY)
      return s && String(s).trim() ? String(s).trim() : ''
    } catch {
      return ''
    }
  }

  function persistBrainAgentSessionId(id) {
    try {
      if (id) window.sessionStorage.setItem(BRAIN_AGENT_SESSION_KEY, id)
    } catch {
      /* ignore */
    }
  }

  function scrollAgentConsoleToBottom() {
    const el = agentScrollRef.value
    if (el && typeof el.scrollTop === 'number') {
      el.scrollTop = el.scrollHeight
    }
  }

  function extractUnifiedChatReply(res) {
    if (!res || typeof res !== 'object') return ''
    if (typeof res.response === 'string') return res.response
    const d = res.data
    if (d && typeof d === 'object') {
      if (typeof d.response === 'string') return d.response
      if (typeof d.text === 'string') return d.text
      if (d.message && typeof d.message.content === 'string') return d.message.content
    }
    if (res.success === false && res.message) return `请求未成功：${res.message}`
    if (res.error) return `错误：${res.error}`
    return ''
  }

  function extractSessionIdFromChatResponse(res) {
    if (!res || typeof res !== 'object') return ''
    const d = res.data
    if (d && typeof d.session_id === 'string' && d.session_id.trim()) return d.session_id.trim()
    if (typeof res.session_id === 'string' && res.session_id.trim()) return res.session_id.trim()
    return ''
  }

  async function clearAgentChat() {
    agentMessages.value = []
    agentInput.value = ''
    brainAgentSessionId.value = ''
    try {
      window.sessionStorage.removeItem(BRAIN_AGENT_SESSION_KEY)
    } catch {
      /* ignore */
    }
    pushActivity('已清空智脑 Agent 对话')
    await initBrainAgentSession()
  }

  function onAgentComposerKeydown(e) {
    if (e.key !== 'Enter') return
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault()
      sendAgentMessage()
    }
  }

  async function sendAgentMessage() {
    const text = agentInput.value.trim()
    if (!text || agentSending.value) return
    agentSending.value = true
    agentMessages.value.push({ id: nextBrainAgentMsgId(), role: 'user', content: text })
    agentInput.value = ''
    await nextTick()
    scrollAgentConsoleToBottom()
    try {
      const payload = { message: text, source: 'brain_console' }
      const sid0 = brainAgentSessionId.value.trim()
      if (sid0) payload.session_id = sid0
      const res = await chatApi.sendUnifiedChat(payload)
      const reply = extractUnifiedChatReply(res)
      agentMessages.value.push({
        id: nextBrainAgentMsgId(),
        role: 'assistant',
        content: reply || '（空回复）'
      })
      const sid = extractSessionIdFromChatResponse(res)
      if (sid) {
        brainAgentSessionId.value = sid
        persistBrainAgentSessionId(sid)
      }
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : err instanceof Error ? err.message : '请求失败'
      agentMessages.value.push({
        id: nextBrainAgentMsgId(),
        role: 'assistant',
        content: `错误：${msg}`
      })
      pushActivity(`Agent 对话失败：${msg.slice(0, 80)}`)
    } finally {
      agentSending.value = false
      await nextTick()
      scrollAgentConsoleToBottom()
    }
  }

  watch(
    () => [agentMessages.value.length, agentSending.value],
    () => {
      nextTick(() => scrollAgentConsoleToBottom())
    }
  )

  async function initBrainAgentSession() {
    const existing = readBrainAgentSessionId()
    if (existing) {
      brainAgentSessionId.value = existing
      return
    }
    try {
      const r = await chatApi.newConversation({})
      const sid = r?.data?.session_id
      if (sid && String(sid).trim()) {
        brainAgentSessionId.value = String(sid).trim()
        persistBrainAgentSessionId(brainAgentSessionId.value)
      }
    } catch {
      /* 无会话时仍允许发 unified_chat */
    }
  }

  return {
    agentScrollRef,
    agentMessages,
    agentInput,
    agentSending,
    brainAgentSessionId,
    clearAgentChat,
    onAgentComposerKeydown,
    sendAgentMessage,
    initBrainAgentSession,
  }
}
