/** 联系页问卷 ↔ 官网管家桥接（依赖 contact-intake.js 挂载的 window.XcContactIntake） */

export type IntakeStepId = 'profile' | 'problem' | 'workflow' | 'contact' | 'plan' | 'review'

export type ContactIntakeState = {
  userRole: string
  industry: string
  roleSummary: string
  primaryGoal: string
  directions: string[]
  manualSteps: string
  painGoals: string
  sampleDesc: string
  name: string
  phone: string
  email: string
  company: string
  timeline: string
  budget: string
  needIntegration: string
  integrationNote: string
  extraNote: string
}

export type AiAssistFillResult = { ok: boolean; message: string }

export type XcContactIntake = {
  getState: () => ContactIntakeState
  goToStep: (stepId: IntakeStepId | string) => void
  applyDraft: (partial: Partial<ContactIntakeState>) => void
  highlightField: (fieldId: string) => void
  validateCurrentStep: () => boolean
  buildMessage: () => string
  isSubmitted: () => boolean
  getCurrentStepId: () => string
  stepIds: () => string[]
  runAiAssistFill?: (opts: { company: string; system: string }) => Promise<AiAssistFillResult>
  selectAiCompany?: (item: { name: string; exact?: boolean }) => void
}

const STEP_ORDER: IntakeStepId[] = ['profile', 'problem', 'workflow', 'contact', 'plan', 'review']

declare global {
  interface Window {
    XcContactIntake?: XcContactIntake
  }
}

export function isContactPage(pathname = typeof window !== 'undefined' ? window.location.pathname : ''): boolean {
  return /\/contact(?:\.html)?\/?$/i.test(pathname)
}

export function getBridge(): XcContactIntake | null {
  if (typeof window === 'undefined') return null
  const b = window.XcContactIntake
  return b && typeof b.applyDraft === 'function' ? b : null
}

export function waitForBridge(timeoutMs = 4000): Promise<XcContactIntake | null> {
  const existing = getBridge()
  if (existing) return Promise.resolve(existing)
  if (typeof document === 'undefined') return Promise.resolve(null)

  return new Promise((resolve) => {
    const started = Date.now()
    const tick = () => {
      const b = getBridge()
      if (b) {
        resolve(b)
        return
      }
      if (Date.now() - started >= timeoutMs) {
        resolve(null)
        return
      }
      window.setTimeout(tick, 80)
    }
    tick()
  })
}

function stepIncomplete(stepId: IntakeStepId, s: ContactIntakeState): boolean {
  switch (stepId) {
    case 'profile':
      return !s.userRole.trim() || !s.roleSummary.trim()
    case 'problem':
      return !s.primaryGoal.trim()
    case 'workflow':
      return !s.manualSteps.trim() || !s.painGoals.trim()
    case 'contact':
      return !s.name.trim() || !s.email.trim()
    case 'plan':
      return !s.timeline.trim() || !s.needIntegration.trim()
    case 'review':
      return false
    default:
      return false
  }
}

export function inferEarliestIncompleteStep(state: ContactIntakeState): IntakeStepId {
  for (const id of STEP_ORDER) {
    if (stepIncomplete(id, state)) return id
  }
  return 'review'
}

export function scrollToIntake(): void {
  document.querySelector('.contact-intake-section')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

export function applyDraftSafe(draft: Partial<ContactIntakeState>): boolean {
  const bridge = getBridge()
  if (!bridge || bridge.isSubmitted()) return false
  bridge.applyDraft(draft)
  const merged = { ...bridge.getState(), ...draft }
  bridge.goToStep(inferEarliestIncompleteStep(merged))
  scrollToIntake()
  return true
}

/** 联系页：公司与系统类型 → 一键预填（供移动端 AI 管家调用） */
export async function runContactAiAssistFill(
  company: string,
  system: string,
): Promise<AiAssistFillResult> {
  const bridge = await waitForBridge(8000)
  if (!bridge) {
    scrollToIntake()
    return { ok: false, message: '问卷尚未就绪，请刷新页面后重试。' }
  }
  if (bridge.isSubmitted()) {
    return { ok: false, message: '您已提交过需求问卷，如需修改请通过电话或邮件联系我们。' }
  }
  if (typeof bridge.runAiAssistFill !== 'function') {
    scrollToIntake()
    return { ok: false, message: '预填功能未加载，请强制刷新页面（Cmd+Shift+R）后重试。' }
  }
  const c = company.trim()
  const s = system.trim()
  if (!c || !s) {
    return { ok: false, message: '请填写公司名称和系统 / 业务类型。' }
  }
  return bridge.runAiAssistFill({ company: c, system: s })
}

export function describeDraftFields(draft: Partial<ContactIntakeState>): string[] {
  const labels: Record<string, string> = {
    userRole: '岗位角色',
    industry: '行业',
    roleSummary: '日常工作',
    primaryGoal: '最想改善',
    directions: '期望方向',
    manualSteps: '现有流程',
    painGoals: '痛点',
    sampleDesc: '样例说明',
    name: '姓名',
    phone: '手机',
    email: '邮箱',
    company: '公司',
    timeline: '上线时间',
    budget: '预算',
    needIntegration: '系统对接',
    integrationNote: '对接说明',
    extraNote: '补充说明',
  }
  const filled: string[] = []
  for (const [key, label] of Object.entries(labels)) {
    const val = draft[key as keyof ContactIntakeState]
    if (val == null) continue
    if (Array.isArray(val) && val.length) filled.push(label)
    else if (typeof val === 'string' && val.trim()) filled.push(label)
  }
  return filled
}
