/** Account/mod/conversation-scoped text-only draft. Never serialize File or upload tokens. */
const MAX_CHARS = 16000
const LIFETIME_MS = 7 * 24 * 60 * 60 * 1000

function safeStorage(): Storage | null {
  try { return typeof localStorage === 'undefined' ? null : localStorage } catch { return null }
}

export function readChatComposerDraft(key: string, now = Date.now(), storage = safeStorage()): string {
  if (!key || !storage) return ''
  try {
    const raw = storage.getItem(key)
    if (!raw) return ''
    const record: unknown = JSON.parse(raw)
    if (!record || typeof record !== 'object') throw new Error('invalid draft')
    const data = record as Record<string, unknown>
    if (typeof data.expiresAt !== 'number' || data.expiresAt <= now ||
        typeof data.text !== 'string') {
      storage.removeItem(key)
      return ''
    }
    return data.text.slice(0, MAX_CHARS)
  } catch {
    try { storage.removeItem(key) } catch { /* Storage denied */ }
    return ''
  }
}

export function writeChatComposerDraft(key: string, text: string, now = Date.now(), storage = safeStorage()): void {
  if (!key || !storage) return
  try {
    if (!text.trim()) storage.removeItem(key)
    else storage.setItem(key, JSON.stringify({
      text: text.slice(0, MAX_CHARS),
      expiresAt: now + LIFETIME_MS,
    }))
  } catch {
    // Full/disabled local storage must not block the primary chat transport.
  }
}
