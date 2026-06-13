export type CommandIntentType = 'sales_contract' | 'price_list' | 'start_print'

export type CommandHandlerKey =
  | 'handleSalesContractCommand'
  | 'handlePriceListCommand'
  | 'handleStartPrintCommand'

export interface CommandIntentMatch {
  intent: CommandIntentType
  handlerKey: CommandHandlerKey
}

export interface CommandBufferEntry extends CommandIntentMatch {
  normalizedText: string
  hitCount: number
  createdAt: number
  lastUsedAt: number
}

export interface CommandBufferHit extends CommandIntentMatch {
  normalizedText: string
  strategy: 'exact' | 'contains'
  cachedEntry: CommandBufferEntry
}

const COMMAND_BUFFER_STORAGE_KEY = 'xcagi_command_buffer_v1'
const COMMAND_BUFFER_LIMIT = 200
/** 超过未使用的条目视为过期，避免长期运行 localStorage 只增不减 */
const COMMAND_BUFFER_ENTRY_TTL_MS = 30 * 24 * 60 * 60 * 1000
const START_PRINT_COMMAND_RE = /^开始打印(?:吧|一下)?$/
const COMMAND_VERBS = [
  '打印',
  '生成',
  '创建',
  '更新',
  '修改',
  '调整',
  '刷新',
  '打一下',
  '打一份',
  '打一个',
  '打',
  '开一份',
  '开一个',
  '开'
]
const INTENT_TOKENS = [
  '销售合同',
  '价格表',
  '报价表',
  '价目表',
  '开始打印',
  '打印',
  '生成',
  '创建',
  '更新',
  '修改',
  '调整',
  '刷新',
  '打一下',
  '打一个',
  '打一份',
  '打',
  '开一份',
  '开一个',
  '开'
]

function canUseStorage(): boolean {
  return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined'
}

export function normalizeCommandText(raw: string): string {
  return String(raw || '')
    .trim()
    .toLowerCase()
    .replace(/[，、；：。！？]/g, ' ')
    .replace(/[“”‘’"'`]/g, '')
    .replace(/\s+/g, ' ')
    .replace(/(^\s+|\s+$)/g, '')
}

function containsAnyVerb(text: string): boolean {
  return COMMAND_VERBS.some((k) => text.includes(k))
}

function extractMatchTokens(text: string): string[] {
  const tokens = new Set<string>()
  const raw = String(text || '').trim().toLowerCase()
  if (!raw) return []
  for (const t of INTENT_TOKENS) {
    if (raw.includes(t)) tokens.add(t)
  }
  const wordMatches = raw.match(/[a-z0-9]+/gi) || []
  for (const t of wordMatches) {
    if (t.length >= 2) tokens.add(t)
  }
  return Array.from(tokens)
}

function tokenSimilarity(a: string, b: string): number {
  const ta = extractMatchTokens(a)
  const tb = extractMatchTokens(b)
  if (!ta.length || !tb.length) return 0
  const sa = new Set(ta)
  const sb = new Set(tb)
  let overlap = 0
  for (const t of sa) {
    if (sb.has(t)) overlap += 1
  }
  const denom = Math.max(sa.size, sb.size)
  if (!denom) return 0
  return overlap / denom
}

export function isSalesContractCommandText(message: string): boolean {
  const text = String(message || '').trim()
  if (!text) return false
  if (!text.includes('销售合同')) return false
  return containsAnyVerb(text)
}

/** 与口语「报价表」「价目表」对齐，避免只写「价格表」才走本地价表逻辑。 */
function hasPriceListDocKeyword(text: string): boolean {
  return (
    text.includes('价格表') ||
    text.includes('报价表') ||
    text.includes('价目表')
  )
}

export function isPriceListCommandText(message: string): boolean {
  const text = String(message || '').trim()
  if (!text) return false
  if (!hasPriceListDocKeyword(text)) return false
  return containsAnyVerb(text)
}

export function detectIntentByRegex(message: string): CommandIntentMatch | null {
  const text = String(message || '').trim()
  if (!text) return null
  if (START_PRINT_COMMAND_RE.test(text)) {
    return { intent: 'start_print', handlerKey: 'handleStartPrintCommand' }
  }
  if (isSalesContractCommandText(text)) {
    return { intent: 'sales_contract', handlerKey: 'handleSalesContractCommand' }
  }
  if (isPriceListCommandText(text)) {
    return { intent: 'price_list', handlerKey: 'handlePriceListCommand' }
  }
  return null
}

function safeParseEntries(raw: string | null): CommandBufferEntry[] {
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
      .map((x: unknown) => ({
        intent: x?.intent,
        handlerKey: x?.handlerKey,
        normalizedText: String(x?.normalizedText || ''),
        hitCount: Number(x?.hitCount || 0),
        createdAt: Number(x?.createdAt || 0),
        lastUsedAt: Number(x?.lastUsedAt || 0)
      }))
      .filter((x: CommandBufferEntry) =>
        !!x.intent &&
        !!x.handlerKey &&
        !!x.normalizedText
      )
  } catch {
    return []
  }
}

function dropStaleEntries(entries: CommandBufferEntry[]): CommandBufferEntry[] {
  const now = Date.now()
  return entries.filter((x) => {
    const ref = Number(x.lastUsedAt || x.createdAt || 0)
    return ref > 0 && now - ref <= COMMAND_BUFFER_ENTRY_TTL_MS
  })
}

export function compactBuffer(entries: CommandBufferEntry[]): CommandBufferEntry[] {
  const pruned = dropStaleEntries(entries)
  const next = [...pruned].sort((a, b) => b.lastUsedAt - a.lastUsedAt)
  if (next.length <= COMMAND_BUFFER_LIMIT) return next
  return next.slice(0, COMMAND_BUFFER_LIMIT)
}

export function loadBuffer(): CommandBufferEntry[] {
  if (!canUseStorage()) return []
  try {
    const rows = safeParseEntries(window.localStorage.getItem(COMMAND_BUFFER_STORAGE_KEY))
    return compactBuffer(rows)
  } catch {
    return []
  }
}

export function saveBuffer(entries: CommandBufferEntry[]): void {
  if (!canUseStorage()) return
  try {
    const compacted = compactBuffer(entries)
    window.localStorage.setItem(COMMAND_BUFFER_STORAGE_KEY, JSON.stringify(compacted))
  } catch {
    /* ignore quota/private mode */
  }
}

function pickContainsMatch(
  entries: CommandBufferEntry[],
  intent: CommandIntentType,
  normalizedText: string
): CommandBufferEntry | null {
  if (normalizedText.length < 8) return null
  const candidates = entries
    .filter((x) => x.intent === intent)
    .sort((a, b) => b.lastUsedAt - a.lastUsedAt)
  for (const row of candidates) {
    const cached = row.normalizedText
    if (!cached || cached.length < 8) continue
    if (cached.includes(normalizedText) || normalizedText.includes(cached)) {
      return row
    }
    if (tokenSimilarity(cached, normalizedText) >= 0.6) {
      return row
    }
  }
  return null
}

export function findRunnableCachedCommand(message: string): CommandBufferHit | null {
  const intent = detectIntentByRegex(message)
  if (!intent) return null
  const normalizedText = normalizeCommandText(message)
  if (!normalizedText) return null
  const entries = loadBuffer()
  if (!entries.length) return null

  const exact = entries.find((x) => x.intent === intent.intent && x.normalizedText === normalizedText)
  if (exact) {
    return {
      intent: exact.intent,
      handlerKey: exact.handlerKey,
      normalizedText,
      strategy: 'exact',
      cachedEntry: exact
    }
  }

  const contains = pickContainsMatch(entries, intent.intent, normalizedText)
  if (!contains) return null
  return {
    intent: contains.intent,
    handlerKey: contains.handlerKey,
    normalizedText,
    strategy: 'contains',
    cachedEntry: contains
  }
}

export function recordCommandHit(params: CommandIntentMatch & { message: string }): void {
  const normalizedText = normalizeCommandText(params.message)
  if (!normalizedText) return
  const now = Date.now()
  const entries = loadBuffer()
  const idx = entries.findIndex((x) => x.intent === params.intent && x.normalizedText === normalizedText)
  if (idx >= 0) {
    const hitCount = Number(entries[idx].hitCount || 0)
    entries[idx] = {
      ...entries[idx],
      handlerKey: params.handlerKey,
      hitCount: hitCount + 1,
      lastUsedAt: now
    }
  } else {
    entries.push({
      intent: params.intent,
      handlerKey: params.handlerKey,
      normalizedText,
      hitCount: 1,
      createdAt: now,
      lastUsedAt: now
    })
  }
  saveBuffer(entries)
}

export function getCommandBufferLimit(): number {
  return COMMAND_BUFFER_LIMIT
}
