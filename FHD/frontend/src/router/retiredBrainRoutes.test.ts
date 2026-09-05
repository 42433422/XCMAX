import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { SHELL_ROUTES } from './routes/shell'
import { BUSINESS_ROUTES } from './routes/business'
import { modRoutes, modMenu } from '../../../mods/xcagi-planner-bridge/frontend/routes.js'
import manifest from '../../../mods/xcagi-planner-bridge/manifest.json'
import mirrorManifest from '../../../XCAGI/mods/xcagi-planner-bridge/manifest.json'
import { modPhysicalViewGlob } from '@/constants/modPhysicalViewGlob.full'
import { modPhysicalViewGlob as minimalViews } from '@/constants/modPhysicalViewGlob.minimal'
import { hostViewGlob } from '@/constants/hostViewGlob'
import { mergeSidebarMenuItems } from '@/utils/mergeSidebarMenuItems'

afterEach(() => {
  vi.unstubAllEnvs()
  localStorage.clear()
})

describe('retired brain developer page', () => {
  it.each([
    { path: '/brain', withMod: true },
    { path: '/mod/xcagi-planner-bridge/brain', withMod: true },
    { path: '/brain', withMod: false },
    { path: '/mod/xcagi-planner-bridge/brain', withMod: false },
  ])('returns $path to home with Mod registration $withMod', async ({ path, withMod }) => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'chat', component: { template: '<main>正常首页</main>' } },
        ...SHELL_ROUTES,
        ...(withMod ? [...BUSINESS_ROUTES, ...modRoutes] : []),
      ],
    })
    const legacy = router.resolve(path).matched.at(-1)
    expect(legacy?.redirect).toBeTruthy()
    expect(legacy?.components).toBeUndefined()
    await router.push(`${path}?path=private-file.py#editor`)
    await router.isReady()
    const wrapper = mount(RouterView, { global: { plugins: [router] } })
    expect(router.currentRoute.value.fullPath).toBe('/')
    expect(wrapper.text()).toBe('正常首页')
    expect(router.hasRoute('brain')).toBe(false)
    expect(router.hasRoute('mod-planner-brain')).toBe(false)
    wrapper.unmount()
  })

  it('keeps chat and ecosystem registration while removing the retired menu and physical bundle modules', () => {
    expect(modMenu.map((item) => item.id)).toEqual(['mod-planner-chat', 'mod-planner-ai-ecosystem'])
    expect(modRoutes.map((route) => route.name)).toContain('mod-planner-chat')
    expect(modRoutes.map((route) => route.name)).toContain('mod-planner-ai-ecosystem')
    for (const source of [manifest, mirrorManifest]) {
      expect(source.frontend.menu.map((item) => item.id)).toEqual(['mod-planner-chat', 'mod-planner-ai-ecosystem'])
      expect(source.config.physical_views).toContain('ChatView.vue')
      expect(source.config.physical_views).toContain('AIEcosystemView.vue')
      expect(source.config.physical_views).not.toContain('BrainView.vue')
      expect(source.config.legacy_host_page_paths).not.toContain('/brain')
    }
    for (const views of [modPhysicalViewGlob, minimalViews, hostViewGlob]) {
      expect(Object.keys(views).some((key) => /\/BrainView\.vue$|\/xcagi-planner-bridge\/frontend\/views\/brain\//.test(key))).toBe(false)
    }
  })

  it.each(['full', 'generic', 'minimal'])('filters stale host and Mod menu entries in the %s shell', (edition) => {
    vi.stubEnv('VITE_XCAGI_EDITION', edition)
    localStorage.setItem('xcagi_platform_shell_mode', '1')
    const base = { name: '旧智脑入口', iconClass: 'fa-brain' }
    const merged = mergeSidebarMenuItems(
      [
        { ...base, key: 'brain' },
        { key: 'chat', name: '智能对话', iconClass: 'fa-comments' },
      ],
      [
        { ...base, key: 'mod-mod-planner-brain', modId: 'xcagi-planner-bridge' },
        { ...base, key: 'legacy-custom-key', path: '/mod/xcagi-planner-bridge/brain/?old=1#editor' },
      ],
      [{ ...base, key: 'old-admin-link', path: '/brain' }],
      [{ key: 'ai-ecosystem', name: '智能生态', iconClass: 'fa-sitemap' }],
      ['xcagi-planner-bridge'],
    )
    expect(merged.map((item) => item.key)).toEqual(['chat', 'ai-ecosystem'])
  })

  it('removes a custom profile nested brain link while keeping its unrelated sibling', () => {
    const child = { key: 'settings', name: '设置', iconClass: 'fa-cog' }
    const merged = mergeSidebarMenuItems(
      [
        {
          key: 'custom-tools',
          name: '工作区',
          iconClass: 'fa-wrench',
          children: [{ key: 'custom-brain-title', name: '自定义开发页', iconClass: 'fa-brain', path: '/brain?legacy=1' }, child],
        },
      ],
      [],
      [],
      [],
      [],
    )
    expect(merged[0]?.children).toEqual([child])
    expect(merged[0]?.children?.[0]).toBe(child)
  })
})
