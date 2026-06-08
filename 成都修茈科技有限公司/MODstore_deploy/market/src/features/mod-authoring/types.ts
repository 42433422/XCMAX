export const EXPERT_TABS = [
  { id: 'guide', label: '概览' },
  { id: 'manifest', label: '配置' },
  { id: 'frontend', label: '前端' },
  { id: 'files', label: '文件' },
  { id: 'snapshots', label: '版本' },
  { id: 'scan', label: '路由' },
] as const

export type ExpertTabId = (typeof EXPERT_TABS)[number]['id']

export const WIZARD_STEPS = [
  { id: 1, key: 'intro', label: '介绍' },
  { id: 2, key: 'employees', label: '员工' },
  { id: 3, key: 'frontend', label: '界面' },
  { id: 4, key: 'release', label: '发布' },
] as const

export const EXPERT_MODE_STORAGE_KEY = 'mod_authoring_expert_mode'
export const WIZARD_FRONTEND_SKIP_KEY = 'mod_authoring_wizard_frontend_skip'
export const MOD_AUTHORING_ATTACH_KEY = 'mod_authoring_attach_mod'

export const WORKFLOW_SUMMARY_MAX = 280

export type LooseRecord = Record<string, any>

export function asLooseRecord(value: unknown): LooseRecord {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as LooseRecord) : {}
}

export function truncatePlain(s: unknown, max: number): string {
  const t = String(s || '')
    .replace(/\s+/g, ' ')
    .trim()
  if (t.length <= max) return t
  return `${t.slice(0, max)}…`
}
