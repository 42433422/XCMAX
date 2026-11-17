import type { UiChatMessage } from '@/types/chat-ui'
import { createBusinessHarnessId } from './businessHarnessIds'

const identities = new WeakMap<object, string>()
/** Content, timestamps and turn IDs are not unique message identities. */
export function chatMessageKey(message: UiChatMessage): string {
  let key = identities.get(message)
  if (!key) {
    const uiKey = typeof message.uiKey === 'string' ? message.uiKey.trim() : ''
    const id = typeof message.persistence?.id === 'string' ? message.persistence.id.trim() : ''
    key = uiKey || (id ? `id:${message.role}:${id}` : createBusinessHarnessId('message'))
    identities.set(message, key)
  }
  return key
}
