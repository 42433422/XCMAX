/** document_full / presentation_full JSON 提取（读取员 → 生成员 / 报告员衔接）（原 tabularReadEmployees 单体拆分） */
import { extractDirectPythonPayload, normalizeEmployeeExecuteEnvelope } from './envelope'

function isDocumentFullShape(obj: Record<string, unknown>): boolean {
  return Array.isArray(obj.paragraphs) || Array.isArray(obj.tables) || Array.isArray(obj.blocks)
}

function isPresentationFullShape(obj: Record<string, unknown>): boolean {
  return Array.isArray(obj.slides)
}

function findPresentationFullObject(node: unknown, depth = 0): Record<string, unknown> | null {
  if (depth > 12 || node == null) return null
  if (Array.isArray(node)) {
    for (const it of node) {
      const hit = findPresentationFullObject(it, depth + 1)
      if (hit) return hit
    }
    return null
  }
  if (typeof node !== 'object') return null
  const o = node as Record<string, unknown>
  if (isPresentationFullShape(o)) return o
  for (const key of ['presentation_full', 'presentation', 'ppt', 'data', 'output', 'items', 'payload']) {
    if (key in o) {
      const hit = findPresentationFullObject(o[key], depth + 1)
      if (hit) return hit
    }
  }
  const outputs = o.outputs
  if (Array.isArray(outputs)) {
    for (const item of outputs) {
      if (!item || typeof item !== 'object') continue
      const row = item as Record<string, unknown>
      const hit = findPresentationFullObject(row.output ?? row, depth + 1)
      if (hit) return hit
    }
  }
  return null
}

function findDocumentFullObject(node: unknown, depth = 0): Record<string, unknown> | null {
  if (depth > 12 || node == null) return null
  if (Array.isArray(node)) {
    for (const it of node) {
      const hit = findDocumentFullObject(it, depth + 1)
      if (hit) return hit
    }
    return null
  }
  if (typeof node !== 'object') return null
  const o = node as Record<string, unknown>
  if (isDocumentFullShape(o)) return o
  for (const key of ['document_full', 'document', 'doc', 'data', 'output', 'items', 'payload']) {
    if (key in o) {
      const hit = findDocumentFullObject(o[key], depth + 1)
      if (hit) return hit
    }
  }
  const outputs = o.outputs
  if (Array.isArray(outputs)) {
    for (const item of outputs) {
      if (!item || typeof item !== 'object') continue
      const row = item as Record<string, unknown>
      const hit = findDocumentFullObject(row.output ?? row, depth + 1)
      if (hit) return hit
    }
  }
  return null
}

/** 从 llm_context_text 或 items 中提取 document_full JSON 字符串（供报告员工上传）。 */
export function extractDocumentFullJsonText(result: unknown): string | null {
  const r = normalizeEmployeeExecuteEnvelope(result)
  const llm = String(r.llm_context_text || '').trim()
  if (llm) {
    const patterns = [
      /### (?:outputs\/)?document_full\.json\n([\s\S]*?)(?=\n### |\n*$)/,
      /### document_full\.json\n([\s\S]*?)(?=\n### |\n*$)/,
    ]
    for (const re of patterns) {
      const m = llm.match(re)
      if (m?.[1]?.trim()) return m[1].trim()
    }
    const trimmed = llm.trim()
    if (trimmed.startsWith('{') && trimmed.includes('"paragraphs"')) {
      return trimmed
    }
  }
  const embedded = findDocumentFullObject(r)
  if (embedded) {
    try {
      return JSON.stringify(embedded, null, 2)
    } catch {
      /* ignore */
    }
  }
  const payload = extractDirectPythonPayload(result)
  if (!payload) return null
  const items = payload.items
  if (Array.isArray(items)) {
    for (const it of items) {
      if (it && typeof it === 'object') {
        const row = it as Record<string, unknown>
        if (isDocumentFullShape(row)) {
          try {
            return JSON.stringify(row, null, 2)
          } catch {
            /* ignore */
          }
        }
      }
    }
  }
  if (isDocumentFullShape(payload)) {
    try {
      return JSON.stringify(payload, null, 2)
    } catch {
      /* ignore */
    }
  }
  return null
}

/** 从读取员工响应提取 presentation_full JSON（PPT 读 → PPT 生）。 */
export function extractPresentationFullJsonText(result: unknown): string | null {
  const r = normalizeEmployeeExecuteEnvelope(result)
  const llm = String(r.llm_context_text || '').trim()
  if (llm) {
    const patterns = [
      /### (?:outputs\/)?presentation_full\.json\n([\s\S]*?)(?=\n### |\n*$)/,
      /### presentation_full\.json\n([\s\S]*?)(?=\n### |\n*$)/,
    ]
    for (const re of patterns) {
      const m = llm.match(re)
      if (m?.[1]?.trim()) return m[1].trim()
    }
    const trimmed = llm.trim()
    if (trimmed.startsWith('{') && trimmed.includes('"slides"')) {
      return trimmed
    }
  }
  const embedded = findPresentationFullObject(r)
  if (embedded) {
    try {
      return JSON.stringify(embedded, null, 2)
    } catch {
      /* ignore */
    }
  }
  const payload = extractDirectPythonPayload(result)
  if (!payload) return null
  const items = payload.items
  if (Array.isArray(items)) {
    for (const it of items) {
      if (it && typeof it === 'object') {
        const row = it as Record<string, unknown>
        if (isPresentationFullShape(row)) {
          try {
            return JSON.stringify(row, null, 2)
          } catch {
            /* ignore */
          }
        }
      }
    }
  }
  if (isPresentationFullShape(payload)) {
    try {
      return JSON.stringify(payload, null, 2)
    } catch {
      /* ignore */
    }
  }
  return null
}

function _summarizeDocumentFullJson(text: string): string {
  try {
    const data = JSON.parse(text) as Record<string, unknown>
    const paragraphs = Array.isArray(data.paragraphs) ? data.paragraphs.length : 0
    const tables = Array.isArray(data.tables) ? data.tables.length : 0
    const meta = data.metadata && typeof data.metadata === 'object' ? (data.metadata as Record<string, unknown>) : {}
    const title = String(meta.title || data.title || '').trim()
    const lines = [`段落数：${paragraphs}`, `表格数：${tables}`, title ? `标题：${title}` : ''].filter(Boolean)
    return lines.join('\n')
  } catch {
    return ''
  }
}
