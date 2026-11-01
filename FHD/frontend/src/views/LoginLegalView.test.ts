import { mount, flushPromises } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CORE_ROUTES } from '@/router/routes/core'
import { resolveInitialRoutes } from '@/router/initialRouteSelection'
import { LEGAL_DOCUMENTS } from '@/constants/legalDocuments'

const mode = vi.hoisted(() => ({ shell: false }))
vi.mock('@/utils/adminConsoleUrl', () => ({ isAdminConsoleSpa: () => false }))
vi.mock('@/constants/platformShellMode', async importOriginal => ({
  ...await importOriginal<typeof import('@/constants/platformShellMode')>(),
  isPlatformShellModeEnabled: () => mode.shell,
}))
afterEach(() => { mode.shell = false; window.history.replaceState({}, '', '/'); document.title = '' })

describe('login legal documents', () => {
  it.each(['normal', 'shell', 'sandbox'])('can read both local documents before login in %s mode and return without losing the destination', async variant => {
    mode.shell = variant === 'shell'
    window.history.replaceState({}, '', variant === 'sandbox' ? '/?sandbox' : '/')
    const router = createRouter({ history: createMemoryHistory(), routes: resolveInitialRoutes(CORE_ROUTES) })
    const wrapper = mount({ template: '<RouterView />' }, { global: { plugins: [router] } })
    try {
      for (const kind of ['service-agreement', 'privacy-policy'] as const) {
        await router.push({ name: 'login-legal', params: { document: kind }, query: { redirect: '/business-docking' } })
        await flushPromises()
        expect(router.currentRoute.value.meta).toMatchObject({ publicAccess: true, hideChrome: true })
        expect(wrapper.get('h1').text()).toBe(LEGAL_DOCUMENTS[kind].title)
        expect(wrapper.text()).toContain('审阅草案，尚未作为生效条款发布')
        expect(wrapper.text()).toContain('版本 【发布前待确认】')
        expect(wrapper.text()).toContain('生效日期 【发布前待确认】')
        expect(wrapper.findAll('section')).toHaveLength(7)
        for (const unverified of ['2026-11-01', 'support@xiu-ci.com', '成都修茈科技有限公司', '所有数据均存储于企业自有服务器']) {
          expect(wrapper.text()).not.toContain(unverified)
        }
        expect(wrapper.text()).toContain('【发布前待确认：')
        expect(wrapper.get('a').attributes('href')).toBe('/login?redirect=/business-docking')
        expect(document.title).toContain(LEGAL_DOCUMENTS[kind].title)
        expect(wrapper.find('[role=dialog]').exists()).toBe(false)
        expect(wrapper.find('input[type=checkbox]').exists()).toBe(false)
      }
    } finally { wrapper.unmount() }
  })
})
