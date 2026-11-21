import { apiFetch, getActiveExtensionModHeaders, getClientModsUiOffHeader } from '@/utils/apiBase'
import { productReadScopeKey } from '@/utils/productReadAccountScope'

/** 统一员工目录行：后端按当前会话与 manifest 可见性返回的可用员工。 */
export type DirectoryEmployee = {
  pack_id: string
  label: string
  description: string
  /** manifest identity.area，如 craft-workshop */
  area: string
  /** 区域中文名，如「制作车间」；无映射时为空 */
  department: string
  enterprise_layer?: string
  runtime_ok: boolean
  /** 仅提示词、无本地 Python 运行时的对话型员工 */
  prompt_only: boolean
  runtime_kind: 'direct_python' | 'prompt_only'
  handlers: string[]
}

let cached: { scope: string; rows: DirectoryEmployee[] } | null = null
let requestGeneration = 0
let pending: { scope: string; promise: Promise<DirectoryEmployee[]> } | null = null

export function employeeDirectoryScope(): string {
  return productReadScopeKey(JSON.stringify([getActiveExtensionModHeaders(), getClientModsUiOffHeader()]))
}

/** 拉取统一员工目录；智能对话 / 员工工作台 / 信息形象共用。 */
export async function fetchEmployeeDirectory(options?: { force?: boolean }): Promise<DirectoryEmployee[]> {
  const scope = employeeDirectoryScope()
  if (cached?.scope === scope && !options?.force) return cached.rows
  if (pending?.scope === scope) return pending.promise
  const generation = ++requestGeneration
  const promise = (async () => {
    const res = await apiFetch('/api/platform-shell/employee-directory', { cache: 'no-store' })
    if (!res.ok) throw new Error(`employee-directory HTTP ${res.status}`)
    const body = (await res.json()) as { success?: boolean; data?: { employees?: DirectoryEmployee[] } }
    if (scope !== employeeDirectoryScope() || generation !== requestGeneration) throw new Error('员工目录上下文已变更，请重试')
    const rows = body?.data?.employees
    if (body.success === false || !Array.isArray(rows)) throw new Error('员工目录响应无效，请重试')
    cached = { scope, rows }
    return rows
  })()
  pending = { scope, promise }
  try { return await promise } finally { if (pending?.promise === promise) pending = null }
}

export function invalidateEmployeeDirectoryCache(): void {
  cached = null
  requestGeneration++
  pending = null
}
