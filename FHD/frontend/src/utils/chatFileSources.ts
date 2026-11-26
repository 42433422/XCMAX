import { asArray, asRecord } from '@/utils/typeGuards'

export interface ChatFileSource {
  name: string
  excerpts: string[]
}

export function readChatFileSources(value: unknown): ChatFileSource[] {
  return asArray(value).slice(0, 6).flatMap(raw => {
    const { name, excerpts } = asRecord(raw)
    if (typeof name !== 'string' || !name.trim() || name.length > 255 || /[\\/:\x00-\x1f\x7f]/.test(name)) return []
    const passages = asArray(excerpts).slice(0, 6).filter((item): item is string =>
      typeof item === 'string' && item.trim().length > 0 && item.length <= 240,
    )
    return passages.length ? [{ name, excerpts: passages }] : []
  })
}

export function readRuntimeFileSources(payload: unknown): ChatFileSource[] {
  const result = asRecord(payload)
  const data = asRecord(result.data)
  return result.success === true && result.runtime === 'xiaox' && data.execution_state === 'completed'
    && data.action === 'runtime_reply' ? readChatFileSources(data.file_sources) : []
}
