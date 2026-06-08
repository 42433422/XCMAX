import { YUANGON_PKG_ROLE_LABELS } from '../domain/yuangonDutyRoster'

/** 与 modstore_server/craft_executor.CRAFT_STEP_EMPLOYEE_MAP 对齐的后端 step id */
export const EMPLOYEE_ORCH_STEP_IDS = [
  'spec',
  'employee_plan',
  'generate',
  'validate',
  'script_workflow',
  'embed_script',
  'workflow',
  'register_pack',
  'workflow_sandbox',
  'mod_sandbox',
  'standalone_smoke',
  'host_check',
  'six_dim_gate',
  'complete',
] as const

export type EmployeeOrchStepId = (typeof EMPLOYEE_ORCH_STEP_IDS)[number]

export interface OrchStepVisual {
  name: string
  color: string
}

/** 后端 step id → 虚拟员工展示 */
export const ORCH_STEP_VISUAL: Record<string, OrchStepVisual> = {
  spec: { name: YUANGON_PKG_ROLE_LABELS['intent-analyst'] || '需求分析员工', color: '#818cf8' },
  employee_plan: { name: YUANGON_PKG_ROLE_LABELS['employee-planner'] || '规划设计员工', color: '#60a5fa' },
  generate: { name: YUANGON_PKG_ROLE_LABELS['artifact-generator'] || '产物生成员工', color: '#4ade80' },
  validate: { name: YUANGON_PKG_ROLE_LABELS['quality-validator'] || '质检员工', color: '#fb923c' },
  script_workflow: { name: YUANGON_PKG_ROLE_LABELS['miniapp-builder'] || '小程序员工', color: '#22d3ee' },
  embed_script: { name: YUANGON_PKG_ROLE_LABELS['script-binder'] || '配置绑定员工', color: '#f472b6' },
  workflow: { name: YUANGON_PKG_ROLE_LABELS['workflow-automator'] || '流程自动化员工', color: '#facc15' },
  register_pack: { name: YUANGON_PKG_ROLE_LABELS['pack-registrar'] || '打包登记员工', color: '#2dd4bf' },
  workflow_sandbox: { name: YUANGON_PKG_ROLE_LABELS['sandbox-tester'] || '测试员工', color: '#f87171' },
  mod_sandbox: { name: YUANGON_PKG_ROLE_LABELS['code-validator'] || '代码校验员工', color: '#fbbf24' },
  standalone_smoke: { name: YUANGON_PKG_ROLE_LABELS['self-checker'] || '自检员工', color: '#a3e635' },
  host_check: { name: YUANGON_PKG_ROLE_LABELS['host-checker'] || '运维员工', color: '#94a3b8' },
  six_dim_gate: { name: YUANGON_PKG_ROLE_LABELS['hex-quality-assessor'] || '六维质检员工', color: '#c084fc' },
  complete: { name: '完成', color: '#34d399' },
}

/** label 变更时的兜底（与 workbench_api._default_steps employee 一致） */
export const ORCH_LABEL_TO_STEP_ID: Record<string, string> = {
  理解需求: 'spec',
  理解任务: 'spec',
  规划一站式员工: 'employee_plan',
  生成产物: 'generate',
  生成处理脚本: 'generate',
  创建Skill组: 'generate',
  '创建 Skill 组': 'generate',
  服务端校验: 'validate',
  安全检查: 'validate',
  生成配套小程序: 'script_workflow',
  绑定到员工: 'embed_script',
  生成自动化流程: 'workflow',
  登记员工包: 'register_pack',
  流程沙箱测试: 'workflow_sandbox',
  工作流沙箱测试: 'workflow_sandbox',
  '包体与Python校验': 'mod_sandbox',
  '包体与 Python 校验': 'mod_sandbox',
  Mod沙箱测试: 'mod_sandbox',
  'Mod 沙箱测试': 'mod_sandbox',
  独立可执行自检: 'standalone_smoke',
  宿主连通性检查: 'host_check',
  六维质量评估: 'six_dim_gate',
  运行并生成文件: 'run',
  完成: 'complete',
}

export type OrchStepLike = {
  id?: string | null
  label?: string | null
  status?: string | null
  message?: unknown
  started_at?: string | null
}

const TERMINAL = new Set(['done', 'skipped', 'error'])

export function isTerminalStepStatus(status: string | null | undefined): boolean {
  return TERMINAL.has(String(status || '').trim())
}

export function resolveOrchStepId(st: OrchStepLike | null | undefined): string {
  const id = String(st?.id || '').trim()
  if (id && ORCH_STEP_VISUAL[id]) return id
  const label = String(st?.label || '').trim()
  if (label && ORCH_LABEL_TO_STEP_ID[label]) return ORCH_LABEL_TO_STEP_ID[label]
  return id || label || 'unknown'
}

export function orchStepEmployee(st: OrchStepLike | null | undefined): string {
  const key = resolveOrchStepId(st)
  return ORCH_STEP_VISUAL[key]?.name || String(st?.label || '制作员工')
}

export function orchStepColor(st: OrchStepLike | null | undefined): string {
  const key = resolveOrchStepId(st)
  return ORCH_STEP_VISUAL[key]?.color || '#818cf8'
}

export interface OrchProgress {
  total: number
  done: number
  percent: number
}

export function computeOrchProgress(steps: OrchStepLike[] | null | undefined): OrchProgress {
  const list = Array.isArray(steps) ? steps : []
  const total = Math.max(list.length, 1)
  const done = list.filter((s) => isTerminalStepStatus(s?.status)).length
  const running = list.some((s) => String(s?.status || '') === 'running') ? 0.45 : 0
  const percent = Math.min(100, Math.max(0, ((done + running) / total) * 100))
  return { total: list.length, done, percent }
}

const STATUS_RANK: Record<string, number> = {
  pending: 0,
  running: 1,
  skipped: 2,
  done: 2,
  error: 2,
}

/** 轮询时防止步骤状态从 done/skipped 回退到 pending */
export function mergeOrchStepsMonotonic<T extends OrchStepLike>(
  prev: T[] | null | undefined,
  incoming: T[],
): T[] {
  if (!prev?.length) return incoming
  const prevMap = new Map<string, T>()
  for (const st of prev) prevMap.set(String(st.id || st.label || ''), st)
  return incoming.map((st) => {
    const key = String(st.id || st.label || '')
    const prevSt = prevMap.get(key)
    if (!prevSt) return st
    const prevRank = STATUS_RANK[String(prevSt.status || '')] ?? 0
    const inRank = STATUS_RANK[String(st.status || '')] ?? 0
    if (inRank >= prevRank) return st
    return { ...st, status: prevSt.status, started_at: prevSt.started_at ?? st.started_at }
  })
}

export interface StructuredStepMessage {
  summary?: string
  detail?: string
  warnings?: string[]
  skipped_reason?: string
  current_tool?: string
  todos?: Array<{ id: string; content: string; status: string }>
  slow_hint?: string
}

export function stepMessageSummary(message: unknown): string {
  if (message == null) return ''
  if (typeof message === 'string') return message.trim()
  if (typeof message === 'object' && message !== null) {
    const m = message as StructuredStepMessage
    if (m.summary) return String(m.summary).trim()
  }
  return ''
}
