import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RegisterView from './RegisterView.vue'

const { isAdminConsoleSpa, isDesktopShell } = vi.hoisted(() => ({
  isAdminConsoleSpa: vi.fn(() => false),
  isDesktopShell: vi.fn(() => true),
}))
vi.mock('@/utils/adminConsoleUrl', () => ({ isAdminConsoleSpa }))
vi.mock('@/utils/desktopShell', () => ({ isDesktopShell }))

async function mountLegacyRegistration(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/login/register', name: 'login-register', component: RegisterView },
      { path: '/login', name: 'login', component: { template: '<main />' } },
    ],
  })
  await router.push(path)
  const wrapper = mount(RegisterView, { global: { plugins: [router] } })
  await flushPromises()
  return { router, wrapper }
}

describe('legacy registration route', () => {
  beforeEach(() => {
    isAdminConsoleSpa.mockReturnValue(false)
    isDesktopShell.mockReturnValue(true)
  })

  it('offers the shared registration link from the desktop without a local form', async () => {
    const { wrapper } = await mountLegacyRegistration('/login/register?redirect=https%3A%2F%2Fexample.org')
    expect(wrapper.find('form').exists()).toBe(false)
    expect(wrapper.get('a').attributes()).toMatchObject({
      href: 'https://xiu-ci.com/market/register?source=xcagi-desktop',
      target: '_blank',
    })
  })

  it('maps the former Flutter registration URL onto the mobile source', async () => {
    const { wrapper } = await mountLegacyRegistration('/login/register?redirect=%2Fapp%2Fmobile-register-complete')
    expect(wrapper.get('a').attributes('href')).toBe('https://xiu-ci.com/market/register?source=xcagi-mobile')
  })

  it('returns admin-console visitors to their login', async () => {
    isAdminConsoleSpa.mockReturnValue(true)
    const { wrapper, router } = await mountLegacyRegistration('/login/register?redirect=/settings')
    expect(wrapper.find('a').exists()).toBe(false)
    expect(router.currentRoute.value).toMatchObject({ name: 'login', query: { redirect: '/settings' } })
  })
})
