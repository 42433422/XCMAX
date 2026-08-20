import { describe, expect, it, beforeEach } from 'vitest'
import { LS_PRODUCT_FLOW_LAST_STEP, readProductFlowLastStep, resolveProductFlowEntryStep, saveProductFlowLastStep } from './productFlow'

describe('productFlow last step resume', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('resumes from saved step when query is empty', () => {
    saveProductFlowLastStep('industry')
    expect(readProductFlowLastStep()).toBe('industry')
    expect(resolveProductFlowEntryStep(undefined)).toBe('industry')
  })

  it('prefers explicit query step', () => {
    saveProductFlowLastStep('host-pack')
    expect(resolveProductFlowEntryStep('welcome')).toBe('welcome')
  })

  it('persists under tenant scoped key', () => {
    saveProductFlowLastStep('host-pack')
    expect(localStorage.getItem(LS_PRODUCT_FLOW_LAST_STEP)).toBe('host-pack')
  })
})
