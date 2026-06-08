/**
 * 模板预览页「同步到对话」写入的登记项；随 /api/ai/* 的 context 带给后端，注入 Planner system。
 */
export const CHAT_EXPORT_TEMPLATES_REGISTRY_KEY = 'xcagi_chat_export_templates_v1'

export type ChatExportTemplateKind = 'excel' | 'word'

export interface ChatExportTemplateEntry {
  kind: ChatExportTemplateKind
  /** 稳定键：excel 用模板 id；word 用 role:slug */
  id: string
  displayName: string
  business_scope: string
  /** Excel：模板类型文案；Word：如 价格表（Word） */
  template_type?: string
  /** Word：document_templates.role */
  role?: string
  /** Word：slug，对应导出 API 的 template_id */
  slug?: string
  storage_relpath?: string
  syncedAt: string
}

function safeParse(raw: string | null): ChatExportTemplateEntry[] {
  if (!raw) return []
  try {
    const v = JSON.parse(raw)
    return Array.isArray(v) ? v : []
  } catch {
    return []
  }
}

export function readChatExportTemplatesRegistry(): ChatExportTemplateEntry[] {
  if (typeof localStorage === 'undefined') return []
  return safeParse(localStorage.getItem(CHAT_EXPORT_TEMPLATES_REGISTRY_KEY))
}

export function writeChatExportTemplatesRegistry(entries: ChatExportTemplateEntry[]) {
  if (typeof localStorage === 'undefined') return
  try {
    localStorage.setItem(CHAT_EXPORT_TEMPLATES_REGISTRY_KEY, JSON.stringify(entries.slice(0, 40)))
  } catch {
    /* quota */
  }
}

export function upsertChatExportTemplateEntry(entry: ChatExportTemplateEntry) {
  const id = String(entry.id || '').trim()
  if (!id) return
  const rest = readChatExportTemplatesRegistry().filter((e) => String(e.id) !== id)
  rest.unshift({ ...entry, syncedAt: entry.syncedAt || new Date().toISOString() })
  writeChatExportTemplatesRegistry(rest)
}

export function removeChatExportTemplateEntry(id: string) {
  const rid = String(id || '').trim()
  if (!rid) return
  writeChatExportTemplatesRegistry(readChatExportTemplatesRegistry().filter((e) => String(e.id) !== rid))
}

export function isTemplateSyncedToChat(tplId: string): boolean {
  const id = String(tplId || '').trim()
  if (!id) return false
  return readChatExportTemplatesRegistry().some((e) => String(e.id) === id)
}
