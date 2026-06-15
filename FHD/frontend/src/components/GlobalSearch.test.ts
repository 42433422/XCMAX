import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import GlobalSearch from './GlobalSearch.vue'

vi.mock('@/api/search', () => ({
  searchApi: {
    searchV0: vi.fn(),
  },
}))

import { searchApi } from '@/api/search'

describe('GlobalSearch', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders search trigger button', () => {
    const wrapper = mount(GlobalSearch)
    expect(wrapper.find('.global-search-trigger').exists()).toBe(true)
    expect(wrapper.find('.global-search-trigger').text()).toContain('搜索')
  })

  it('opens panel on trigger click', async () => {
    const wrapper = mount(GlobalSearch)
    await wrapper.find('.global-search-trigger').trigger('click')
    expect(wrapper.find('.global-search-panel').exists()).toBe(true)
  })

  it('renders search input when open', async () => {
    const wrapper = mount(GlobalSearch)
    await wrapper.find('.global-search-trigger').trigger('click')
    expect(wrapper.find('.global-search-input').exists()).toBe(true)
  })

  it('renders tabs when open', async () => {
    const wrapper = mount(GlobalSearch)
    await wrapper.find('.global-search-trigger').trigger('click')
    const tabs = wrapper.findAll('.tab')
    expect(tabs.length).toBe(3)
    expect(tabs[0].text()).toBe('全部')
    expect(tabs[1].text()).toBe('产品')
    expect(tabs[2].text()).toBe('客户')
  })

  it('closes panel on Esc key', async () => {
    const wrapper = mount(GlobalSearch)
    await wrapper.find('.global-search-trigger').trigger('click')
    expect(wrapper.find('.global-search-panel').exists()).toBe(true)
    await wrapper.find('.global-search').trigger('keydown.esc')
    expect(wrapper.find('.global-search-panel').exists()).toBe(false)
  })

  it('shows loading state during search', async () => {
    let resolveSearch: (v: any) => void
    vi.mocked(searchApi.searchV0).mockImplementation(
      () => new Promise((resolve) => { resolveSearch = resolve })
    )
    const wrapper = mount(GlobalSearch)
    await wrapper.find('.global-search-trigger').trigger('click')
    await wrapper.find('input').setValue('test query')
    await wrapper.find('input').trigger('keydown.enter')
    expect(wrapper.find('.global-search-status').text()).toContain('搜索中')
    resolveSearch!({ success: true, results: {} })
  })

  it('shows error state on search failure', async () => {
    vi.mocked(searchApi.searchV0).mockResolvedValueOnce({
      success: false,
    } as any)
    const wrapper = mount(GlobalSearch)
    await wrapper.find('.global-search-trigger').trigger('click')
    await wrapper.find('input').setValue('test')
    await wrapper.find('input').trigger('keydown.enter')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.error').exists()).toBe(true)
  })

  it('shows error state on search exception', async () => {
    vi.mocked(searchApi.searchV0).mockRejectedValueOnce(new Error('Network error'))
    const wrapper = mount(GlobalSearch)
    await wrapper.find('.global-search-trigger').trigger('click')
    await wrapper.find('input').setValue('test')
    await wrapper.find('input').trigger('keydown.enter')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.error').exists()).toBe(true)
  })

  it('shows product results', async () => {
    vi.mocked(searchApi.searchV0).mockResolvedValueOnce({
      success: true,
      results: {
        products: { data: [{ name: 'Product A' }, { name: 'Product B' }] },
        customers: { data: [] },
      },
    } as any)
    const wrapper = mount(GlobalSearch)
    await wrapper.find('.global-search-trigger').trigger('click')
    await wrapper.find('input').setValue('prod')
    await wrapper.find('input').trigger('keydown.enter')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.result-group-title').text()).toBe('产品')
  })

  it('shows customer results', async () => {
    vi.mocked(searchApi.searchV0).mockResolvedValueOnce({
      success: true,
      results: {
        products: { data: [] },
        customers: { data: [{ customer_name: 'Customer A' }] },
      },
    } as any)
    const wrapper = mount(GlobalSearch)
    await wrapper.find('.global-search-trigger').trigger('click')
    await wrapper.find('input').setValue('cust')
    await wrapper.find('input').trigger('keydown.enter')
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('.result-group-title').some(el => el.text() === '客户')).toBe(true)
  })

  it('shows no results message when search returns empty', async () => {
    vi.mocked(searchApi.searchV0).mockResolvedValueOnce({
      success: true,
      results: {
        products: { data: [] },
        customers: { data: [] },
      },
    } as any)
    const wrapper = mount(GlobalSearch)
    await wrapper.find('.global-search-trigger').trigger('click')
    await wrapper.find('input').setValue('nothing')
    await wrapper.find('input').trigger('keydown.enter')
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('无结果')
  })

  it('clears results when query is empty', async () => {
    const wrapper = mount(GlobalSearch)
    await wrapper.find('.global-search-trigger').trigger('click')
    await wrapper.find('input').setValue('')
    await wrapper.find('input').trigger('keydown.enter')
    await wrapper.vm.$nextTick()
    expect(searchApi.searchV0).not.toHaveBeenCalled()
  })

  it('switches scope on tab click', async () => {
    const wrapper = mount(GlobalSearch)
    await wrapper.find('.global-search-trigger').trigger('click')
    const tabs = wrapper.findAll('.tab')
    await tabs[1].trigger('click')
    expect(tabs[1].classes()).toContain('active')
  })

  it('responds to Cmd+K global shortcut', async () => {
    const wrapper = mount(GlobalSearch)
    const event = new KeyboardEvent('keydown', { key: 'k', metaKey: true })
    window.dispatchEvent(event)
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.global-search-panel').exists()).toBe(true)
  })

  it('closes panel on Cmd+K when open', async () => {
    const wrapper = mount(GlobalSearch)
    await wrapper.find('.global-search-trigger').trigger('click')
    expect(wrapper.find('.global-search-panel').exists()).toBe(true)
    const event = new KeyboardEvent('keydown', { key: 'k', metaKey: true })
    window.dispatchEvent(event)
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.global-search-panel').exists()).toBe(false)
  })
})
