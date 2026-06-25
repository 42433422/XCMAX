import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import DiscoverView from './DiscoverView.vue'

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/discover', name: 'discover', component: DiscoverView },
      { path: '/mod-store', name: 'mod-store', component: { template: '<div />' } },
      { path: '/tools', name: 'tools', component: { template: '<div />' } },
    ],
  })
}

async function mountView() {
  const router = makeRouter()
  await router.push('/discover')
  await router.isReady()
  const wrapper = mount(DiscoverView, {
    global: {
      plugins: [router],
      stubs: { RouterLink: { template: '<a><slot /></a>' } },
    },
  })
  return { wrapper, router }
}

describe('DiscoverView.vue', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('renders the header with title and subtitle', async () => {
    const { wrapper } = await mountView()
    expect(wrapper.find('.discover-view__header h1').text()).toBe('发现')
    expect(wrapper.find('.discover-view__header p').text()).toBe('工作台、扩展与市场、常用工具')
  })

  it('renders the workbench section', async () => {
    const { wrapper } = await mountView()
    expect(wrapper.find('.discover-section h2').text()).toBe('工作台')
    expect(wrapper.find('.discover-cell strong').text()).toBe('工作台')
  })

  it('renders the extensions and market section', async () => {
    const { wrapper } = await mountView()
    const sections = wrapper.findAll('.discover-section')
    expect(sections).toHaveLength(2)
    expect(sections[1].find('h2').text()).toBe('扩展与市场')
    const cells = sections[1].findAll('.discover-cell')
    expect(cells).toHaveLength(2)
    expect(cells[0].find('strong').text()).toBe('MOD 市场')
    expect(cells[1].find('strong').text()).toBe('工具箱')
  })

  it('opens workbench URL in new tab when workbench cell clicked', async () => {
    const openSpy = vi.spyOn(window, 'open').mockReturnValue(null)
    const { wrapper } = await mountView()
    const workbenchCell = wrapper.findAll('.discover-cell')[0]
    await workbenchCell.trigger('click')
    expect(openSpy).toHaveBeenCalledTimes(1)
    const url = openSpy.mock.calls[0][0]
    expect(url).toContain('xiu-ci.com/market/workbench/unified')
    expect(openSpy.mock.calls[0][1]).toBe('_blank')
    expect(openSpy.mock.calls[0][2]).toBe('noopener,noreferrer')
    openSpy.mockRestore()
  })

  it('navigates to mod-store when MOD market cell clicked', async () => {
    const { wrapper, router } = await mountView()
    const pushSpy = vi.spyOn(router, 'push')
    const modCell = wrapper.findAll('.discover-cell')[1]
    await modCell.trigger('click')
    expect(pushSpy).toHaveBeenCalledWith({ name: 'mod-store' })
  })

  it('navigates to tools when toolbox cell clicked', async () => {
    const { wrapper, router } = await mountView()
    const pushSpy = vi.spyOn(router, 'push')
    const toolsCell = wrapper.findAll('.discover-cell')[2]
    await toolsCell.trigger('click')
    expect(pushSpy).toHaveBeenCalledWith({ name: 'tools' })
  })

  it('uses custom modstore web URL from env', async () => {
    vi.stubEnv('VITE_MODSTORE_WEB_URL', 'https://custom.example.com/workbench/')
    const openSpy = vi.spyOn(window, 'open').mockReturnValue(null)
    const { wrapper } = await mountView()
    const workbenchCell = wrapper.findAll('.discover-cell')[0]
    await workbenchCell.trigger('click')
    expect(openSpy.mock.calls[0][0]).toBe('https://custom.example.com/workbench')
    openSpy.mockRestore()
    vi.unstubAllEnvs()
  })

  it('trims trailing slash from modstore web URL', async () => {
    vi.stubEnv('VITE_MODSTORE_WEB_URL', 'https://example.com/market/')
    const openSpy = vi.spyOn(window, 'open').mockReturnValue(null)
    const { wrapper } = await mountView()
    await wrapper.findAll('.discover-cell')[0].trigger('click')
    expect(openSpy.mock.calls[0][0]).toBe('https://example.com/market')
    openSpy.mockRestore()
    vi.unstubAllEnvs()
  })

  it('renders all discover cells as buttons', async () => {
    const { wrapper } = await mountView()
    const cells = wrapper.findAll('.discover-cell')
    expect(cells).toHaveLength(3)
    cells.forEach((cell) => {
      expect(cell.element.tagName).toBe('BUTTON')
    })
  })
})
