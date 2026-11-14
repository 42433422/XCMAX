import { apiFetch } from '@/utils/apiBase'

/** 统一员工目录行：后端 runtime_ok + 非宿主管理岗过滤后的可用员工。 */
export type DirectoryEmployee = {
  pack_id: string
  label: string
  description: string
  /** manifest identity.area，如 craft-workshop */
  area: string
  /** 区域中文名，如「制作车间」；无映射时为空 */
  department: string
  runtime_ok: boolean
  handlers: string[]
}

let cached: DirectoryEmployee[] | null = null

/** 拉取统一员工目录；智能对话 / 员工工作台 / 信息形象共用。 */
export async function fetchEmployeeDirectory(options?: { force?: boolean }): Promise<DirectoryEmployee[]> {
  if (cached && !options?.force) return cached
  const res = await apiFetch('/api/platform-shell/employee-directory', { cache: 'no-store' })
  if (!res.ok) throw new Error(`employee-directory HTTP ${res.status}`)
  const body = (await res.json()) as { data?: { employees?: DirectoryEmployee[] } }
  const rows = body?.data?.employees
  cached = Array.isArray(rows) ? rows : []
  return cached
}

export function invalidateEmployeeDirectoryCache(): void {
  cached = null
}
