import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, onMounted } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { assembleMpModelPayment } from '../../../mods/xcagi-model-payment-bridge/frontend/views/model-payment/assemble'
import { useSettingsAccount } from '@/composables/settings/useSettingsAccount'
import { appAlert } from '@/utils/appDialog'

const gate = vi.hoisted(() => ({
  handoff: vi.fn(),
  overview: vi.fn(),
  catalog: vi.fn(),
}))
const api = vi.hoisted(() => ({
  getCurrentUser: vi.fn(),
  validateSession: vi.fn(),
  updateProfile: vi.fn(),
  logout: vi.fn(),
}))
const profile = vi.hoisted(() => ({
  applyFromMeData: vi.fn(),
  clear: vi.fn(),
  companyBrand: '',
  displayBrand: '',
  accountKind: 'personal',
  isAdminAccount: false,
}))

vi.mock('@/api/marketAccount', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/marketAccount')>()
  return {
    ...actual,
    fetchSessionMarketHandoff: gate.handoff,
    fetchMarketAccountOverview: gate.overview,
    fetchMarketLlmCatalog: gate.catalog,
    persistMarketTokensFromHandoff: vi.fn(() => true),
  }
})
vi.mock('@/api/auth', () => ({ authApi: api }))
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('vue-router', () => ({ useRoute: () => ({ fullPath: '/settings' }), useRouter: () => ({ replace: vi.fn() }) }))
vi.mock('@/api/core', () => ({ buildFullApiUrl: (path: string) => path }))
vi.mock('@/api/adminAudit', () => ({ default: {} }))
vi.mock('@/stores/accountProfile', () => ({ useAccountProfileStore: () => profile }))
vi.mock('@/utils/appDialog', () => ({ appAlert: vi.fn(), appConfirm: vi.fn() }))

const user = {
  id: 1,
  username: 'wuxinghua1',
  display_name: 'wuxinghua1',
  email: 'a@example.com',
  role: 'user',
  is_active: true,
}
const Page = defineComponent({
  setup() {
    const mp = assembleMpModelPayment()
    const account = useSettingsAccount()
    onMounted(() => { void account.loadLocalUser() })
    return () => h('div', { id: 'view-settings' }, [
      h('h1', '系统设置'),
      h('input', {
        value: account.profileDisplayNameDraft.value,
        onInput: (event: Event) => {
          account.profileDisplayNameDraft.value = (event.target as HTMLInputElement).value
        },
      }),
      h('button', {
        type: 'button',
        class: 'settings-profile-form__submit',
        disabled: !account.profileFormDirty.value || account.profileSaving.value,
        onClick: () => { void account.saveProfile() },
      }, '保存资料'),
      h('p', { 'data-testid': 'balance-hint' }, mp.marketBalanceHint.value),
    ])
  },
})

function pending() {
  let reject!: (reason: unknown) => void
  const promise = new Promise((_resolve, fail) => { reject = fail })
  return { promise, reject }
}

let invalid = vi.fn()
beforeEach(() => {
  vi.clearAllMocks()
  document.getElementById('stability-notice')?.remove()
  localStorage.clear()
  profile.applyFromMeData.mockResolvedValue(undefined)
  api.getCurrentUser.mockResolvedValue({ success: true, data: { user } })
  api.updateProfile.mockRejectedValue(new Error('保存失败'))
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) }))
  invalid = vi.fn()
  window.addEventListener('xcagi:enterprise-session-invalid', invalid)
})
afterEach(() => {
  window.removeEventListener('xcagi:enterprise-session-invalid', invalid)
  vi.unstubAllGlobals()
})

describe('settings page load', () => {
  it('paints the shell and keeps profile save while market handoff and wallet sync fail quietly', async () => {
    const handoff = pending()
    const overview = pending()
    gate.handoff.mockReturnValue(handoff.promise)
    gate.overview.mockReturnValue(overview.promise)
    gate.catalog.mockReturnValue(new Promise(() => {}))

    const wrapper = mount(Page)
    await flushPromises()

    expect(wrapper.get('h1').text()).toBe('系统设置')
    expect(wrapper.get('[data-testid="balance-hint"]').text()).toBe('正在同步账户信息…')
    expect(gate.overview).toHaveBeenCalled()
    expect(gate.handoff).toHaveBeenCalled()
    let handoffSettled = false
    void handoff.promise.then(() => { handoffSettled = true }, () => { handoffSettled = true })
    await flushPromises()
    expect(handoffSettled).toBe(false)
    expect(api.getCurrentUser).toHaveBeenCalledWith(expect.objectContaining({ quiet: true }))

    await wrapper.get('input').setValue('新展示名')
    expect(wrapper.get('button').attributes('disabled')).toBeUndefined()

    handoff.reject(Object.assign(new Error('请求超时（>8s）。该请求未成功。'), { status: 0 }))
    overview.reject(Object.assign(new Error('登录状态已失效，请重新登录。'), { status: 401 }))
    await flushPromises()

    expect(document.getElementById('stability-notice')).toBeNull()
    expect(invalid).not.toHaveBeenCalled()
    expect(wrapper.get('[data-testid="balance-hint"]').text()).toBe('暂时没有同步到')
    expect(wrapper.get('button').attributes('disabled')).toBeUndefined()

    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(api.updateProfile).toHaveBeenCalled()
    expect(appAlert).toHaveBeenCalled()
    wrapper.unmount()
  })
})
