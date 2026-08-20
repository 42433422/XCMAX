export type UnknownRecord = Record<string, unknown>

export function isUnknownRecord(value: unknown): value is UnknownRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function asUnknownRecord(value: unknown): UnknownRecord {
  return isUnknownRecord(value) ? value : {}
}

export function errorMessage(error: unknown, fallback = '操作失败'): string {
  if (error instanceof Error && error.message) return error.message
  if (isUnknownRecord(error)) {
    const detail = error.detail
    if (typeof detail === 'string' && detail.trim()) return detail.trim()
    const message = error.message
    if (typeof message === 'string' && message.trim()) return message.trim()
  }
  const text = String(error || '').trim()
  return text || fallback
}
