import { api } from './core'
import type { ApiResponse } from '@/types/api'

export const PRIVATE_DB_READ_ASSISTANT_MOD_ID = 'private-db-read-assistant'

const BASE = `/api/mod/${PRIVATE_DB_READ_ASSISTANT_MOD_ID}`

const MOD_UNAVAILABLE: ApiResponse<never> = {
  success: false,
  message: 'private-db-read-assistant Mod 未安装或不可用',
}

type PrivateDbModRouteRow = {
  id?: string
  mod_id?: string
  enabled?: boolean
}

async function isPrivateDbModRouteAvailable(): Promise<boolean> {
  // Installed and account-visible Mods can change without reloading the page.
  const resp = await api.get<ApiResponse<PrivateDbModRouteRow[] | PrivateDbModRouteRow>>('/api/mods/', {}, { cache: 'no-store' })
  if (resp?.success === false) {
    throw new Error(resp.message || '无法读取 Mod 列表')
  }
  const mods = Array.isArray(resp?.data) ? resp.data : resp?.data ? [resp.data] : []
  return mods.some((m) => {
    const id = String(m?.id || m?.mod_id || '')
    return id === PRIVATE_DB_READ_ASSISTANT_MOD_ID && m?.enabled !== false
  })
}

export interface PrivateDbSource {
  id: string
  label: string
  description?: string
  status?: 'available' | 'planned'
  category?: 'im' | 'mail' | 'erp' | 'office' | 'ecommerce' | 'generic'
  icon?: string
  capabilities?: string[]
  requires_authorization?: boolean
}

export interface PrivateDbContact {
  id?: number | null
  display_name: string
  contact_name?: string
  remark?: string
  source_user_id?: string
  contact_type?: string
  is_starred?: boolean
}

async function modGet<T>(path: string): Promise<ApiResponse<T>> {
  if (!(await isPrivateDbModRouteAvailable())) {
    return MOD_UNAVAILABLE as ApiResponse<T>
  }
  return api.get<ApiResponse<T>>(path)
}

async function modPost<T>(path: string, body?: unknown): Promise<ApiResponse<T>> {
  if (!(await isPrivateDbModRouteAvailable())) {
    return MOD_UNAVAILABLE as ApiResponse<T>
  }
  return api.post<ApiResponse<T>>(path, body)
}

export const privateDbAssistantApi = {
  status(): Promise<ApiResponse<unknown>> {
    return modGet(`${BASE}/status`)
  },

  listSources(): Promise<ApiResponse<PrivateDbSource[]>> {
    return modGet(`${BASE}/sources`)
  },

  selectSource(sourceId: string): Promise<ApiResponse<unknown>> {
    return modPost(`${BASE}/sources/select`, { source_id: sourceId })
  },

  refreshSource(sourceId: string, refreshType: 'contacts' | 'messages' | 'all' = 'contacts'): Promise<ApiResponse<unknown>> {
    return modPost(`${BASE}/sources/refresh`, {
      source_id: sourceId,
      refresh_type: refreshType,
    })
  },

  searchContacts(sourceId: string, q: string): Promise<ApiResponse<PrivateDbContact[]>> {
    return modGet(`${BASE}/contacts/search?source_id=${encodeURIComponent(sourceId)}&q=${encodeURIComponent(q)}`)
  },

  getContext(sourceId: string, contactId: number | string): Promise<ApiResponse<unknown[]>> {
    return modGet(`${BASE}/contacts/${encodeURIComponent(String(contactId))}/context?source_id=${encodeURIComponent(sourceId)}`)
  },

  sendMessage(sourceId: string, contactName: string, message: string): Promise<ApiResponse<unknown>> {
    return modPost(`${BASE}/send`, {
      source_id: sourceId,
      contact_name: contactName,
      message,
    })
  },
}

export default privateDbAssistantApi
