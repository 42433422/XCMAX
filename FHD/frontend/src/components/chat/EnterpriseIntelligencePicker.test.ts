// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import type { API } from 'nouislider'
import { beforeEach, describe, expect, it, onTestFinished, vi } from 'vitest'
import { nextTick, reactive } from 'vue'
import EnterpriseIntelligencePicker from './EnterpriseIntelligencePicker.vue'

const { apiFetch, create } = vi.hoisted(() => ({
  apiFetch: vi.fn<(_path: string, options?: RequestInit) => Promise<Response>>(),
  create: vi.fn(),
}))

const profile = reactive({
  loaded: true,
  tenantId: 42,
  isAdminAccount: false,
  isImpersonating: false,
  accountKind: 'enterprise',
  userRole: 'tenant:owner',
})

vi.mock('@/stores/accountProfile', () => ({ useAccountProfileStore: () => profile }))
vi.mock('@/utils/apiBase', () => ({ apiFetch, DEFAULT_MOD_API_TIMEOUT_MS: 15000 }))
vi.mock('nouislider', () => ({ create, PipsMode: { Steps: 'steps' } }))

function mockSlider() {
  let position = 2
  const listeners = new Map<string, Parameters<API['on']>[1]>()
  const slider = {
    on: vi.fn<API['on']>((event, callback) => { listeners.set(event, callback) }),
    get: vi.fn(() => position),
    set: vi.fn((level: number) => { position = level }),
    disable: vi.fn(),
    enable: vi.fn(),
    destroy: vi.fn(),
  }
  create.mockReturnValue(slider)
  return {
    slider,
    emit(event: 'update' | 'change', level: number) {
      position = level
      const listener = listeners.get(event)
      if (!listener) throw new Error(`Missing noUiSlider ${event} listener`)
      const instance = slider as unknown as API
      listener.call(instance, [String(level)], 0, [level], false, [(level - 1) * 20], instance)
    },
  }
}

function enterpriseLevel(level: number, revision: number, editable = true) {
  return Response.json({ owner_id: `tenant:${profile.tenantId}`, editable, level, revision })
}

async function openPicker() {
  const wrapper = mount(EnterpriseIntelligencePicker, { attachTo: document.body })
  onTestFinished(() => { wrapper.unmount() })
  await flushPromises()
  const trigger = wrapper.get<HTMLButtonElement>('.enterprise-level-trigger')
  await trigger.trigger('click')
  await flushPromises()
  return trigger
}

describe('EnterpriseIntelligencePicker', () => {
  beforeEach(() => {
    apiFetch.mockReset()
    create.mockReset()
    profile.tenantId = 42
  })

  it('previews drag updates and saves one enterprise-scoped change on release', async () => {
    const { slider, emit } = mockSlider()
    let resolveSave!: (response: Response) => void
    const save = new Promise<Response>(resolve => { resolveSave = resolve })
    apiFetch.mockResolvedValueOnce(enterpriseLevel(2, 7)).mockReturnValueOnce(save)
    const trigger = await openPicker()
    expect(trigger.attributes('aria-label')).toBe('本企业智能等级 L2 · 执行智能')

    expect(create).toHaveBeenCalledWith(expect.any(HTMLElement), expect.objectContaining({ behaviour: 'tap-smooth-steps' }))
    emit('update', 3.1)
    emit('update', 3.8)
    await nextTick()
    expect(document.querySelector('.enterprise-level-preview strong')?.textContent).toBe('自治智能')
    const track = document.querySelector<HTMLElement>('.enterprise-level-track')
    expect(Number(track?.style.getPropertyValue('--level-progress'))).toBeCloseTo(0.56)
    expect(apiFetch).toHaveBeenCalledTimes(1)

    emit('change', 4)
    emit('change', 5)
    await nextTick()
    expect(apiFetch).toHaveBeenCalledTimes(2)
    expect(apiFetch).toHaveBeenLastCalledWith('/api/workspace/intelligence', expect.objectContaining({
      method: 'PUT',
      body: JSON.stringify({ level: 4, expected_owner_id: 'tenant:42', expected_revision: 7 }),
    }))
    expect(slider.disable).toHaveBeenCalledOnce()
    expect(trigger.attributes('aria-label')).toBe('本企业智能等级 L2 · 执行智能')

    resolveSave(enterpriseLevel(4, 8))
    await flushPromises()
    expect(trigger.attributes('aria-label')).toBe('本企业智能等级 L4 · 自治智能')
  })

  it('keeps the current level read-only when the account lacks edit access', async () => {
    const { slider, emit } = mockSlider()
    apiFetch.mockResolvedValueOnce(enterpriseLevel(2, 7, false))
    const trigger = await openPicker()
    expect(slider.disable).toHaveBeenCalledOnce()
    expect(document.querySelector('.enterprise-level-status')?.textContent).toBe('仅企业主账号可修改')

    emit('change', 3)
    await flushPromises()
    expect(apiFetch).toHaveBeenCalledTimes(1)
    expect(trigger.attributes('aria-label')).toBe('本企业智能等级 L2 · 执行智能')
  })
})
