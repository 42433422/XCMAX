import { ref } from 'vue'
import { defineStore } from 'pinia'
import { resolveTrackSteps } from '@/tutorial/resolveSteps'
import { buildDriverScheduleFromTutorialSteps } from '@/tutorial/buildDriverSchedule'
import type { DriverStepSchedule } from '@/tutorial/buildDriverSchedule'
import type { TutorialBuildContext } from '@/tutorial/types'

const COMPLETED_KEY = 'xcagi_onboarding_driver_tutorial_completed'

export type OnboardingReturnContext = {
  routeName?: string
  assistantOpen?: boolean
  assistantTab?: string
  assistantState?: Record<string, unknown> | null
}

export const useOnboardingTutorialStore = defineStore('onboardingTutorial', () => {
  const active = ref(false)
  const paused = ref(false)
  const skipRequested = ref(false)
  const schedules = ref<DriverStepSchedule[]>([])
  const returnContext = ref<OnboardingReturnContext | null>(null)
  const trackId = ref<string>('advanced')

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

  const start = (options: {
    track?: string
    buildContext: TutorialBuildContext
    returnContext?: OnboardingReturnContext
  }) => {
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
    isCompleted,
    markCompleted,
    start,
    finish,
    requestSkip,
    togglePause,
  }
})
