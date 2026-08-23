import { beforeEach, describe, expect, it } from 'vitest'
import { useApprovalMode } from './useApprovalMode'

describe('useApprovalMode', () => {
  beforeEach(() => {
    const { setEnabled, setMode } = useApprovalMode()
    setEnabled(false)
    setMode('manual')
  })

  it('defaults to disabled manual mode', () => {
    const { state } = useApprovalMode()
    expect(state.enabled).toBe(false)
    expect(state.mode).toBe('manual')
  })

  it('setEnabled toggles enabled', () => {
    const { state, setEnabled } = useApprovalMode()
    setEnabled(true)
    expect(state.enabled).toBe(true)
  })

  it('setMode switches to auto', () => {
    const { state, setMode } = useApprovalMode()
    setMode('auto')
    expect(state.mode).toBe('auto')
  })
})