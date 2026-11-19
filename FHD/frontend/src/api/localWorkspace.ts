import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import { readCsrfTokenFromCookie } from '@/utils/csrfCookie'
import { isDesktopShell } from '@/utils/desktopShell'

export type LocalRecordKind = 'customer' | 'product' | 'order'

export interface LocalRecord {
  id: string
  kind: LocalRecordKind
  data: Record<string, unknown>
  deleted: boolean
  version: string
}

export interface LocalArchive {
  archive_id: string
  workspace_id: string
  created_at: string | number
  record_count: number
}

interface LocalStatus {
  workspace_id: string
  cursor: number
  record_count: number
  paired: boolean
  archives: LocalArchive[]
}

interface LocalOperation extends Omit<LocalRecord, 'version'> {
  op_id: string
  base_version: string | null
}

interface LocalWriteResult {
  accepted: string[]
  conflicts: Array<{ op_id: string; current: LocalRecord | null }>
}

export function hasLocalWorkspace(): boolean {
  if (typeof window === 'undefined' || !isDesktopShell() || isAdminConsoleSpa()) return false
  const { hostname, protocol } = window.location
  return ['127.0.0.1', 'localhost', '[::1]'].includes(hostname) && (protocol === 'http:' || protocol === 'https:')
}

async function localRequest<T>(path: string, method = 'GET', payload?: object): Promise<T> {
  if (!hasLocalWorkspace()) throw new Error('请在本机桌面应用中打开本地工作区。')
  const headers: Record<string, string> = { Accept: 'application/json', 'X-XCAGI-Desktop-Local': '1' }
  if (payload !== undefined) headers['Content-Type'] = 'application/json'
  if (method !== 'GET') {
    const csrf = readCsrfTokenFromCookie()
    if (csrf) headers['X-CSRF-Token'] = csrf
  }
  const response = await fetch(`/api/local-workspace${path}`, {
    method, headers, mode: 'same-origin', credentials: 'same-origin', cache: 'no-store', redirect: 'error',
    body: payload === undefined ? undefined : JSON.stringify(payload),
    signal: AbortSignal.timeout(12_000),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(typeof body?.detail === 'string' ? body.detail : `本地服务请求失败（${response.status}）`)
  }
  return response.json() as Promise<T>
}

export const localWorkspaceApi = {
  status: () => localRequest<LocalStatus>('/status'),
  records: () => localRequest<{ workspace_id: string; records: LocalRecord[]; cursor: number }>('/records'),
  write: (workspaceId: string, operation: LocalOperation) =>
    localRequest<LocalWriteResult>('/records', 'POST', { operations: [operation], workspace_id: workspaceId }),
  createPairing: () =>
    localRequest<{ qr: { kind: string; v: number; endpoint: string; key: string } }>('/pairing', 'POST', {}),
  removePairing: () => localRequest<LocalStatus>('/pairing', 'DELETE'),
  restore: (archiveId: string, workspaceId: string) =>
    localRequest<LocalStatus>(`/archives/${encodeURIComponent(archiveId)}/restore`, 'POST', { workspace_id: workspaceId }),
}
