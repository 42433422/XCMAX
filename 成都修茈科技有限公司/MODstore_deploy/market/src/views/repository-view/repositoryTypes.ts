// 拆分自 RepositoryView.vue：类型、常量与纯函数（逻辑逐字迁移，行为不变）。

export const LS_AUTHORING_INDUSTRY = 'modstore_authoring_industry_id'

export const PREFILL_KEY = 'modstore_employee_prefill'

export interface ModRow {
  id: string
  name?: string
  version?: string
  artifact?: string
  ok?: boolean
  primary?: boolean
  warnings?: string[]
  error?: string
  workflow_employees?: Array<Record<string, unknown>>
  path?: string
  description?: string
  library_blurb?: string
  updated_at?: string
  usage_scene?: string
  [key: string]: unknown
}

export interface EnterpriseUserRow {
  id?: string | number
  username?: string
  email?: string
  mod_ids?: string[]
}

export function modIndustryId(m: ModRow): string {
  const industry = m?.industry
  if (industry && typeof industry === 'object') {
    const id = String((industry as Record<string, unknown>).id || '').trim()
    if (id) return id
    const name = String((industry as Record<string, unknown>).name || '').trim()
    if (name) return name
  }
  if (typeof industry === 'string' && industry.trim()) return industry.trim()
  return String(m?.industry_id || '通用').trim() || '通用'
}

export function modShelfStatus(m: ModRow): string {
  if (m.primary) return 'primary'
  if (isBundle(m)) return 'bundle'
  return 'mod'
}

export function formatUpdatedAt(raw: string | undefined): string {
  const s = String(raw || '').trim()
  if (!s) return ''
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return ''
  const now = Date.now()
  const diff = now - d.getTime()
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  if (diff < 14 * 86_400_000) return `${Math.floor(diff / 86_400_000)} 天前`
  return d.toLocaleDateString('zh-CN', { year: 'numeric', month: 'short', day: 'numeric' })
}

export function getUsageScene(m: ModRow): string {
  if (!m || typeof m !== 'object') return ''
  const scene = typeof m.usage_scene === 'string' ? m.usage_scene.trim() : ''
  if (scene) return scene
  const wf = m.workflow_employees
  if (Array.isArray(wf) && wf.length) {
    const e0 = wf[0]
    const label = e0 && typeof e0 === 'object' ? String(e0.label || e0.id || '').trim() : ''
    if (label) return `工作流员工：${label}`
  }
  if (m.primary) return '主扩展 / 宿主壳层'
  if (isBundle(m)) return '组合包 manifest.bundle'
  return '沙箱 / 制作页'
}

/** 由显示名生成 manifest / 目录 id（与后端 create_mod 约定一致） */
export function modIdFromDisplayName(name: string): string {
  const raw = String(name || '')
    .trim()
    .toLowerCase()
  let x = raw
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
  if (!x) {
    x = `mod-${Date.now().toString(36)}`
  }
  if (!/^[a-z]/.test(x)) {
    x = `m-${x.replace(/[^a-z0-9-]/g, '')}`.replace(/-+/g, '-').replace(/^-|-$/g, '')
  }
  if (!x || !/^[a-z]/.test(x)) {
    x = `mod-${Date.now().toString(36)}`
  }
  return x.slice(0, 128)
}

export function isCreateModConflictError(e: unknown): boolean {
  const msg = (e as { message?: string })?.message || String(e)
  return msg.includes('已存在') || msg.includes('409') || /FileExistsError/i.test(msg)
}

/** 磁盘目录末段名（仅用于提示文案；删除 API 须用 manifest id） */
export function libraryFolderForDeleteApi(m: ModRow | null | undefined): string {
  if (!m || typeof m !== 'object') return ''
  const rawPath = typeof m.path === 'string' ? m.path.trim() : ''
  if (rawPath) {
    const norm = rawPath.replace(/\\/g, '/').replace(/\/+$/, '')
    const seg = norm.split('/').filter(Boolean).pop()
    if (seg) return seg
  }
  return String(m.id || '').trim()
}

/** DELETE /api/mods/:id 须传 manifest.id（与账号 user_mod 一致）；服务端再解析真实目录 */
export function modIdForDeleteApi(m: ModRow | null | undefined): string {
  if (!m || typeof m !== 'object') return ''
  const mid = String(m.id || '').trim()
  if (mid) return mid
  return libraryFolderForDeleteApi(m)
}

export function getBlurb(m: ModRow): string {
  if (!m || typeof m !== 'object') return ''
  const b = typeof m.library_blurb === 'string' ? m.library_blurb.trim() : ''
  if (b) return b
  const d = typeof m.description === 'string' ? m.description.trim() : ''
  if (!d) return ''
  const one = d.replace(/\s+/g, ' ')
  return one.length > 120 ? `${one.slice(0, 117)}…` : one
}

export function artifactLabel(a: string | undefined): string {
  const x = (a || 'mod').toLowerCase()
  if (x === 'employee_pack') return '员工包'
  if (x === 'bundle') return '组合包'
  return 'Mod'
}

export function isBundle(m: ModRow): boolean {
  return (m?.artifact || 'mod').toLowerCase() === 'bundle'
}

export function registerKey(modId: string, workflowIndex: number): string {
  return `${modId}:${workflowIndex}`
}
