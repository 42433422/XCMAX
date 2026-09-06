/**
 * IM 信息页（ImMessengerView）的「条目」纯逻辑模块。
 *
 * 收敛所有与具体组件无关的：
 *  - 固定/系统/外部应用会话条目类型与常量
 *  - 条目类型守卫（isXxxEntry）
 *  - 纯字符串/头像/状态标签等辅助函数（无响应式依赖）
 *
 * 任何需要在组件内做响应式派生（如 systemEntryRuntimeStatus / systemEntryLastStatus）
 * 的逻辑都保留在组件或对应的会话 composable 中。
 */
import { type ImContact, type ImConversationSummary } from '@/api/im'
import { type SuperEmployeeAvatarKey, superEmployeeAvatarSrcForId } from '@/constants/superEmployeeAvatars'
import { type CodexSuperEmployeeDispatch, type CodexSuperEmployeeMessage } from '@/api/codexSuperEmployee'
import { YUANGON_AREAS, YUANGON_PKG_DESCRIPTIONS, YUANGON_PKG_ROLE_LABELS } from '@/domain/yuangonDutyRoster'

// ── 类型 ──────────────────────────────────────────────────────────────

export type CodexSuperEmployeeEntry = {
  id: 'codex-super-employee'
  display_name: '超级员工-Codex'
  username: 'codex-super-employee'
  subtitle: '全设备协同调度'
  description?: string
  is_codex_super_employee: true
}

export type ClaudeSuperEmployeeEntry = {
  id: 'claude-super-employee'
  display_name: '超级员工-Claude'
  username: 'claude-super-employee'
  subtitle: '全设备协同 · 排比派工'
  description?: string
  is_claude_super_employee: true
}

export type CursorSuperEmployeeEntry = {
  id: 'cursor-super-employee'
  display_name: '超级员工-Cursor'
  username: 'cursor-super-employee'
  subtitle: '全设备协同 · Agent 派工'
  description?: string
  is_cursor_super_employee: true
}

export type DutyEmployeeEntry = {
  id: string
  display_name: string
  username: string
  subtitle: string
  description: string
  area: string
  status: string
  api_base_path: string
  phone_channel: string
  avatar_text?: string
  is_duty_employee_entry: true
}

export type ExternalAppEntry = {
  id: 'kellai-customer-im'
  display_name: '客户消息 · 客来来'
  username: 'kellai-customer-im'
  subtitle: '在 XCMAX 内只读查看客户会话'
  target_url: string
  is_external_app_entry: true
}

export type AiGroupChatEntry = {
  id: 'ai-group-chat'
  display_name: '我的群聊'
  username: 'ai-group-chat'
  subtitle: '多 AI 员工协同群聊'
  is_ai_group_chat_entry: true
}

export type SystemEmployeeEntry = CodexSuperEmployeeEntry | ClaudeSuperEmployeeEntry | CursorSuperEmployeeEntry | DutyEmployeeEntry

export type PinnedImEntry = ImContact | SystemEmployeeEntry | ExternalAppEntry | AiGroupChatEntry

export type ImSidebarListItem =
  | { kind: 'pinned'; key: string; entry: PinnedImEntry }
  | { kind: 'conversation'; key: string; conversation: ImConversationSummary }

export type CodexDisplayMessage = CodexSuperEmployeeMessage & {
  streaming?: boolean
  synthetic?: boolean
}

export type ActiveSuperTool = 'codex' | 'claude' | 'cursor'

export type AdminEmployeeApiItem = {
  id?: string
  name?: string
  label?: string
  title?: string
  description?: string
  panel_summary?: string
  yuangon_area?: string
  industry?: string
  status?: string
  api_base_path?: string
  phone_channel?: string
}

export type DutyEmployeeChatMessage = {
  id: string
  role: 'user' | 'assistant'
  body: string
  created_at: string
  status?: string
}

export type EmployeeExecuteResponse = {
  success?: boolean
  message?: string
  source?: string
  data?: unknown
}

// ── 常量 ──────────────────────────────────────────────────────────────

export const CODEX_STREAM_PLACEHOLDER_ID = '__codex_streaming_reply__'
export const CODEX_POLL_INTERVAL_MS = 2400
export const CODEX_POLL_MAX_ROUNDS = 60

export const CODEX_SUPER_EMPLOYEE_ENTRY: CodexSuperEmployeeEntry = {
  id: 'codex-super-employee',
  display_name: '超级员工-Codex',
  username: 'codex-super-employee',
  subtitle: '全设备协同调度',
  is_codex_super_employee: true,
}

export const CLAUDE_SUPER_EMPLOYEE_ENTRY: ClaudeSuperEmployeeEntry = {
  id: 'claude-super-employee',
  display_name: '超级员工-Claude',
  username: 'claude-super-employee',
  subtitle: '全设备协同 · 排比派工',
  is_claude_super_employee: true,
}

export const CURSOR_SUPER_EMPLOYEE_ENTRY: CursorSuperEmployeeEntry = {
  id: 'cursor-super-employee',
  display_name: '超级员工-Cursor',
  username: 'cursor-super-employee',
  subtitle: '全设备协同 · Agent 派工',
  is_cursor_super_employee: true,
}

export const KELLAI_CUSTOMER_IM_ENTRY: ExternalAppEntry = {
  id: 'kellai-customer-im',
  display_name: '客户消息 · 客来来',
  username: 'kellai-customer-im',
  subtitle: '在 XCMAX 内只读查看客户会话',
  target_url: 'kellai://messages?source=xcmax',
  is_external_app_entry: true,
}

export const AI_GROUP_CHAT_ENTRY: AiGroupChatEntry = {
  id: 'ai-group-chat',
  display_name: '我的群聊',
  username: 'ai-group-chat',
  subtitle: '多 AI 员工协同群聊',
  is_ai_group_chat_entry: true,
}

export const SUPER_CLI_TOOLS: SystemEmployeeEntry[] = [CODEX_SUPER_EMPLOYEE_ENTRY, CURSOR_SUPER_EMPLOYEE_ENTRY, CLAUDE_SUPER_EMPLOYEE_ENTRY]

/** 面向企业用户的精选员工；完整 55 岗编制仍保留在管理端。 */
export const CURATED_DUTY_EMPLOYEE_IDS = [
  'user-customer-service-officer',
  'intake-dispatcher',
  'intent-analyst',
  'workflow-automator',
  'artifact-generator',
  'quality-validator',
  'enterprise-adoption-officer',
] as const

const CURATED_DUTY_EMPLOYEE_AVATARS: Record<string, string> = {
  'user-customer-service-officer': '💬',
  'intake-dispatcher': '🧭',
  'intent-analyst': '🔎',
  'workflow-automator': '⚙️',
  'artifact-generator': '🧩',
  'quality-validator': '🛡️',
  'enterprise-adoption-officer': '📈',
}

// ── 条目类型守卫 ──────────────────────────────────────────────────────

export function isCodexSuperEmployeeEntry(entry: PinnedImEntry): entry is CodexSuperEmployeeEntry {
  return 'is_codex_super_employee' in entry && entry.is_codex_super_employee
}

export function isClaudeSuperEmployeeEntry(entry: PinnedImEntry): entry is ClaudeSuperEmployeeEntry {
  return 'is_claude_super_employee' in entry && entry.is_claude_super_employee
}

export function isCursorSuperEmployeeEntry(entry: PinnedImEntry): entry is CursorSuperEmployeeEntry {
  return 'is_cursor_super_employee' in entry && entry.is_cursor_super_employee
}

/** 超级员工（Codex / Claude / Cursor）共用同一套合成器、消息管线与轮询。 */
export function isSuperEmployeeEntry(
  entry: PinnedImEntry | null,
): entry is CodexSuperEmployeeEntry | ClaudeSuperEmployeeEntry | CursorSuperEmployeeEntry {
  return Boolean(entry && (isCodexSuperEmployeeEntry(entry) || isClaudeSuperEmployeeEntry(entry) || isCursorSuperEmployeeEntry(entry)))
}

export function isDutyEmployeeEntry(entry: PinnedImEntry | null): entry is DutyEmployeeEntry {
  return Boolean(entry && 'is_duty_employee_entry' in entry && entry.is_duty_employee_entry)
}

export function isExternalAppEntry(entry: PinnedImEntry | null): entry is ExternalAppEntry {
  return Boolean(entry && 'is_external_app_entry' in entry && entry.is_external_app_entry)
}

export function isAiGroupChatEntry(entry: PinnedImEntry | null): entry is AiGroupChatEntry {
  return Boolean(entry && 'is_ai_group_chat_entry' in entry && entry.is_ai_group_chat_entry)
}

// ── 纯辅助函数 ────────────────────────────────────────────────────────

export function avatarText(name: string): string {
  const s = String(name || '').trim()
  return s ? s.slice(0, 1).toUpperCase() : '?'
}

export function formatTime(iso: string | null): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

export function dutyContactLabel(channel: string): string {
  const raw = String(channel || '').trim()
  if (raw === 'admin-duty') return '管理端工作台'
  if (raw === 'mobile' || raw === 'mobile-chat') return '手机端会话'
  if (raw === 'super') return '超级员工调度'
  return raw || '员工通讯录'
}

export function superEmployeeAvatarKey(entry: PinnedImEntry): SuperEmployeeAvatarKey | null {
  if (isCodexSuperEmployeeEntry(entry)) return 'codex'
  if (isClaudeSuperEmployeeEntry(entry)) return 'claude'
  if (isCursorSuperEmployeeEntry(entry)) return 'cursor'
  return null
}

export function superEmployeeAvatarSrc(entry: PinnedImEntry): string | null {
  return superEmployeeAvatarSrcForId(String(entry.id || '').trim())
}

export function pinnedAvatarText(entry: PinnedImEntry): string {
  if (isCodexSuperEmployeeEntry(entry)) return 'Codex'
  if (isClaudeSuperEmployeeEntry(entry)) return 'Claude'
  if (isCursorSuperEmployeeEntry(entry)) return 'Cursor'
  if (isExternalAppEntry(entry)) return '客'
  if (isAiGroupChatEntry(entry)) return '群'
  if (isDutyEmployeeEntry(entry)) return entry.avatar_text || avatarText(entry.display_name)
  return avatarText(entry.display_name)
}

export function pinnedEntryPreview(entry: PinnedImEntry): string {
  if (isSuperEmployeeEntry(entry)) return entry.subtitle
  if (isDutyEmployeeEntry(entry)) return entry.subtitle
  if (isExternalAppEntry(entry)) return entry.subtitle
  if (isAiGroupChatEntry(entry)) return entry.subtitle
  return `@${entry.username}`
}

export function superCliToolLabel(entry: SystemEmployeeEntry): string {
  if (isCodexSuperEmployeeEntry(entry)) return 'Codex'
  if (isCursorSuperEmployeeEntry(entry)) return 'Cursor'
  if (isClaudeSuperEmployeeEntry(entry)) return 'Claude'
  return entry.display_name
}

export function systemEntryStatusLabel(entry: SystemEmployeeEntry): string {
  if (isSuperEmployeeEntry(entry)) return '多设备调度'
  return entry.status === 'on_duty' ? '在岗员工' : '编制员工'
}

export function systemEntryIdentity(entry: SystemEmployeeEntry): string {
  if (isSuperEmployeeEntry(entry)) return '跨设备协作开发员工'
  return entry.area || '管理端编制员工'
}

export function systemEntryDispatch(entry: SystemEmployeeEntry): string {
  if (isCodexSuperEmployeeEntry(entry)) return '全设备 Codex'
  if (isClaudeSuperEmployeeEntry(entry)) return '全设备 Claude'
  if (isCursorSuperEmployeeEntry(entry)) return '全设备 Cursor'
  return dutyContactLabel(entry.phone_channel)
}

export function isEnterpriseDedicatedContact(contact: ImContact): boolean {
  return Boolean(contact.is_enterprise_dedicated_cs) || contact.username.trim().toLowerCase() === 'enterprise-cs'
}

export function isEnterpriseDedicatedConversation(conversation: ImConversationSummary): boolean {
  return Boolean(conversation.is_enterprise_dedicated_cs) || conversation.title.trim() === '企业专属客服'
}

export function isCodexDispatcherMessage(message: CodexSuperEmployeeMessage): boolean {
  if (message.role === 'system' || message.kind === 'dispatcher') return true
  if (message.role !== 'assistant') return false
  const status = String(message.status || '').toLowerCase()
  const body = String(message.body || '')
  return (
    ['accepted', 'queued', 'running', 'dispatch_failed', 'dispatch_error'].includes(status) &&
    /调度器|调用队列|已派发|已调用全设备|未发现在线|Para 任务/.test(body)
  )
}

export function isCodexResultMessage(message: CodexSuperEmployeeMessage): boolean {
  if (typeof message.kind === 'string' && message.kind.endsWith('_result')) return true
  return message.role === 'assistant' && !isCodexDispatcherMessage(message)
}

export function isCodexStreamingMessage(message: CodexDisplayMessage): boolean {
  return Boolean(message.streaming)
}

export function sanitizeCodexReplyText(text: string): string {
  return String(text || '')
    .replace(/排比\s*Para\/Codex\s*多设备调度器/g, '全设备 Codex')
    .replace(/跨设备调度器/g, '全设备 Codex')
    .replace(/多设备调度器/g, '全设备 Codex')
    .replace(/调度器/g, 'Codex')
    .replace(/Para\/Codex/g, 'Codex')
    .replace(/Para\s*任务/g, 'Codex 任务')
    .replace(/调用队列/g, '任务队列')
    .replace(/任务\s*ID[:：]\s*[0-9a-f-]+/gi, '')
    .replace(/\s+。/g, '。')
    .trim()
}

export function codexReplyFromDispatcher(message: CodexSuperEmployeeMessage | null): string {
  if (!message) return 'Codex 已收到任务，正在连接全设备执行环境。'
  const body = String(message.body || '')
  const status = String(message.task_status || message.status || '').toLowerCase()
  if (/未发现在线可用 Codex 设备/.test(body)) {
    return 'Codex 暂未检测到在线工作设备，任务已保留，等待设备上线后继续。'
  }
  if (/任务运行中|进度\s*\d+%/.test(body)) {
    return sanitizeCodexReplyText(body)
  }
  if (status === 'queued') {
    return 'Codex 已收到任务，正在排队等待可用设备。'
  }
  if (status === 'accepted' || status === 'running') {
    return 'Codex 已收到任务，正在连接全设备执行环境。'
  }
  return sanitizeCodexReplyText(body) || 'Codex 已收到任务，正在处理。'
}

export function latestCodexDispatcherMessage(items: CodexSuperEmployeeMessage[], requestId = ''): CodexSuperEmployeeMessage | null {
  const pool = requestId ? items.filter((m) => String(m.dispatch_request_id || '') === requestId) : items
  return [...pool].reverse().find((m) => isCodexDispatcherMessage(m)) ?? null
}

export function latestCodexResultMessage(items: CodexSuperEmployeeMessage[], requestId = ''): CodexSuperEmployeeMessage | null {
  const pool = requestId ? items.filter((m) => String(m.dispatch_request_id || '') === requestId) : items
  return [...pool].reverse().find((m) => isCodexResultMessage(m)) ?? null
}

export function isCodexDispatchStillOpen(message: CodexSuperEmployeeMessage | null): boolean {
  if (!message) return false
  const status = String(message.task_status || message.status || '').toLowerCase()
  return !['completed', 'merged', 'failed', 'merge_conflict', 'dispatch_failed', 'dispatch_error'].includes(status)
}

export function dutyAreaLabelForId(id: string): string {
  for (const area of Object.values(YUANGON_AREAS)) {
    if (area.ids.includes(id)) return area.label
  }
  return '管理端编制'
}

export function normalizeDutyEmployee(raw: AdminEmployeeApiItem): DutyEmployeeEntry | null {
  const id = String(raw.id || '').trim()
  if (!id) return null
  const name = String(raw.name || raw.label || raw.title || YUANGON_PKG_ROLE_LABELS[id] || id).trim()
  const description = String(raw.panel_summary || raw.description || YUANGON_PKG_DESCRIPTIONS[id] || '').trim()
  const area = String(raw.yuangon_area || raw.industry || dutyAreaLabelForId(id)).trim()
  return {
    id,
    display_name: name || id,
    username: id,
    subtitle: `${dutyContactLabel(raw.phone_channel || 'admin-duty')} · AI号 ${id}`,
    description,
    area,
    status: String(raw.status || 'on_duty').trim(),
    api_base_path: String(raw.api_base_path || `/api/admin/employees/${id}`).trim(),
    phone_channel: String(raw.phone_channel || 'admin-duty').trim(),
    avatar_text: CURATED_DUTY_EMPLOYEE_AVATARS[id] || avatarText(name || id),
    is_duty_employee_entry: true,
  }
}

export function fallbackDutyEmployees(): DutyEmployeeEntry[] {
  const rows: AdminEmployeeApiItem[] = []
  for (const area of Object.values(YUANGON_AREAS)) {
    for (const id of area.ids) {
      rows.push({
        id,
        name: YUANGON_PKG_ROLE_LABELS[id] || id,
        description: YUANGON_PKG_DESCRIPTIONS[id] || '',
        yuangon_area: area.label,
        status: 'on_duty',
        api_base_path: `/api/admin/employees/${id}`,
        phone_channel: 'admin-duty',
      })
    }
  }
  return rows.map(normalizeDutyEmployee).filter((item): item is DutyEmployeeEntry => Boolean(item))
}

export function uniqueDutyEmployees(items: DutyEmployeeEntry[]): DutyEmployeeEntry[] {
  const seen = new Set<string>()
  return items.filter((item) => {
    if (seen.has(item.id)) return false
    seen.add(item.id)
    return true
  })
}

export function curatedDutyEmployees(items: DutyEmployeeEntry[]): DutyEmployeeEntry[] {
  const byId = new Map(uniqueDutyEmployees(items).map((item) => [item.id, item]))
  const fallbacks = new Map(fallbackDutyEmployees().map((item) => [item.id, item]))
  const selected: DutyEmployeeEntry[] = []
  for (const id of CURATED_DUTY_EMPLOYEE_IDS) {
    const current = byId.get(id)
    const item = current || fallbacks.get(id)
    if (!item) continue
    selected.push({
      ...item,
      ...(current ? {} : { status: 'planned', subtitle: '编制员工 · 未安装' }),
      avatar_text: CURATED_DUTY_EMPLOYEE_AVATARS[id] || item.avatar_text,
    })
  }
  return selected
}

export function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null
}

export function firstTextFromRecord(record: Record<string, unknown> | null, keys: string[]): string {
  if (!record) return ''
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
    if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  }
  return ''
}

export function textFromEmployeeOutputs(record: Record<string, unknown> | null): string {
  const outputs = Array.isArray(record?.outputs) ? record.outputs : []
  const parts: string[] = []
  for (const item of outputs) {
    const out = asRecord(item)
    if (!out) continue
    const directText = firstTextFromRecord(out, ['output', 'message', 'summary', 'error', 'result'])
    if (directText) {
      parts.push(directText)
      continue
    }
    const nestedOutput = asRecord(out.output)
    const nestedText = firstTextFromRecord(nestedOutput, ['reply', 'response', 'message', 'summary', 'result', 'error'])
    if (nestedText) parts.push(nestedText)
  }
  return parts.join('\n\n').trim()
}

export function shortJson(value: unknown): string {
  try {
    const text = JSON.stringify(value, null, 2)
    return text.length > 1200 ? `${text.slice(0, 1200)}…` : text
  } catch {
    return ''
  }
}

export function dutyEmployeeReplyFromExecution(result: EmployeeExecuteResponse, entry: DutyEmployeeEntry): string {
  const root = asRecord(result)
  const data = asRecord(result.data)
  const nestedResult = asRecord(data?.result)
  const success = result.success !== false && data?.success !== false
  const text =
    textFromEmployeeOutputs(nestedResult) ||
    textFromEmployeeOutputs(data) ||
    firstTextFromRecord(data, ['message', 'output', 'reply', 'response', 'stdout']) ||
    firstTextFromRecord(nestedResult, ['message', 'output', 'reply', 'response']) ||
    firstTextFromRecord(data, ['result', 'summary']) ||
    firstTextFromRecord(nestedResult, ['result', 'summary']) ||
    firstTextFromRecord(root, ['message'])
  const errorText =
    firstTextFromRecord(data, ['error', 'detail']) ||
    firstTextFromRecord(nestedResult, ['error', 'detail']) ||
    firstTextFromRecord(root, ['error', 'detail'])
  if (!success) return `执行失败：${errorText || text || '员工运行时未返回详细原因'}`
  if (text) return text
  return `${entry.display_name} 已完成执行，但没有返回可读文本。${shortJson(result.data) ? `\n${shortJson(result.data)}` : ''}`
}

// 备案：CodexSuperEmployeeDispatch 类型仅用于类型引用，避免未使用告警。
export type { CodexSuperEmployeeDispatch }
