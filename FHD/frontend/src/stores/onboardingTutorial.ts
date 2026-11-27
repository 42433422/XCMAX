import { ref } from 'vue'
import { defineStore } from 'pinia'
import { resolveTrackSteps } from '@/tutorial/resolveSteps'
import { buildDriverScheduleFromTutorialSteps } from '@/tutorial/buildDriverSchedule'
import type { DriverStepSchedule } from '@/tutorial/buildDriverSchedule'
import type { TutorialBuildContext } from '@/tutorial/types'

const COMPLETED_KEY = 'xcagi_onboarding_driver_tutorial_completed'
const CORE_CHECKLIST_KEY = 'xcagi_onboarding_core_checklist_v1'

export const ONBOARDING_CORE_TASK_SLA_MS = 10 * 60 * 1000

export const DEFAULT_CORE_ONBOARDING_TASKS = [
  'setup_workspace',
  'first_ai_chat',
  'first_business_action',
] as const

export type CoreOnboardingTaskId = (typeof DEFAULT_CORE_ONBOARDING_TASKS)[number] | string

export type CoreOnboardingChecklistState = {
  startedAtMs: number | null
  completedAtMs: number | null
  completedTasks: string[]
}

export type CoreOnboardingChecklistSummary = CoreOnboardingChecklistState & {
  requiredTasks: string[]
  progressPct: number
  completed: boolean
  elapsedMs: number | null
  withinSla: boolean | null
  slaMs: number
}

export type OnboardingReturnContext = {
  routeName?: string
  assistantOpen?: boolean
  assistantTab?: string
  assistantState?: Record<string, unknown> | null
}

function readChecklistState(): CoreOnboardingChecklistState {
  try {
    const raw = localStorage.getItem(CORE_CHECKLIST_KEY)
    if (!raw) return { startedAtMs: null, completedAtMs: null, completedTasks: [] }
    const parsed = JSON.parse(raw) as Partial<CoreOnboardingChecklistState>
    const completedTasks = Array.isArray(parsed.completedTasks)
      ? Array.from(new Set(parsed.completedTasks.map((item) => String(item).trim()).filter(Boolean)))
      : []
    return {
      startedAtMs: typeof parsed.startedAtMs === 'number' ? parsed.startedAtMs : null,
      completedAtMs: typeof parsed.completedAtMs === 'number' ? parsed.completedAtMs : null,
      completedTasks,
    }
  } catch {
    return { startedAtMs: null, completedAtMs: null, completedTasks: [] }
  }
}

function writeChecklistState(state: CoreOnboardingChecklistState): void {
  try {
    localStorage.setItem(CORE_CHECKLIST_KEY, JSON.stringify(state))
  } catch {
    /* ignore */
  }
}

export const useOnboardingTutorialStore = defineStore('onboardingTutorial', () => {
  const active = ref(false)
  const paused = ref(false)
  const skipRequested = ref(false)
  const schedules = ref<DriverStepSchedule[]>([])
  const returnContext = ref<OnboardingReturnContext | null>(null)
  const trackId = ref<string>('advanced')
  const coreChecklist = ref<CoreOnboardingChecklistState>(readChecklistState())

  const isCompleted = () => {
    try {
      return localStorage.getItem(COMPLETED_KEY) === '1'
    } catch {
      return false
    }
  }

  const markCompleted = () => {
    try {
      localStorage.setItem(COMPLETED_KEY, '1')
    } catch {
      /* ignore */
    }
  }

  const markSkipped = () => {
    /* 跳过不写入 completed，下次仍可提示 */
  }

  const resetControls = () => {
    paused.value = false
    skipRequested.value = false
  }

  const startCoreChecklist = (nowMs: number = Date.now()) => {
    const current = readChecklistState()
    if (current.startedAtMs === null) {
      current.startedAtMs = nowMs
      writeChecklistState(current)
    }
    coreChecklist.value = current
    return getCoreChecklistSummary()
  }

  const completeCoreTask = (taskId: CoreOnboardingTaskId, nowMs: number = Date.now()) => {
    const normalized = String(taskId || '').trim()
    if (!normalized) return getCoreChecklistSummary()
    const current = readChecklistState()
    if (current.startedAtMs === null) {
      current.startedAtMs = nowMs
    }
    if (!current.completedTasks.includes(normalized)) {
      current.completedTasks = [...current.completedTasks, normalized]
    }
    const allDone = DEFAULT_CORE_ONBOARDING_TASKS.every((req) => current.completedTasks.includes(req))
    if (allDone && current.completedAtMs === null) {
      current.completedAtMs = Math.max(nowMs, current.startedAtMs)
    }
    writeChecklistState(current)
    coreChecklist.value = current
    return getCoreChecklistSummary()
  }

  const getCoreChecklistSummary = (): CoreOnboardingChecklistSummary => {
    const current = readChecklistState()
    coreChecklist.value = current
    const requiredTasks = [...DEFAULT_CORE_ONBOARDING_TASKS]
    const doneCount = requiredTasks.filter((req) => current.completedTasks.includes(req)).length
    const completed = doneCount === requiredTasks.length
    const elapsedMs =
      completed && current.startedAtMs !== null && current.completedAtMs !== null
        ? Math.max(0, current.completedAtMs - current.startedAtMs)
        : null
    return {
      ...current,
      requiredTasks,
      progressPct: Math.round((doneCount / requiredTasks.length) * 100),
      completed,
      elapsedMs,
      withinSla: elapsedMs === null ? null : elapsedMs <= ONBOARDING_CORE_TASK_SLA_MS,
      slaMs: ONBOARDING_CORE_TASK_SLA_MS,
    }
  }

  const resetCoreChecklist = () => {
    const empty: CoreOnboardingChecklistState = {
      startedAtMs: null,
      completedAtMs: null,
      completedTasks: [],
    }
    coreChecklist.value = empty
    try {
      localStorage.removeItem(CORE_CHECKLIST_KEY)
    } catch {
      /* ignore */
    }
  }

  const start = (options: { track?: string; buildContext: TutorialBuildContext; returnContext?: OnboardingReturnContext }) => {
    const tid = String(options.track || 'advanced').trim() || 'advanced'
    trackId.value = tid
    returnContext.value = options.returnContext || null
    const rawSteps = resolveTrackSteps(tid, options.buildContext)
    schedules.value = buildDriverScheduleFromTutorialSteps(rawSteps)
    resetControls()
    active.value = schedules.value.length > 0
  }

  const finish = (completed: boolean) => {
    active.value = false
    schedules.value = []
    resetControls()
    if (completed) markCompleted()
    else markSkipped()
  }

  const requestSkip = () => {
    skipRequested.value = true
  }

  const togglePause = () => {
    paused.value = !paused.value
  }

  return {
    active,
    paused,
    skipRequested,
    schedules,
    returnContext,
    trackId,
    coreChecklist,
    isCompleted,
    markCompleted,
    startCoreChecklist,
    completeCoreTask,
    getCoreChecklistSummary,
    resetCoreChecklist,
    start,
    finish,
    requestSkip,
    togglePause,
  }
})
