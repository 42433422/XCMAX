import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import AIOpenPanel from './AIOpenPanel.vue'

vi.mock('@/utils/apiBase', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/utils/apiBase')>()
  return {
    ...actual,
    apiFetch: vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }),
    getApiBase: vi.fn(() => 'http://localhost:5100'),
  }
})
vi.mock('@/utils/aiopenMcpInstall', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/utils/aiopenMcpInstall')>()
  return {
    ...actual,
    buildAiopenOneLiner: vi.fn(() => 'one-liner'),
    fetchMcpHealth: vi.fn().mockResolvedValue({ ok: true }),
  }
})

describe('AIOpenPanel.vue', () => {
  it('renders AIOPEN hero', () => {
    const wrapper = mount(AIOpenPanel, {
      global: {
        stubs: { RouterLink: true },
      },
    })
    expect(wrapper.find('.aiopen-shell').exists()).toBe(true)
    expect(wrapper.text()).toContain('AIOPEN')
  })

  it('emits back on header click', async () => {
    const wrapper = mount(AIOpenPanel, {
      global: { stubs: { RouterLink: true } },
    })
    await wrapper.find('.aiopen-back').trigger('click')
    expect(wrapper.emitted('back')).toBeTruthy()
  })
})
