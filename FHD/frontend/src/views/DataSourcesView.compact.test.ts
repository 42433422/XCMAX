import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import DataSourcesView from '../../../mods/bridge/xcagi-erp-domain-bridge/frontend/views/DataSourcesView.vue'

vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }) }))
vi.mock('@/api', () => ({ api: { get: vi.fn().mockResolvedValue({}), post: vi.fn() } }))
vi.mock('@/api/privateDbAssistant', () => ({ default: { status: vi.fn().mockResolvedValue({ success: false }), listSources: vi.fn().mockResolvedValue({ data: [] }) } }))
afterEach(() => vi.unstubAllEnvs())

it('filters admin sources by category and keeps message drafts while switching sections', async () => {
  vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '1')
  const wrapper = mount(DataSourcesView, { attachTo: document.body })
  try {
    await flushPromises()
    expect(wrapper.findAll('.data-source-card')).toHaveLength(1)
    await wrapper.get('select[aria-label="数据源类别"]').setValue('mail')
    expect(wrapper.findAll('.data-source-card')).toHaveLength(3)
    expect(wrapper.findAll('.data-source-card').every(card => /邮箱/.test(card.text()))).toBe(true)
    const nav = wrapper.findAll('.admin-section-nav button')
    await nav[2].trigger('click')
    await wrapper.get('textarea').setValue('尚未发送的草稿')
    await nav[0].trigger('click')
    expect(wrapper.get('textarea').isVisible()).toBe(false)
    await nav[2].trigger('click')
    expect(wrapper.get('textarea').isVisible()).toBe(true)
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('尚未发送的草稿')
  } finally { wrapper.unmount() }
})
