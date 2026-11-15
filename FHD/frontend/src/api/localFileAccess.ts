import { apiFetch } from '@/utils/apiBase'

export type LocalFileGrantMode = 'folder' | 'full_disk'
export type FullDiskAccessStatus = 'granted' | 'denied' | 'unknown' | 'not_required'

export interface LocalFileGrant {
  id: number
  mode: LocalFileGrantMode
  root_path: string
  display_name: string
  is_active: boolean
  device_id?: string
  last_scan_at?: string | null
  scan_status?: string
  scan_error?: string
  indexed_count?: number
  skipped_count?: number
  error_count?: number
}

export interface LocalFileStatus {
  desktop: boolean
  full_disk_access: FullDiskAccessStatus
  grants: LocalFileGrant[]
}

export interface LocalFileGrantDetail {
  grant_id: number
  scan_status: string
  total_documents: number
  indexed_count: number
  skipped_count: number
  error_count: number
}

function detailMessage(body: unknown, fallback: string): string {
  if (!body || typeof body !== 'object') return fallback
  const detail = (body as { detail?: unknown }).detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object') {
    const message = (detail as { message?: unknown; code?: unknown }).message
    if (typeof message === 'string' && message) return message
  }
  const message = (body as { message?: unknown }).message
  return typeof message === 'string' && message ? message : fallback
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(path, init)
  const body: unknown = await response.json().catch(() => null)
  if (!response.ok || (body as { success?: boolean } | null)?.success !== true) {
    throw new Error(detailMessage(body, '本机文件服务暂时不可用'))
  }
  return (body as { data: T }).data
}

export const localFileAccessApi = {
  status(): Promise<LocalFileStatus> {
    return request<LocalFileStatus>('/api/local-files/status')
  },

  createGrant(mode: LocalFileGrantMode, rootPath: string): Promise<LocalFileGrant> {
    return request<LocalFileGrant>('/api/local-files/grants', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode, root_path: rootPath }),
    })
  },

  revokeGrant(grantId: number): Promise<LocalFileGrant> {
    return request<LocalFileGrant>(`/api/local-files/grants/${grantId}/revoke`, { method: 'POST' })
  },

  syncGrant(grantId: number): Promise<LocalFileGrantDetail & { queued: boolean }> {
    return request(`/api/local-files/grants/${grantId}/sync`, { method: 'POST' })
  },

  grantDetail(grantId: number): Promise<LocalFileGrantDetail> {
    return request(`/api/local-files/grants/${grantId}`)
  },
}

export default localFileAccessApi
