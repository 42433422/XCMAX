import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { ApiError } from '@/api'
import {
  tutorialV2Api,
  type TutorialCourseDTO,
  type TutorialRunDTO,
} from '@/api/tutorialV2'

function safeErrorHint(error: unknown): string {
  if (error instanceof ApiError) {
    const payload = error.data && typeof error.data === 'object'
      ? error.data as Record<string, unknown>
      : {}
    const nested = payload.error && typeof payload.error === 'object'
      ? payload.error as Record<string, unknown>
      : {}
    if (typeof nested.hint === 'string' && nested.hint.trim()) return nested.hint
  }
  return '教程服务暂时不可用，请保存当前工作后重试。'
}

export const useTutorialV2Store = defineStore('tutorialV2', () => {
  const courses = ref<TutorialCourseDTO[]>([])
  const currentRun = ref<TutorialRunDTO | null>(null)
  const loading = ref(false)
  const verifying = ref(false)
  const errorHint = ref('')
  const verificationHint = ref('')
  const targetVisited = ref(false)
  const reports = ref<Array<Record<string, unknown>>>([])

  const isActive = computed(() => currentRun.value?.status === 'active')
  const currentStep = computed(() => currentRun.value?.steps.find(
    (step) => step.id === currentRun.value?.current_step_id,
  ) || null)

  async function loadCourses() {
    loading.value = true
    errorHint.value = ''
    try {
      courses.value = await tutorialV2Api.courses()
      return courses.value
    } catch (error) {
      errorHint.value = safeErrorHint(error)
      throw error
    } finally {
      loading.value = false
    }
  }

  async function restoreCurrent() {
    try {
      currentRun.value = await tutorialV2Api.current()
    } catch (error) {
      errorHint.value = safeErrorHint(error)
    }
  }

  async function startCourse(courseId: string) {
    loading.value = true
    errorHint.value = ''
    verificationHint.value = ''
    try {
      const run = await tutorialV2Api.start(courseId)
      currentRun.value = await tutorialV2Api.enter(run.id)
      targetVisited.value = false
      await loadCourses()
      return currentRun.value
    } catch (error) {
      errorHint.value = safeErrorHint(error)
      throw error
    } finally {
      loading.value = false
    }
  }

  async function enterRun(runId: string) {
    currentRun.value = await tutorialV2Api.enter(runId)
    targetVisited.value = false
    verificationHint.value = ''
    return currentRun.value
  }

  async function leaveCurrent() {
    if (!currentRun.value) return
    const left = await tutorialV2Api.leave(currentRun.value.id)
    if (left.status === 'completed') {
      currentRun.value = null
      verificationHint.value = ''
    } else {
      currentRun.value = left
      verificationHint.value = '进度已保存，可从课程目录继续。'
    }
  }

  async function verifyCurrent(visitedRoute: string) {
    if (!currentRun.value || !currentStep.value) return null
    verifying.value = true
    verificationHint.value = ''
    try {
      const result = await tutorialV2Api.verify(
        currentRun.value.id,
        currentStep.value.id,
        { visited_route: targetVisited.value ? visitedRoute : '' },
      )
      currentRun.value = result.run
      verificationHint.value = result.hint
      targetVisited.value = false
      await loadCourses()
      return result
    } catch (error) {
      verificationHint.value = safeErrorHint(error)
      throw error
    } finally {
      verifying.value = false
    }
  }

  async function resetCourse(runId: string) {
    loading.value = true
    try {
      currentRun.value = await tutorialV2Api.reset(runId)
      targetVisited.value = false
      verificationHint.value = '已创建新的教学代次，旧数据将在 7 天后清理。'
      await loadCourses()
      return currentRun.value
    } catch (error) {
      errorHint.value = safeErrorHint(error)
      throw error
    } finally {
      loading.value = false
    }
  }

  function markTargetVisited() {
    targetVisited.value = true
  }

  async function loadReports() {
    reports.value = await tutorialV2Api.reports()
    return reports.value
  }

  return {
    courses,
    currentRun,
    currentStep,
    isActive,
    loading,
    verifying,
    errorHint,
    verificationHint,
    targetVisited,
    reports,
    loadCourses,
    restoreCurrent,
    startCourse,
    enterRun,
    leaveCurrent,
    verifyCurrent,
    resetCourse,
    markTargetVisited,
    loadReports,
  }
})
