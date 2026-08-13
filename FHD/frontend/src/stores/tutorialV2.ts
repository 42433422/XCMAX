import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { ApiError } from '@/api'
import {
  tutorialV2Api,
  type TutorialCourseDTO,
  type TutorialRunDTO,
} from '@/api/tutorialV2'

export function tutorialRunAllowsRoute(
  run: TutorialRunDTO | null | undefined,
  routeName: string,
): boolean {
  if (!run || !['active', 'completed'].includes(run.status)) return false
  const target = String(routeName || '').trim()
  return Boolean(target && run.steps.some((step) => step.route_name === target))
}

export function activeTutorialRunAllowsRoute(routeName: string): boolean {
  try {
    return tutorialRunAllowsRoute(useTutorialV2Store().currentRun, routeName)
  } catch {
    return false
  }
}

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

  async function verifyCurrent(visitedRoute: string, targetVisible = false) {
    if (!currentRun.value || !currentStep.value) return null
    verifying.value = true
    verificationHint.value = ''
    const verifiedTitle = currentStep.value.title
    try {
      const result = await tutorialV2Api.verify(
        currentRun.value.id,
        currentStep.value.id,
        {
          visited_route: targetVisited.value ? visitedRoute : '',
          target_visible: targetVisited.value && targetVisible,
        },
      )
      currentRun.value = result.run
      if (result.evidence.status === 'passed') {
        const next = result.run.steps.find((item) => item.id === result.run.current_step_id)
        verificationHint.value = result.run.status === 'completed'
          ? `“${verifiedTitle}”验证通过，本课程已完成。`
          : `“${verifiedTitle}”验证通过；现在进入“${next?.title || '下一步'}”。`
        targetVisited.value = false
      } else {
        verificationHint.value = result.hint
      }
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
      const previousCourseId = courses.value.find((course) => course.run?.id === runId)?.id
      currentRun.value = await tutorialV2Api.reset(runId)
      targetVisited.value = false
      verificationHint.value = previousCourseId && previousCourseId !== currentRun.value.course_id
        ? '已创建新的教学代次。新空间没有旧业务数据，请先重新完成前置课程；旧数据将在 7 天后清理。'
        : '已创建新的教学代次，旧数据将在 7 天后清理。'
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
