/**
 * 修茈 MODstore 员工 API 桥接。
 * 优先级：远程修茈 API（VITE_MODSTORE_API_ORIGIN / VITE_MARKET_BASE）→ 本地后端同源 API。
 * 鉴权：xcagi_market_access_token（与 ModelPaymentView / Login 一致）。
 */
import { LS_MARKET_ACCESS_TOKEN } from '@amin/primary-key-guard/api/marketAccount'
import { apiFetch, DEFAULT_MOD_API_TIMEOUT_MS } from '@/utils/apiBase'

export type ModstoreEmployeeRow = {
  id: string
  name?: string
  source?: string
  version?: string
  industry?: string
  [key: string]: unknown
}

export function resolveModstoreApiOrigin(): string {
  const explicit = String(import.meta.env.VITE_MODSTORE_API_ORIGIN || '').trim().replace(/\/$/, '')
  if (explicit) return explicit
  const market = String(import.meta.env.VITE_MARKET_BASE || '').trim().replace(/\/$/, '')
  if (!market) return ''
  return market.replace(/\/market\/?$/i, '') || market
}

function readBearer(): string {
  if (typeof window === 'undefined') return ''
  return (window.localStorage.getItem(LS_MARKET_ACCESS_TOKEN) || '').trim()
}

function authHeaders(): HeadersInit {
  const t = readBearer()
  const h: Record<string, string> = { Accept: 'application/json' }
  if (t) {
    const v = t.toLowerCase().startsWith('bearer ') ? t : `Bearer ${t}`
    h.Authorization = v
  }
  return h
}

async function readJsonBody(res: Response): Promise<unknown> {
  const text = await res.text()
  if (!text) return null
  try {
    return JSON.parse(text) as unknown
  } catch {
    return { detail: text }
  }
}

function msgFromBody(data: unknown, fallback: string): string {
  if (!data || typeof data !== 'object') return fallback
  const o = data as Record<string, unknown>
  const d = o.detail
  if (typeof d === 'string' && d.trim()) return d.trim()
  if (Array.isArray(d)) {
    return d
      .map((x) => (x && typeof x === 'object' && 'msg' in x ? String((x as { msg?: unknown }).msg) : JSON.stringify(x)))
      .join('; ')
  }
  const m = o.message
  if (typeof m === 'string' && m.trim()) return m.trim()
  return fallback
}

export function hasModstoreMarketToken(): boolean {
  return Boolean(readBearer())
}

async function listEmployeesFromLocal(): Promise<ModstoreEmployeeRow[]> {
  const res = await apiFetch('/api/employees/', { timeoutMs: DEFAULT_MOD_API_TIMEOUT_MS })
  const data = await readJsonBody(res)
  if (!res.ok) throw new Error(msgFromBody(data, `拉取本地员工列表失败 HTTP ${res.status}`))
  if (Array.isArray(data)) return data as ModstoreEmployeeRow[]
  if (data && typeof data === 'object' && Array.isArray((data as Record<string, unknown>).data)) {
    return (data as Record<string, unknown>).data as ModstoreEmployeeRow[]
  }
  throw new Error('员工列表格式异常')
}

async function listEmployeesFromRemote(origin: string): Promise<ModstoreEmployeeRow[]> {
  const res = await fetch(`${origin}/api/employees/`, {
    method: 'GET',
    headers: authHeaders(),
    credentials: 'omit',
  })
  const data = await readJsonBody(res)
  if (!res.ok) throw new Error(msgFromBody(data, `拉取员工列表失败 HTTP ${res.status}`))
  if (Array.isArray(data)) return data as ModstoreEmployeeRow[]
  throw new Error('员工列表格式异常')
}

export async function modstoreListEmployees(): Promise<ModstoreEmployeeRow[]> {
  const origin = resolveModstoreApiOrigin()
  if (origin) {
    return listEmployeesFromRemote(origin)
  }
  return listEmployeesFromLocal()
}

export async function modstoreDeleteEmployeePack(pkgId: string): Promise<unknown> {
  const origin = resolveModstoreApiOrigin()
  const id = encodeURIComponent(pkgId)
  if (!origin) {
    const res = await apiFetch(`/api/admin/employee-packs/${id}`, {
      method: 'DELETE',
      timeoutMs: DEFAULT_MOD_API_TIMEOUT_MS,
    })
    const data = await readJsonBody(res)
    if (!res.ok) throw new Error(msgFromBody(data, `删除失败 HTTP ${res.status}`))
    return data
  }
  const res = await fetch(`${origin}/api/admin/employee-packs/${id}`, {
    method: 'DELETE',
    headers: authHeaders(),
    credentials: 'omit',
  })
  const data = await readJsonBody(res)
  if (!res.ok) throw new Error(msgFromBody(data, `删除失败 HTTP ${res.status}`))
  return data
}

export type AdminCatalogUploadFields = {
  pkgId: string
  version: string
  name: string
  description?: string
  artifact?: string
  industry?: string
  price?: number
  isPublic?: boolean
  file: File
}

export async function modstoreAdminUploadCatalog(fields: AdminCatalogUploadFields): Promise<unknown> {
  const origin = resolveModstoreApiOrigin()
  const fd = new FormData()
  fd.set('pkg_id', fields.pkgId.trim())
  fd.set('version', fields.version.trim())
  fd.set('name', fields.name.trim())
  fd.set('description', (fields.description ?? '').trim())
  fd.set('price', String(fields.price ?? 0))
  fd.set('artifact', (fields.artifact ?? 'employee_pack').trim())
  fd.set('industry', (fields.industry ?? '通用').trim())
  fd.set('is_public', fields.isPublic ? 'true' : 'false')
  fd.set('file', fields.file, fields.file.name)

  if (!origin) {
    const res = await apiFetch('/api/admin/catalog', {
      method: 'POST',
      body: fd,
      timeoutMs: DEFAULT_MOD_API_TIMEOUT_MS * 3,
    })
    const data = await readJsonBody(res)
    if (!res.ok) throw new Error(msgFromBody(data, `上传失败 HTTP ${res.status}`))
    return data
  }

  const res = await fetch(`${origin}/api/admin/catalog`, {
    method: 'POST',
    headers: authHeaders(),
    body: fd,
    credentials: 'omit',
  })
  const data = await readJsonBody(res)
  if (!res.ok) throw new Error(msgFromBody(data, `上传失败 HTTP ${res.status}`))
  return data
}
