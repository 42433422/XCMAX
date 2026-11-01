import { shallowRef } from 'vue'
import { getAuthSessionEpoch } from './authSessionCache'
import { productReadAccountEpoch } from './productReadAccountScope'
import { resolveChatIdentity } from './chatStorageKeys'

export interface ChatModelRoute {
  provider: string
  model: string
  route_source: string
  key_source: string
  config_revision: string | null
  route_state: 'selected' | 'completed' | 'failed'
}

const receipts = shallowRef(new Map<string, ChatModelRoute | null>())
let owner = ''
function key(sessionId: string, identity: string): string {
  const scope = JSON.stringify([getAuthSessionEpoch(), productReadAccountEpoch.value])
  return JSON.stringify([scope, identity, sessionId || 'default'])
}
export function readChatModelRoute(value: unknown): ChatModelRoute | null {
  if (!value || typeof value !== 'object') return null
  const row = value as Record<string, unknown>
  const text = (name: string) => typeof row[name] === 'string' ? row[name].trim() : ''
  if (!text('provider') || !text('model') || !text('route_source') || !text('key_source')) return null
  const route_state = ['completed', 'failed'].includes(text('route_state')) ? text('route_state') as 'completed' | 'failed' : 'selected'
  return { provider: text('provider'), model: text('model'), route_source: text('route_source'), key_source: text('key_source'), config_revision: text('config_revision') || null, route_state }
}
export function recordChatModelRoute(sessionId: string, value: unknown, identity = resolveChatIdentity()): void {
  if (value === undefined) return
  const route = readChatModelRoute(value)
  if (value != null && !route) return
  const scope = JSON.stringify([getAuthSessionEpoch(), productReadAccountEpoch.value])
  if (owner !== scope) { owner = scope; receipts.value = new Map() }
  receipts.value = new Map(receipts.value).set(key(sessionId, identity), route)
}
export function lastChatModelRoute(sessionId: string, identity = resolveChatIdentity()): ChatModelRoute | null {
  return receipts.value.get(key(sessionId, identity)) || null
}
export function chatRouteSourceLabel(source: string): string {
  return ({ platform: '跟随平台', platform_default: '跟随平台', platform_configuration: '跟随平台', fallback: '平台可用聊天模型', preference: '个人显式选择', user_preference: '个人显式选择', user: '个人显式选择', explicit: '个人显式选择', user_provider: '个人供应商选择', byok: '个人 BYOK' } as Record<string, string>)[source] || source || '未提供'
}
export function chatKeySourceLabel(source: string): string {
  return ({ managed: '平台服务端配置', platform: '平台服务端配置', environment: '平台环境配置', env: '平台环境配置', byok: '个人 BYOK', user: '个人 BYOK', user_override: '个人 BYOK' } as Record<string, string>)[source] || source || '未提供'
}
