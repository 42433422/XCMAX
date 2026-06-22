import { describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { WIZARD_FRONTEND_SKIP_KEY, WIZARD_STEPS } from '../types'
import { useModAuthoringWizard } from './useModAuthoringWizard'

function makeCtx() {
  return {
    modDescriptionLine: ref(''),
    modData: ref<any>(null),
    workflowEmployeesRows: ref<any[]>([]),
    employeeReadiness: ref<any>(null),
    fileSet: ref(new Set<string>()),
    checklist: ref([{ ok: false }, { ok: true }]),
  }
}

describe('useModAuthoringWizard', () => {
  it('tracks step completion, navigation bounds, and frontend skip storage', () => {
    localStorage.removeItem(WIZARD_FRONTEND_SKIP_KEY)
    const ctx = makeCtx()
    const wizard = useModAuthoringWizard(ctx as any)

    expect(wizard.WIZARD_STEPS).toBe(WIZARD_STEPS)
    expect(wizard.stepCompletion.value).toEqual([false, false, false, false])
    wizard.goPrev()
    expect(wizard.currentStep.value).toBe(1)
    wizard.goToStep(99)
    expect(wizard.currentStep.value).toBe(1)

    ctx.modDescriptionLine.value = '行业 Mod'
    ctx.modData.value = {
      manifest: { industry: { id: '  retail  ' } },
      validation_ok: true,
    }
    ctx.workflowEmployeesRows.value = [{ id: 'emp' }]
    ctx.employeeReadiness.value = { ok: true }
    ctx.fileSet.value = new Set(['frontend/routes.js'])
    ctx.checklist.value = [{ ok: true }, { ok: true }]

    expect(wizard.stepCompletion.value).toEqual([true, true, true, true])
    wizard.goNext()
    wizard.goNext()
    wizard.goNext()
    wizard.goNext()
    expect(wizard.currentStep.value).toBe(4)
    wizard.goPrev()
    expect(wizard.currentStep.value).toBe(3)
    wizard.goToStep(2)
    expect(wizard.currentStep.value).toBe(2)
    wizard.goToStep(0)
    expect(wizard.currentStep.value).toBe(2)

    ctx.fileSet.value = new Set()
    expect(wizard.step3Done.value).toBe(false)
    wizard.markFrontendSkipped()
    expect(wizard.frontendSkipped.value).toBe(true)
    expect(wizard.step3Done.value).toBe(true)
    expect(localStorage.getItem(WIZARD_FRONTEND_SKIP_KEY)).toBe('1')
    wizard.clearFrontendSkip()
    expect(wizard.frontendSkipped.value).toBe(false)
    expect(localStorage.getItem(WIZARD_FRONTEND_SKIP_KEY)).toBeNull()
  })

  it('loads existing frontend skip state and handles incomplete context shapes', () => {
    localStorage.setItem(WIZARD_FRONTEND_SKIP_KEY, '1')
    const ctx = makeCtx()
    ctx.modDescriptionLine.value = 'desc'
    ctx.modData.value = { manifest: { industry: null }, validation_ok: true }
    ctx.workflowEmployeesRows.value = [{ id: 'emp' }]
    ctx.employeeReadiness.value = { ok: false }
    ctx.checklist.value = [{ ok: true }, { ok: false }]

    const wizard = useModAuthoringWizard(ctx as any)

    expect(wizard.frontendSkipped.value).toBe(true)
    expect(wizard.step1Done.value).toBe(false)
    expect(wizard.step2Done.value).toBe(false)
    expect(wizard.step3Done.value).toBe(true)
    expect(wizard.step4Done.value).toBe(false)

    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota')
    })
    const removeItem = vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new Error('quota')
    })
    expect(() => wizard.markFrontendSkipped()).not.toThrow()
    expect(() => wizard.clearFrontendSkip()).not.toThrow()
    setItem.mockRestore()
    removeItem.mockRestore()
  })
})
