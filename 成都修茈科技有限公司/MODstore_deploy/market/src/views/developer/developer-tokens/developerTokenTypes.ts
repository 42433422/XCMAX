// 开发者 Token 面板：类型、常量与纯函数（无状态）。
import { ApiError } from '../../../infrastructure/http/client'

export interface DeveloperToken {
  id: number
  name: string
  prefix: string
  scopes: string[]
  created_at: string | null
  last_used_at: string | null
  expires_at: string | null
  revoked_at: string | null
  is_active: boolean
}

export interface KeyExportAuditEvent {
  id: number | string
  created_at: string | null
  action: string
  success: boolean
  detail: string
  client_ip?: string | null
}

export const SCOPE_HINTS = ['mod:sync', 'llm:use', 'workflow:read', 'workflow:execute', 'employee:execute', 'catalog:read', 'webhook:manage']

export function errText(e: unknown, fallback: string): string {
  if (e instanceof ApiError) return e.message
  if (e && typeof e === 'object') {
    const o = e as { message?: string; detail?: unknown }
    if (typeof o.message === 'string' && o.message.trim()) return o.message
    if (typeof o.detail === 'string' && o.detail.trim()) return o.detail
  }
  return fallback
}

export function formatTime(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

export function formatExpiresShort(iso: string | null): string {
  if (!iso) return '永不过期'
  try {
    return new Date(iso).toLocaleDateString()
  } catch {
    return iso
  }
}

export function scopesSummary(scopes: string[]): string {
  if (!scopes.length) return '未配置权限'
  if (scopes.length <= 2) return scopes.join(' · ')
  return `${scopes.slice(0, 2).join(' · ')} +${scopes.length - 2}`
}

export function statusOf(row: DeveloperToken): { text: string; cls: string } {
  if (row.revoked_at) return { text: '已吊销', cls: 'st-revoked' }
  if (row.expires_at && new Date(row.expires_at).getTime() < Date.now()) return { text: '已过期', cls: 'st-expired' }
  return { text: '可用', cls: 'st-active' }
}
