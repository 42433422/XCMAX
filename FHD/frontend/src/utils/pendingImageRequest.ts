import { buildChatScopedKey } from '@/utils/chatStorageKeys'
import { isDurableChatScope } from '@/utils/chatSessionRestore'

const PREFIX = 'xcagi_pending_image_request_'
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

/** Persist only a prompt digest and request key, scoped to the authenticated chat. */
export async function reserveImageRequest(scope: string, sessionId: string, modId: string, prompt: string) {
  if (!isDurableChatScope(scope) || !sessionId || !globalThis.crypto?.subtle || !globalThis.crypto.randomUUID) {
    throw new Error('账号或会话尚未准备好，无法安全提交生图请求。')
  }
  const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(prompt))
  const hex = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
  const key = `${buildChatScopedKey(PREFIX, sessionId, modId, scope)}:${hex}`
  const existing = localStorage.getItem(key)
  if (existing && !UUID.test(existing)) throw new Error('生图请求记录异常，请先核对原请求。')
  const requestId = existing || globalThis.crypto.randomUUID()
  if (!existing) localStorage.setItem(key, requestId)
  if (localStorage.getItem(key) !== requestId) throw new Error('无法保存生图请求，请稍后重试。')
  return { key, requestId }
}

export function finishImageRequest(key: string, requestId: string) {
  if (localStorage.getItem(key) === requestId) localStorage.removeItem(key)
}
