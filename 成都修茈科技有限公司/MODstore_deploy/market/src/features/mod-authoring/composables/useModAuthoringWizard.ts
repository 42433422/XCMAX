import { computed, ref } from 'vue'
import { WIZARD_FRONTEND_SKIP_KEY, WIZARD_STEPS } from '../types'
import type { ModAuthoringContext } from './useModAuthoringContext'

export function useModAuthoringWizard(ctx: ModAuthoringContext) {
  const currentStep = ref(1)
  const frontendSkipped = ref(
    typeof localStorage !== 'undefined' && localStorage.getItem(WIZARD_FRONTEND_SKIP_KEY) === '1',
  )

  const step1Done = computed(() => {
    const desc = ctx.modDescriptionLine.value
    const industry = (ctx.modData.value as { manifest?: { industry?: { id?: string } } } | null)?.manifest
      ?.industry
    const id = industry && typeof industry === 'object' ? String(industry.id || '').trim() : ''
    return Boolean(desc) && Boolean(id)
  })

  const step2Done = computed(() => {
    if (ctx.workflowEmployeesRows.value.length === 0) return false
    return Boolean(ctx.employeeReadiness.value?.ok)
  })

  const step3Done = computed(() => {
    if (frontendSkipped.value) return true
    return ctx.fileSet.value.has('frontend/routes.js')
  })

  const step4Done = computed(() => {
    const ok = Boolean((ctx.modData.value as { validation_ok?: boolean } | null)?.validation_ok)
    const checklistOk = ctx.checklist.value.every((r) => r.ok)
    return ok && checklistOk
  })

  const stepCompletion = computed(() => [step1Done.value, step2Done.value, step3Done.value, step4Done.value])

  function markFrontendSkipped() {
    frontendSkipped.value = true
    try {
      localStorage.setItem(WIZARD_FRONTEND_SKIP_KEY, '1')
    } catch {
      /* ignore */
    }
  }

  function clearFrontendSkip() {
    frontendSkipped.value = false
    try {
      localStorage.removeItem(WIZARD_FRONTEND_SKIP_KEY)
    } catch {
      /* ignore */
    }
  }

  function goNext() {
    if (currentStep.value < WIZARD_STEPS.length) currentStep.value += 1
  }

  function goPrev() {
    if (currentStep.value > 1) currentStep.value -= 1
  }

  function goToStep(n: number) {
    if (n >= 1 && n <= WIZARD_STEPS.length) currentStep.value = n
  }

  return {
    WIZARD_STEPS,
    currentStep,
    step1Done,
    step2Done,
    step3Done,
    step4Done,
    stepCompletion,
    frontendSkipped,
    markFrontendSkipped,
    clearFrontendSkip,
    goNext,
    goPrev,
    goToStep,
  }
}

export type ModAuthoringWizard = ReturnType<typeof useModAuthoringWizard>
