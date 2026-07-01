/**
 * 会话本地持久化（localStorage 优先，失败时退回内存）。
 * - 仅做一档「直接对话」的会话；二档/三档独立。
 * - 数据结构与豆包 / ChatGPT 类似：conversations[]（含 messages[]）+ activeId。
 * - 不做云端同步；后续接 /api/llm/conversations 时只需替换 io 层即可。
 */

export interface ChatAttachmentMeta {
  name: string
  size: number
  status: 'ready' | 'inline' | 'error' | 'skipped' | 'uploading'
  docId?: string
  kind?: 'vision' | 'file'
}

/** OpenAI-compatible multimodal user message parts（与 /api/llm/chat 对齐）。 */
export type ChatMultimodalPart =
  | { type: 'text'; text: string }
  | { type: 'image_url'; image_url: { url: string } }

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  /** 存在时优先作为发给 LLM 的 user.content（可与纯文本 content 并存用于展示）。 */
  multimodalContent?: ChatMultimodalPart[]
  createdAt: number
  reasoning?: string
  attachments?: ChatAttachmentMeta[]
  citations?: Array<{ title: string; url?: string; snippet?: string }>
  imageUrls?: string[]
  feedback?: 'up' | 'down' | null
  pending?: boolean
  error?: string
  skills?: string[]
  agentId?: string
  agentLabel?: string
  /** 员工 execute-file 成功后由服务端返回的可下载产物（GET /api/employees/downloads/…，需 Bearer）。 */
  outputDownloads?: Array<{ jobId: string; filename: string; label?: string }>
}

export interface Conversation {
  id: string
  title: string
  createdAt: number
  updatedAt: number
  pinned: boolean
  messages: ChatMessage[]
  agentId?: string
  agentLabel?: string
}

const STORAGE_KEY = 'workbench_direct_conversations_v1'
const ACTIVE_KEY = 'workbench_direct_active_v1'
const MAX_CONVS = 100
const MAX_MSGS_PER_CONV = 400

function newId(prefix = 'c'): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    try {
      return `${prefix}_${crypto.randomUUID()}`
    } catch {
      /* fallthrough */
    }
  }
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`
}

function safeRead<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return fallback
    return JSON.parse(raw) as T
  } catch {
    return fallback
  }
}

function safeWrite(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* 配额超限时静默吞掉 */
  }
}

export function loadConversations(): Conversation[] {
  const raw = safeRead<Conversation[]>(STORAGE_KEY, [])
  if (!Array.isArray(raw)) return []
  return raw
    .filter((c) => c && typeof c.id === 'string' && Array.isArray(c.messages))
    .map((c) => ({
      id: c.id,
      title: String(c.title || '新对话'),
      createdAt: Number(c.createdAt) || Date.now(),
      updatedAt: Number(c.updatedAt) || Date.now(),
      pinned: Boolean(c.pinned),
      messages: c.messages.slice(0, MAX_MSGS_PER_CONV),
      agentId: c.agentId,
      agentLabel: c.agentLabel,
    }))
    .sort((a, b) => {
      if (a.pinned !== b.pinned) return a.pinned ? -1 : 1
      return b.updatedAt - a.updatedAt
    })
    .slice(0, MAX_CONVS)
}

export function saveConversations(list: Conversation[]): void {
  const trimmed = list
    .slice()
    .sort((a, b) => {
      if (a.pinned !== b.pinned) return a.pinned ? -1 : 1
      return b.updatedAt - a.updatedAt
    })
    .slice(0, MAX_CONVS)
    .map((c) => ({ ...c, messages: c.messages.slice(-MAX_MSGS_PER_CONV) }))
  safeWrite(STORAGE_KEY, trimmed)
}

export function loadActiveId(): string {
  return safeRead<string>(ACTIVE_KEY, '')
}

export function saveActiveId(id: string): void {
  safeWrite(ACTIVE_KEY, id || '')
}

export function createConversation(opts?: { title?: string; agentId?: string; agentLabel?: string }): Conversation {
  const now = Date.now()
  return {
    id: newId('conv'),
    title: opts?.title || '新对话',
    createdAt: now,
    updatedAt: now,
    pinned: false,
    messages: [],
    agentId: opts?.agentId,
    agentLabel: opts?.agentLabel,
  }
}

export function makeMessage(role: ChatMessage['role'], content: string, extra: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: newId('msg'),
    role,
    content,
    createdAt: Date.now(),
    ...extra,
  }
}

/** 侧栏/列表展示的短标题（带省略号） */
export function summarizeForTitle(text: string, maxLen = 28): string {
  const s = String(text || '').replace(/\s+/g, ' ').trim()
  if (!s) return '新对话'
  if (s.length <= maxLen) return s
  const cut = s.slice(0, maxLen)
  const lastSpace = cut.lastIndexOf(' ')
  if (lastSpace > Math.floor(maxLen * 0.45)) return `${cut.slice(0, lastSpace)}…`
  return `${cut}…`
}

/** 会话持久化标题（首轮用户问题，保留更完整文案供 tooltip） */
export function buildConversationTitle(text: string, maxLen = 48): string {
  const s = String(text || '').replace(/\s+/g, ' ').trim()
  if (!s) return '新对话'
  if (s.length <= maxLen) return s
  const cut = s.slice(0, maxLen)
  const lastSpace = cut.lastIndexOf(' ')
  if (lastSpace > Math.floor(maxLen * 0.5)) return `${cut.slice(0, lastSpace)}…`
  return `${cut}…`
}

export function exportConversationAsMarkdown(c: Conversation): string {
  const head = `# ${c.title}\n\n_导出时间：${new Date().toLocaleString()}_\n\n---\n\n`
  const body = c.messages
    .map((m) => {
      const role = m.role === 'user' ? '**你**' : m.role === 'assistant' ? '**AI**' : '**系统**'
      return `${role}\n\n${m.content}\n`
    })
    .join('\n---\n\n')
  return head + body
}

/** 主区消息为空但 storage 中该会话有记录时，应从 storage 重新加载列表。 */
export function shouldReloadConversationFromStorage(
  uiMessageCount: number,
  storageMessages: ChatMessage[] | undefined,
): boolean {
  return uiMessageCount === 0 && (storageMessages?.length ?? 0) > 0
}

/** 侧栏选中会话时合并内存列表与 storage（Vitest / 双通道 pick 共用）。 */
export function mergeConversationsForPick(
  memoryList: Conversation[],
  storageList: Conversation[],
  conversationId: string,
  uiMessageCount: number,
): Conversation[] {
  const fresh = storageList.find((c) => c.id === conversationId)
  if (shouldReloadConversationFromStorage(uiMessageCount, fresh?.messages)) {
    return storageList
  }
  const inMemory = memoryList.find((c) => c.id === conversationId)
  if (inMemory && inMemory.messages.length > 0) return memoryList
  if (fresh) return storageList
  return memoryList
}

export function searchConversations(list: Conversation[], q: string): Conversation[] {
  const kw = String(q || '').trim().toLowerCase()
  if (!kw) return list
  return list.filter((c) => {
    if (c.title.toLowerCase().includes(kw)) return true
    return c.messages.some((m) => m.content.toLowerCase().includes(kw))
  })
}
