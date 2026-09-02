// 拆分自 CatalogDetailView.vue：类型、文案映射与纯函数（逻辑逐字迁移，行为不变）。
import type { CatalogAuthor, CatalogCreatorStats } from '../../components/catalog/CatalogCreatorProfile.vue'

export interface CatalogItemDetail {
  id: number | string
  pkg_id?: string
  name?: string
  version?: string
  industry?: string
  artifact?: string
  material_category?: string
  description?: string
  license_scope_label?: string
  license_scope?: string
  origin_type?: string
  ip_risk_level?: string
  compliance_status?: string
  security_level?: string
  price: number
  favorited?: boolean
  purchased?: boolean
  user_has_review?: boolean
  status?: string
  execution_stats?: { total_runs?: number; success_rate?: number } | null
  capabilities?: { label: string; description: string }[]
  examples?: { title: string; description: string; input: Record<string, unknown> }[]
  author_id?: number
  author?: CatalogAuthor | null
  creator_stats?: CatalogCreatorStats | null
  install_count?: number
}

export interface ReviewRow {
  id: number | string
  user_name?: string
  rating: number
  created_at?: string
  content?: string
}

export interface ReviewsPayload {
  reviews: ReviewRow[]
  average_rating: number
  total: number
}

export interface EmployeeStatusPayload {
  status?: string
  execution_stats?: {
    total_executions?: number
    total_runs?: number
    success_rate?: number
  } | null
}

const artifactLabels = {
  mod: 'MOD 插件',
  employee_pack: 'AI 员工包',
  bundle: '资源包',
  surface: '界面扩展',
  workflow_template: '工作流模板',
}

const materialCategoryLabels = {
  ai_employee: 'AI 员工',
  agent_prompt: 'Agent 提示词',
  skill: 'Skill',
  tts_voice: 'TTS 声音模型',
  mod_asset: 'MOD 包素材',
  page_style: '页面风格',
  personal_design: '个性化设计',
  workflow_template: '工作流模板',
  other: '其他素材',
}

const licenseScopeLabels = {
  personal: '个人使用',
  commercial: '商业授权',
  free_personal: '免费个人用',
  enterprise: '企业级',
}

const originTypeLabels = {
  original: '原创',
  derivative: '二创/改编',
  collaboration: '联动授权',
  fan_linkage: '粉丝联动',
  suspected_plagiarism: '疑似抄袭',
}

const complianceStatusLabels = {
  approved: '已审核',
  active: '已上架',
  under_review: '投诉处理中',
  restricted: '已降权',
  delisted: '已下架',
}

export function securityLevelLabel(level: string | undefined) {
  const map: Record<string, string> = {
    personal: '个人级',
    team: '团队级',
    enterprise: '企业级',
  }
  return map[level || ''] || level || '个人级'
}

export function getArtifactLabel(artifact: string | undefined) {
  return (artifact && (artifactLabels as Record<string, string>)[artifact]) || artifact || '其他'
}

export function materialCategoryLabel(cat: string | undefined) {
  return (cat && (materialCategoryLabels as Record<string, string>)[cat]) || cat || '其他素材'
}

export function licenseScopeLabel(scope: string | undefined) {
  return (scope && (licenseScopeLabels as Record<string, string>)[scope]) || scope || '个人使用'
}

export function originTypeLabel(origin: string | undefined) {
  return (origin && (originTypeLabels as Record<string, string>)[origin]) || origin || '原创'
}

export function ipRiskLabel(risk: string | undefined) {
  if (risk === 'high') return '高'
  if (risk === 'medium') return '中'
  return '低'
}

export function complianceStatusLabel(status: string | undefined) {
  return (status && (complianceStatusLabels as Record<string, string>)[status]) || status || '已审核'
}

export function employeeTotalExecutions(status: EmployeeStatusPayload | null): number {
  const stats = status?.execution_stats
  return Number(stats?.total_executions ?? stats?.total_runs ?? 0) || 0
}

export function employeeSuccessRate(status: EmployeeStatusPayload | null): number {
  return Number(status?.execution_stats?.success_rate ?? 0) || 0
}

export const AUTHOR_FOLLOW_KEY = 'catalog_author_follows'

export function readAuthorFollowSet(): Set<number> {
  try {
    const raw = localStorage.getItem(AUTHOR_FOLLOW_KEY)
    const arr = raw ? (JSON.parse(raw) as unknown) : []
    if (!Array.isArray(arr)) return new Set()
    return new Set(arr.map((x) => Number(x)).filter((n) => Number.isFinite(n) && n > 0))
  } catch {
    return new Set()
  }
}

export function writeAuthorFollowSet(set: Set<number>) {
  localStorage.setItem(AUTHOR_FOLLOW_KEY, JSON.stringify([...set]))
}
