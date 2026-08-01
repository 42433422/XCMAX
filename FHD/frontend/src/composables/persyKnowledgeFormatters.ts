import type { KnowledgeBaseChunk, PersyMemoryRecord, PersyMemoryValue } from '@/api/knowledgeBase'

export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error || '操作失败')
}

export function numberText(value: unknown): string {
  const n = Number(value)
  return Number.isFinite(n) ? n.toLocaleString('zh-CN') : '-'
}

export function versionLabel(value: unknown): string {
  const n = Number(value)
  return Number.isFinite(n) && n > 0 ? `v${n}` : '-'
}

export function formatScore(value: unknown): string {
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  return n >= 1 ? n.toFixed(2) : `${Math.round(n * 100)}%`
}

export function strengthText(value: unknown): string {
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  return `${Math.round(Math.max(0, Math.min(n, 1)) * 100)}%`
}

export function formatDate(value: unknown): string {
  const date = new Date(String(value || ''))
  if (!Number.isFinite(date.getTime())) return '-'
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

export function memoryValue(memory: PersyMemoryRecord): PersyMemoryValue {
  return memory.value && typeof memory.value === 'object'
    ? (memory.value as PersyMemoryValue)
    : {}
}

export function memoryStatusLabel(status: string): string {
  return (
    {
      pending: '待确认',
      active: '已确认',
      rejected: '已忽略',
      deleted: '已删除',
    }[status] || status || '未知'
  )
}

export function memoryScopeLabel(scope: string): string {
  return scope === 'tenant' ? '企业共享' : '仅自己'
}

export function memoryTypeLabel(type: string): string {
  return (
    {
      preference: '偏好',
      entity: '人物与事实',
      episodic: '经历',
    }[type] || '记忆'
  )
}

export function memoryIcon(type: string): string {
  return (
    {
      preference: 'fa-heart-o',
      entity: 'fa-link',
      episodic: 'fa-clock-o',
    }[type] || 'fa-history'
  )
}

export function memoryEvidenceSource(memory: PersyMemoryRecord): string {
  const first = Array.isArray(memory.evidence) ? memory.evidence[0] : null
  if (first && typeof first === 'object') {
    const sourceName = String(first.source || '').trim()
    if (sourceName) return sourceName === 'chat' ? '可信对话' : sourceName
  }
  return memory.source === 'chat_trace' ? '可信对话' : String(memory.source || '受控记忆')
}

export function buildMemoryStatement(subject: string, predicate: string, object: string): string {
  return ['负责', '属于', '位于', '使用', '采用'].includes(predicate)
    ? `${subject}${predicate}${object}`
    : `${subject}的${predicate}是${object}`
}

export function normalizeChunkSource(chunk: KnowledgeBaseChunk): string {
  const source = chunk.metadata?.source || chunk.source || '知识来源'
  const normalized = String(source).replace(/\+rerank$/i, '').trim()
  if (normalized.toLowerCase() === 'bm25') return '关键词召回'
  return normalized || '知识来源'
}

export function normalizeAnswer(value: unknown, evidenceCount: number): string {
  const answer = String(value || '').trim()
  if (!answer) return ''
  if (/^Based on the retrieved dataset evidence\b/i.test(answer)) {
    return `已召回 ${evidenceCount} 条相关知识证据。`
  }
  return answer
}

export function evidenceKey(chunk: KnowledgeBaseChunk, index: number): string {
  return `${chunk.metadata?.memory_id || chunk.metadata?.document_id || chunk.source || 'chunk'}-${chunk.chunk_index ?? index}`
}

export function isMemoryChunk(chunk: KnowledgeBaseChunk): boolean {
  return Boolean(chunk.metadata?.memory_id)
}

export function parserLabel(value: unknown): string {
  const parser = String(value || '')
  if (parser === 'inline_text') return '直接文本'
  if (parser === 'pdfplumber') return 'PDF'
  if (parser === 'python-docx') return 'Word'
  return parser || '文本'
}

export function nodeTypeLabel(type: string): string {
  return (
    {
      core: 'Persy 核心',
      topic: '主题',
      source: '资料来源',
      knowledge: '知识',
      memory: '长期记忆',
      recall: '召回',
      onboarding: '开始',
    }[type] || '知识节点'
  )
}

export function nodeIcon(type: string): string {
  return (
    {
      core: 'fa-circle-o',
      topic: 'fa-tag',
      source: 'fa-file-text-o',
      knowledge: 'fa-lightbulb-o',
      memory: 'fa-history',
      recall: 'fa-bolt',
      onboarding: 'fa-plus',
    }[type] || 'fa-circle'
  )
}

export function fileSizeText(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
