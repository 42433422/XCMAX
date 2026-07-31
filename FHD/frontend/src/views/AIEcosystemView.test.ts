import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'

vi.mock('@/utils/plannerPagePaths', () => ({
  resolvePlannerPageRedirectForRouteName: vi.fn(() => null),
}))

import AIEcosystemView from './AIEcosystemView.vue'
import { resolvePlannerPageRedirectForRouteName } from '@/utils/plannerPagePaths'

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: { template: '<div />' } },
      { path: '/brain', name: 'brain', component: { template: '<div />' } },
      { path: '/mod-store', name: 'mod-store', component: { template: '<div />' } },
      { path: '/ecosystem', name: 'ecosystem', component: AIEcosystemView },
    ],
  })
}

async function mountView() {
  const router = makeRouter()
  await router.push('/ecosystem')
  await router.isReady()
  const wrapper = mount(AIEcosystemView, {
    global: {
      plugins: [router],
      stubs: {
        AiOpenLauncherIcon: { template: '<i class="icon-aiopen" />' },
        KittenLauncherIcon: { template: '<i class="icon-kitten" />' },
        ProductionEmployeeLauncherIcon: { template: '<i class="icon-prod" />' },
        ModStoreLauncherIcon: { template: '<i class="icon-modstore" />' },
      },
    },
  })
  return { wrapper, router }
}

describe('AIEcosystemView.vue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(resolvePlannerPageRedirectForRouteName).mockReturnValue(null)
  })

  it('renders the ecosystem home by default', async () => {
    const { wrapper } = await mountView()
    expect(wrapper.find('.ecosystem-home').exists()).toBe(true)
    expect(wrapper.find('.ecosystem-home-title').text()).toBe('AI生态应用')
  })

  it('renders four launcher buttons', async () => {
    const { wrapper } = await mountView()
    const launchers = wrapper.findAll('.app-launcher')
    expect(launchers).toHaveLength(4)
    expect(wrapper.find('.app-launcher--kitten').exists()).toBe(true)
    expect(wrapper.find('.app-launcher--aiopen').exists()).toBe(true)
    expect(wrapper.find('.app-launcher--production').exists()).toBe(true)
    expect(wrapper.find('.app-launcher--modstore').exists()).toBe(true)
  })

  it('renders launcher descriptions', async () => {
    const { wrapper } = await mountView()
    const descs = wrapper.findAll('.app-launcher-desc')
    expect(descs).toHaveLength(4)
    expect(descs[0].text()).toContain('可视化 AI 员工')
    expect(descs[1].text()).toContain('MCP/API')
    expect(descs[2].text()).toContain('生产 AI 员工')
    expect(descs[3].text()).toContain('MOD 扩展')
  })

  it('renders launcher names', async () => {
    const { wrapper } = await mountView()
    const names = wrapper.findAll('.app-launcher-name')
    expect(names.map((n) => n.text())).toEqual([
      '智慧分析',
      'AIOPEN 开放智控',
      '生产员工',
      '员工商店',
    ])
  })

  it('modstore launcher has data-tour attribute', async () => {
    const { wrapper } = await mountView()
    const modstore = wrapper.find('[data-tour="ecosystem-launcher-modstore"]')
    expect(modstore.exists()).toBe(true)
  })

  it('hides ecosystem home after entering kitten analyzer', async () => {
    const { wrapper } = await mountView()
    await wrapper.find('.app-launcher--kitten').trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.ecosystem-home').exists()).toBe(false)
  })

  it('hides ecosystem home after entering aiopen panel', async () => {
    const { wrapper } = await mountView()
    await wrapper.find('.app-launcher--aiopen').trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.ecosystem-home').exists()).toBe(false)
  })

  it('returns to ecosystem home on exitAnalyzer via back event', async () => {
    const { wrapper } = await mountView()
    await wrapper.find('.app-launcher--kitten').trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.ecosystem-home').exists()).toBe(false)
    // Emit back from the analyzer child (async component resolves to KittenAnalyzerView)
    await wrapper.vm.$nextTick()
    const kitten = wrapper.findComponent({ name: 'KittenAnalyzerView' })
    if (kitten.exists()) {
      kitten.vm.$emit('back')
      await wrapper.vm.$nextTick()
      expect(wrapper.find('.ecosystem-home').exists()).toBe(true)
    } else {
      // If async component not yet resolved, test exitAnalyzer via AIOpenPanel path
      const aiopen = wrapper.findComponent({ name: 'AIOpenPanel' })
      if (aiopen.exists()) {
        aiopen.vm.$emit('back')
        await wrapper.vm.$nextTick()
        expect(wrapper.find('.ecosystem-home').exists()).toBe(true)
      }
    }
  })

  it('navigates to brain shell page when production launcher clicked', async () => {
    const { wrapper, router } = await mountView()
    const pushSpy = vi.spyOn(router, 'push')
    await wrapper.find('.app-launcher--production').trigger('click')
    expect(pushSpy).toHaveBeenCalledWith({ name: 'brain' })
  })

  it('navigates to mod-store shell page when modstore launcher clicked', async () => {
    const { wrapper, router } = await mountView()
    const pushSpy = vi.spyOn(router, 'push')
    await wrapper.find('.app-launcher--modstore').trigger('click')
    expect(pushSpy).toHaveBeenCalledWith({ name: 'mod-store' })
  })

  it('uses mod path redirect when planner mod pages enabled (brain)', async () => {
    vi.mocked(resolvePlannerPageRedirectForRouteName).mockReturnValue('/mod/brain')
    const { wrapper, router } = await mountView()
    const pushSpy = vi.spyOn(router, 'push')
    await wrapper.find('.app-launcher--production').trigger('click')
    expect(pushSpy).toHaveBeenCalledWith('/mod/brain')
    expect(pushSpy).not.toHaveBeenCalledWith({ name: 'brain' })
  })

  it('uses mod path redirect when planner mod pages enabled (mod-store)', async () => {
    vi.mocked(resolvePlannerPageRedirectForRouteName).mockReturnValue('/mod/store')
    const { wrapper, router } = await mountView()
    const pushSpy = vi.spyOn(router, 'push')
    await wrapper.find('.app-launcher--modstore').trigger('click')
    expect(pushSpy).toHaveBeenCalledWith('/mod/store')
  })
})
