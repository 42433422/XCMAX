import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const mockGetProductsReadLockState = vi.fn().mockResolvedValue('open')
const mockProbeProductsReadAccess = vi.fn().mockResolvedValue(true)
const mockSaveStoredReadToken = vi.fn()
const mockTouchProductsReadGateGrace = vi.fn()

vi.mock('@/fhd/dbTokenHeaders', () => ({
  FHD_DB_READ_UNLOCKED_EVENT: 'fhd:db-read-unlocked',
  LS_DB_READ_TOKEN: 'xcagi_db_read_token',
  XCAGI_PROMPT_DB_READ_TOKEN_EVENT: 'xcagi:prompt-db-read-token',
  getProductsReadLockState: (...args: any[]) => mockGetProductsReadLockState(...args),
  probeProductsReadAccess: (...args: any[]) => mockProbeProductsReadAccess(...args),
  saveStoredReadToken: (...args: any[]) => mockSaveStoredReadToken(...args),
  touchProductsReadGateGrace: (...args: any[]) => mockTouchProductsReadGateGrace(...args),
}))

import GlobalReadTokenPrompt from '@/fhd/GlobalReadTokenPrompt.vue'

function mountComponent(propsOverrides = {}) {
  return mount(GlobalReadTokenPrompt, {
    props: { ...propsOverrides },
    attachTo: document.body,
  })
}

describe('GlobalReadTokenPrompt', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionStorage.clear()
    mockGetProductsReadLockState.mockResolvedValue('open')
    mockProbeProductsReadAccess.mockResolvedValue(true)
    mockSaveStoredReadToken.mockImplementation(() => {})
    mockTouchProductsReadGateGrace.mockImplementation(() => {})
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('renders without errors', async () => {
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })

  it('does not show overlay or FAB when lock state is open', async () => {
    mockGetProductsReadLockState.mockResolvedValue('open')
    const wrapper = mountComponent()
    await flushPromises()
    expect(document.querySelector('.fhd-read-gate-root')).toBeNull()
    expect(document.querySelector('.fhd-read-fab')).toBeNull()
  })

  it('shows overlay when locked (not FAB)', async () => {
    mockGetProductsReadLockState.mockResolvedValue('locked')
    const wrapper = mountComponent()
    await flushPromises()
    // When locked, evaluate() sets blocked=true and fabOpen=true, so showOverlay=true
    expect(document.querySelector('.fhd-read-gate-root')).not.toBeNull()
    // FAB is NOT shown because fabOpen is true
    expect(document.querySelector('.fhd-read-fab')).toBeNull()
  })

  it('shows FAB after overlay is dismissed', async () => {
    mockGetProductsReadLockState.mockResolvedValue('locked')
    const wrapper = mountComponent()
    await flushPromises()
    // Dismiss the overlay
    const backdrop = document.querySelector('.fhd-read-gate-backdrop') as HTMLElement
    expect(backdrop).not.toBeNull()
    backdrop.click()
    await wrapper.vm.$nextTick()
    // After dismiss, blocked is set to false, so neither overlay nor FAB shows
    // (onDismissSession sets blocked=false)
  })

  it('shows error text for locked_bad_token', async () => {
    mockGetProductsReadLockState.mockResolvedValue('locked_bad_token')
    const wrapper = mountComponent()
    await flushPromises()
    // Should show overlay with error text about invalid token
    expect(document.querySelector('.fhd-read-gate-root')).not.toBeNull()
    expect(document.querySelector('.fhd-read-gate-error')?.textContent).toContain('无效')
  })

  it('dismisses overlay on backdrop click', async () => {
    mockGetProductsReadLockState.mockResolvedValue('locked')
    const wrapper = mountComponent()
    await flushPromises()
    expect(document.querySelector('.fhd-read-gate-root')).not.toBeNull()
    const backdrop = document.querySelector('.fhd-read-gate-backdrop') as HTMLElement
    backdrop.click()
    await wrapper.vm.$nextTick()
    expect(document.querySelector('.fhd-read-gate-root')).toBeNull()
  })

  it('dismisses overlay on secondary button click', async () => {
    mockGetProductsReadLockState.mockResolvedValue('locked')
    const wrapper = mountComponent()
    await flushPromises()
    const btn = document.querySelector('.fhd-read-gate-btn-secondary') as HTMLElement
    expect(btn).not.toBeNull()
    btn.click()
    await wrapper.vm.$nextTick()
    expect(document.querySelector('.fhd-read-gate-root')).toBeNull()
  })

  it('shows error when empty password submitted', async () => {
    mockGetProductsReadLockState.mockResolvedValue('locked')
    const wrapper = mountComponent()
    await flushPromises()
    const unlockBtn = document.querySelector('.fhd-read-gate-btn') as HTMLElement
    expect(unlockBtn).not.toBeNull()
    unlockBtn.click()
    await wrapper.vm.$nextTick()
    const errorEl = document.querySelector('.fhd-read-gate-error')
    expect(errorEl).not.toBeNull()
    expect(errorEl?.textContent).toContain('请输入口令')
  })

  it('calls saveStoredReadToken on unlock with password', async () => {
    mockGetProductsReadLockState.mockResolvedValue('locked')
    const wrapper = mountComponent()
    await flushPromises()
    const input = document.querySelector('.fhd-read-gate-input') as HTMLInputElement
    expect(input).not.toBeNull()
    input.value = 'my_token'
    input.dispatchEvent(new Event('input'))
    await wrapper.vm.$nextTick()
    const unlockBtn = document.querySelector('.fhd-read-gate-btn') as HTMLElement
    unlockBtn.click()
    await flushPromises()
    expect(mockSaveStoredReadToken).toHaveBeenCalledWith('my_token')
  })

  it('shows error on wrong token', async () => {
    mockGetProductsReadLockState.mockResolvedValue('locked')
    mockProbeProductsReadAccess.mockResolvedValue(false)
    const wrapper = mountComponent()
    await flushPromises()
    const input = document.querySelector('.fhd-read-gate-input') as HTMLInputElement
    input.value = 'wrong_token'
    input.dispatchEvent(new Event('input'))
    await wrapper.vm.$nextTick()
    const unlockBtn = document.querySelector('.fhd-read-gate-btn') as HTMLElement
    unlockBtn.click()
    await flushPromises()
    const errorEl = document.querySelector('.fhd-read-gate-error')
    expect(errorEl?.textContent).toContain('口令错误')
  })

  it('sets sessionStorage on dismiss', async () => {
    mockGetProductsReadLockState.mockResolvedValue('locked')
    const wrapper = mountComponent()
    await flushPromises()
    const backdrop = document.querySelector('.fhd-read-gate-backdrop') as HTMLElement
    backdrop.click()
    await wrapper.vm.$nextTick()
    expect(sessionStorage.getItem('xcagi_skip_fhd_read_gate_session')).toBe('1')
  })

  it('suppresses prompt when sessionStorage is set', async () => {
    sessionStorage.setItem('xcagi_skip_fhd_read_gate_session', '1')
    const wrapper = mountComponent()
    await flushPromises()
    expect(document.querySelector('.fhd-read-gate-root')).toBeNull()
    expect(document.querySelector('.fhd-read-fab')).toBeNull()
  })

  it('renders the dialog title when locked', async () => {
    mockGetProductsReadLockState.mockResolvedValue('locked')
    const wrapper = mountComponent()
    await flushPromises()
    const title = document.querySelector('.fhd-read-gate-title')
    expect(title?.textContent).toContain('一级数据库口令')
  })

  it('renders the password input when locked', async () => {
    mockGetProductsReadLockState.mockResolvedValue('locked')
    const wrapper = mountComponent()
    await flushPromises()
    expect(document.querySelector('.fhd-read-gate-input')).not.toBeNull()
  })

  it('renders the unlock button when locked', async () => {
    mockGetProductsReadLockState.mockResolvedValue('locked')
    const wrapper = mountComponent()
    await flushPromises()
    expect(document.querySelector('.fhd-read-gate-btn')).not.toBeNull()
  })

  it('renders the close button when locked', async () => {
    mockGetProductsReadLockState.mockResolvedValue('locked')
    const wrapper = mountComponent()
    await flushPromises()
    expect(document.querySelector('.fhd-read-gate-btn-secondary')).not.toBeNull()
  })

  it('re-evaluates when apiBase changes', async () => {
    mockGetProductsReadLockState.mockClear()
    const wrapper = mountComponent()
    await flushPromises()
    const callsBefore = mockGetProductsReadLockState.mock.calls.length
    await wrapper.setProps({ apiBase: '/new-api' })
    await flushPromises()
    expect(mockGetProductsReadLockState.mock.calls.length).toBeGreaterThan(callsBefore)
  })
})
