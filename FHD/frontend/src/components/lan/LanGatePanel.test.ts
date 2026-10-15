import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

const container = vi.hoisted(() => ({ mocks: {} as Record<string, unknown> }))

vi.mock('@/composables/useLanGate', async () => {
  const { ref } = await import('vue')
  const statusRef = ref<{
    enabled: boolean
    in_whitelist: boolean
    in_dynamic_allowlist: boolean
    authorized: boolean
    is_admin_host: boolean
    ip: string
  } | null>(null)
  const refreshMock = vi.fn().mockResolvedValue(undefined)
  const dismissLanGateModalMock = vi.fn()
  container.mocks.statusRef = statusRef
  container.mocks.refreshMock = refreshMock
  container.mocks.dismissLanGateModalMock = dismissLanGateModalMock
  return {
    useLanGate: () => ({
      refresh: refreshMock,
      status: statusRef,
      dismissLanGateModal: dismissLanGateModalMock,
    }),
  }
})

vi.mock('@/api/lanGate', () => {
  const hostInfoMock = vi.fn()
  const myAccessRequestMock = vi.fn()
  const requestAccessMock = vi.fn()
  const activateMock = vi.fn()
  container.mocks.hostInfoMock = hostInfoMock
  container.mocks.myAccessRequestMock = myAccessRequestMock
  container.mocks.requestAccessMock = requestAccessMock
  container.mocks.activateMock = activateMock
  return {
    lanGateApi: {
      hostInfo: hostInfoMock,
      myAccessRequest: myAccessRequestMock,
      requestAccess: requestAccessMock,
      activate: activateMock,
    },
  }
})

vi.mock('@/stores/mods', () => {
  const initializeMock = vi.fn().mockResolvedValue(undefined)
  container.mocks.initializeMock = initializeMock
  return {
    useModsStore: () => ({
      initialize: initializeMock,
    }),
  }
})

vi.mock('@/utils/typeGuards', async () => {
  const actual = await vi.importActual<typeof import('@/utils/typeGuards')>('@/utils/typeGuards')
  return { ...actual }
})

vi.mock('@/api/core', async () => {
  const actual = await vi.importActual<typeof import('@/api/core')>('@/api/core')
  return { ...actual }
})

import LanGatePanel from './LanGatePanel.vue'

const statusRef = container.mocks.statusRef as ReturnType<(typeof import('vue'))['ref']>
const refreshMock = container.mocks.refreshMock as ReturnType<typeof vi.fn>
const dismissLanGateModalMock = container.mocks.dismissLanGateModalMock as ReturnType<typeof vi.fn>
const hostInfoMock = container.mocks.hostInfoMock as ReturnType<typeof vi.fn>
const myAccessRequestMock = container.mocks.myAccessRequestMock as ReturnType<typeof vi.fn>
const requestAccessMock = container.mocks.requestAccessMock as ReturnType<typeof vi.fn>
const activateMock = container.mocks.activateMock as ReturnType<typeof vi.fn>
const initializeMock = container.mocks.initializeMock as ReturnType<typeof vi.fn>

function setStatus(overrides = {}) {
  statusRef.value = { enabled: true, in_whitelist: true, in_dynamic_allowlist: false,
    authorized: false, is_admin_host: false, ip: '1.1.1.1', ...overrides }
}

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/qsm-pro', component: { template: '<div />' } },
    ],
  })
}

function mountPanel(props: Record<string, unknown> = {}) {
  const router = makeRouter()
  return router.push('/').then(() =>
    router.isReady().then(() =>
      mount(LanGatePanel, {
        props: { variant: 'page', redirectPath: '/', ...props },
        global: { plugins: [router] },
      }),
    ),
  )
}

describe('LanGatePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    statusRef.value = null
    refreshMock.mockResolvedValue(undefined)
    hostInfoMock.mockResolvedValue({ bootstrap_available: false, token_ttl_seconds: 28800 })
    myAccessRequestMock.mockResolvedValue({ request: null })
    requestAccessMock.mockResolvedValue({ request: null })
    activateMock.mockResolvedValue({ success: true, is_admin: false })
    initializeMock.mockResolvedValue(undefined)
  })

  it('renders the panel container', async () => {
    setStatus({ enabled: false, in_whitelist: false })
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.lan-gate-panel').exists()).toBe(true)
  })

  it('renders page brand with FHD title when variant is page', async () => {
    setStatus({ enabled: false, in_whitelist: false })
    const wrapper = await mountPanel({ variant: 'page' })
    await flushPromises()
    expect(wrapper.find('.brand h1').text()).toContain('FHD')
  })

  it('renders compact brand when variant is modal', async () => {
    setStatus({ enabled: false, in_whitelist: false })
    const wrapper = await mountPanel({ variant: 'modal' })
    await flushPromises()
    expect(wrapper.find('.brand-compact').exists()).toBe(true)
    expect(wrapper.find('.brand-compact h1').text()).toBe('局域网授权')
  })

  it('renders modal bar with dismiss button when variant is modal', async () => {
    setStatus({ enabled: false, in_whitelist: false })
    const wrapper = await mountPanel({ variant: 'modal' })
    await flushPromises()
    expect(wrapper.find('.lan-gate-modal-bar').exists()).toBe(true)
    expect(wrapper.find('.lan-gate-modal-title').text()).toBe('局域网授权')
  })

  it('shows "未启用" banner when enabled is false', async () => {
    setStatus({ enabled: false, in_whitelist: false })
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.state-banner.ok').exists()).toBe(true)
    expect(wrapper.text()).toContain('未启用局域网模式')
  })

  it('renders "进入系统" button when not enabled', async () => {
    setStatus({ enabled: false, in_whitelist: false })
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.state-banner.ok .btn.primary').text()).toBe('进入系统')
  })

  it('shows gate wait section when enabled but not in whitelist and no clearance', async () => {
    setStatus({ in_whitelist: false })
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.gate-wait').exists()).toBe(true)
  })

  it('shows "非授权网络" message when not in whitelist', async () => {
    setStatus({ in_whitelist: false })
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.state-banner.danger').exists()).toBe(true)
    expect(wrapper.text()).toContain('非授权网络')
  })

  it('shows IP in danger banner', async () => {
    setStatus({ in_whitelist: false, ip: '192.168.1.1' })
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.text()).toContain('192.168.1.1')
  })

  it('shows "未知" when IP is empty', async () => {
    setStatus({ in_whitelist: false, ip: '' })
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.text()).toContain('未知')
  })

  it('shows "普通密钥须先经审批" message when in whitelist but no clearance', async () => {
    setStatus()
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.state-banner.warn').exists()).toBe(true)
    expect(wrapper.text()).toContain('普通密钥须先经审批')
  })

  it('renders access request form in gate wait', async () => {
    setStatus({ in_whitelist: false })
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.request-form').exists()).toBe(true)
    expect(wrapper.find('input[placeholder*="财务室"]').exists()).toBe(true)
  })

  it('renders admin key entry button in gate wait', async () => {
    setStatus({ in_whitelist: false })
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.admin-key-entry').exists()).toBe(true)
    expect(wrapper.find('.admin-key-entry .btn.ghost').text()).toContain('管理员密钥')
  })

  it('shows key form when admin key button is clicked', async () => {
    setStatus({ in_whitelist: false })
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('input[type="password"]').exists()).toBe(false)
    await wrapper.find('.admin-key-entry .btn.ghost').trigger('click')
    expect(wrapper.find('input[type="password"]').exists()).toBe(true)
  })

  it('shows key form directly when userKeyClearance is true', async () => {
    setStatus({ in_dynamic_allowlist: true })
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('input[type="password"]').exists()).toBe(true)
  })

  it('shows key form directly when bootstrap is available', async () => {
    setStatus()
    hostInfoMock.mockResolvedValue({ bootstrap_available: true, token_ttl_seconds: 28800 })
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('input[type="password"]').exists()).toBe(true)
    expect(wrapper.find('.hint-box').exists()).toBe(true)
  })

  it('renders submit button with "激活本机" text', async () => {
    setStatus({ in_dynamic_allowlist: true })
    const wrapper = await mountPanel()
    await flushPromises()
    const btn = wrapper.find('.btn.primary.big')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toContain('激活本机')
  })

  it('disables submit button when keyInput is empty', async () => {
    setStatus({ in_dynamic_allowlist: true })
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.btn.primary.big').attributes('disabled')).toBeDefined()
  })

  it('enables submit button when key is entered', async () => {
    setStatus({ in_dynamic_allowlist: true })
    const wrapper = await mountPanel()
    await flushPromises()
    await wrapper.find('input[type="password"]').setValue('my-key')
    expect(wrapper.find('.btn.primary.big').attributes('disabled')).toBeUndefined()
  })

  it('calls activate API when form is submitted', async () => {
    setStatus({ in_dynamic_allowlist: true })
    activateMock.mockResolvedValue({ success: true, is_admin: false })
    const wrapper = await mountPanel()
    await flushPromises()
    await wrapper.find('input[type="password"]').setValue('my-key')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(activateMock).toHaveBeenCalledWith('my-key', undefined)
  })

  it('shows error when activate returns success=false', async () => {
    setStatus({ in_dynamic_allowlist: true })
    activateMock.mockResolvedValue({ success: false, is_admin: false })
    const wrapper = await mountPanel()
    await flushPromises()
    await wrapper.find('input[type="password"]').setValue('bad-key')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(wrapper.find('.error').text()).toContain('激活失败')
  })

  it('shows mapped error for bad_key', async () => {
    setStatus({ in_dynamic_allowlist: true })
    const { ApiError } = await import('@/api/core')
    activateMock.mockRejectedValue(new ApiError('bad', 400, { detail: 'bad_key' }))
    const wrapper = await mountPanel()
    await flushPromises()
    await wrapper.find('input[type="password"]').setValue('bad-key')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(wrapper.find('.error').text()).toContain('密钥错误')
  })

  it('shows mapped error for key_revoked', async () => {
    setStatus({ in_dynamic_allowlist: true })
    const { ApiError } = await import('@/api/core')
    activateMock.mockRejectedValue(new ApiError('revoked', 400, { detail: 'key_revoked' }))
    const wrapper = await mountPanel()
    await flushPromises()
    await wrapper.find('input[type="password"]').setValue('bad-key')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(wrapper.find('.error').text()).toContain('已被吊销')
  })

  it('shows mapped error for key_expired', async () => {
    setStatus({ in_dynamic_allowlist: true })
    const { ApiError } = await import('@/api/core')
    activateMock.mockRejectedValue(new ApiError('expired', 400, { detail: 'key_expired' }))
    const wrapper = await mountPanel()
    await flushPromises()
    await wrapper.find('input[type="password"]').setValue('bad-key')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(wrapper.find('.error').text()).toContain('已过期')
  })

  it('shows mapped error for lan_blocked', async () => {
    setStatus({ in_dynamic_allowlist: true })
    const { ApiError } = await import('@/api/core')
    activateMock.mockRejectedValue(new ApiError('blocked', 400, { detail: 'lan_blocked' }))
    const wrapper = await mountPanel()
    await flushPromises()
    await wrapper.find('input[type="password"]').setValue('bad-key')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(wrapper.find('.error').text()).toContain('不在白名单')
  })

  it('shows mapped error for activation_requires_approval', async () => {
    setStatus({ in_dynamic_allowlist: true })
    const { ApiError } = await import('@/api/core')
    activateMock.mockRejectedValue(new ApiError('approval', 400, { detail: 'activation_requires_approval' }))
    const wrapper = await mountPanel()
    await flushPromises()
    await wrapper.find('input[type="password"]').setValue('key')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(wrapper.find('.error').text()).toContain('须管理员批准')
  })

  it('shows mapped error for empty_key', async () => {
    setStatus({ in_dynamic_allowlist: true })
    const { ApiError } = await import('@/api/core')
    activateMock.mockRejectedValue(new ApiError('empty', 400, { detail: 'empty_key' }))
    const wrapper = await mountPanel()
    await flushPromises()
    await wrapper.find('input[type="password"]').setValue('key')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(wrapper.find('.error').text()).toContain('请输入密钥')
  })

  it('renders footer meta with status text', async () => {
    setStatus({ in_dynamic_allowlist: true })
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.meta').exists()).toBe(true)
    expect(wrapper.find('.meta').text()).toContain('局域网授权已启用')
  })

  it('shows IP in footer when present', async () => {
    setStatus({ in_dynamic_allowlist: true, ip: '10.0.0.1' })
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.meta').text()).toContain('10.0.0.1')
  })

  it('shows "主机管理员位" when is_admin_host is true', async () => {
    setStatus({ in_dynamic_allowlist: true, is_admin_host: true })
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.meta').text()).toContain('主机管理员位')
  })

  it('renders ttl hours in lead text', async () => {
    setStatus({ in_dynamic_allowlist: true })
    hostInfoMock.mockResolvedValue({ bootstrap_available: false, token_ttl_seconds: 36000 })
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.lead').text()).toContain('10 小时')
  })

  it('renders access request state when present', async () => {
    setStatus({ in_whitelist: false })
    myAccessRequestMock.mockResolvedValue({
      request: {
        status: 'pending',
        device_label: '我的设备',
        review_note: '审核中',
      },
    })
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.request-state').exists()).toBe(true)
    expect(wrapper.text()).toContain('待管理员审核')
    expect(wrapper.text()).toContain('我的设备')
    expect(wrapper.text()).toContain('审核中')
  })

  it('shows "已批准" status text for approved request', async () => {
    setStatus({ in_whitelist: false })
    myAccessRequestMock.mockResolvedValue({
      request: { status: 'approved', device_label: '', review_note: '' },
    })
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.text()).toContain('已批准')
  })

  it('shows "已拒绝" status text for rejected request', async () => {
    setStatus({ in_whitelist: false })
    myAccessRequestMock.mockResolvedValue({
      request: { status: 'rejected', device_label: '', review_note: '' },
    })
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.text()).toContain('已拒绝')
  })

  it('submits access request when form is submitted', async () => {
    setStatus({ in_whitelist: false })
    requestAccessMock.mockResolvedValue({
      request: { status: 'pending', device_label: 'PC1', review_note: '' },
    })
    const wrapper = await mountPanel()
    await flushPromises()
    const inputs = wrapper.findAll('.request-form input')
    await inputs[0].setValue('PC1')
    await inputs[1].setValue('测试用途')
    await wrapper.find('.request-form').trigger('submit.prevent')
    await flushPromises()
    expect(requestAccessMock).toHaveBeenCalledWith({ device_label: 'PC1', note: '测试用途' })
  })

  it('shows "更新申请" button text when request is pending', async () => {
    setStatus({ in_whitelist: false })
    myAccessRequestMock.mockResolvedValue({
      request: { status: 'pending', device_label: '', review_note: '' },
    })
    const wrapper = await mountPanel()
    await flushPromises()
    const submitBtn = wrapper.find('.request-form .btn.primary')
    expect(submitBtn.text()).toContain('更新申请')
  })

  it('shows "提交访问申请" button text when no request', async () => {
    setStatus({ in_whitelist: false })
    myAccessRequestMock.mockResolvedValue({ request: null })
    const wrapper = await mountPanel()
    await flushPromises()
    const submitBtn = wrapper.find('.request-form .btn.primary')
    expect(submitBtn.text()).toContain('提交访问申请')
  })

  it('calls dismissLanGateModal when dismiss button is clicked in modal variant', async () => {
    setStatus({ enabled: false, in_whitelist: false })
    const wrapper = await mountPanel({ variant: 'modal' })
    await flushPromises()
    await wrapper.find('.btn-text').trigger('click')
    expect(dismissLanGateModalMock).toHaveBeenCalled()
  })

  it('shows initialization error when load fails', async () => {
    setStatus({ in_dynamic_allowlist: true })
    refreshMock.mockRejectedValue(new Error('refresh failed'))
    hostInfoMock.mockRejectedValue(new Error('hostInfo failed'))
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.error').text()).toContain('初始化失败')
  })

  it('renders bootstrap hint box when bootstrap is available', async () => {
    setStatus()
    hostInfoMock.mockResolvedValue({ bootstrap_available: true, token_ttl_seconds: 28800 })
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.hint-box').exists()).toBe(true)
    expect(wrapper.find('.hint-box').text()).toContain('LAN_ADMIN_BOOTSTRAP_KEY')
  })

  it('renders label input when bootstrap is available', async () => {
    setStatus()
    hostInfoMock.mockResolvedValue({ bootstrap_available: true, token_ttl_seconds: 28800 })
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('input[placeholder*="财务老李"]').exists()).toBe(true)
  })

  it('shows warn-lead when admin key unlocked but no clearance and no bootstrap', async () => {
    setStatus()
    hostInfoMock.mockResolvedValue({ bootstrap_available: false, token_ttl_seconds: 28800 })
    const wrapper = await mountPanel()
    await flushPromises()
    await wrapper.find('.admin-key-entry .btn.ghost').trigger('click')
    expect(wrapper.find('.warn-lead').exists()).toBe(true)
    expect(wrapper.find('.warn-lead').text()).toContain('管理员密钥')
  })

  it('shows different lead text when userKeyClearance is true', async () => {
    setStatus({ in_dynamic_allowlist: true })
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.lead').text()).toContain('一级密钥')
  })

  it('redirects to home when authorized on load', async () => {
    setStatus({ in_dynamic_allowlist: true, authorized: true })
    const router = makeRouter()
    await router.push('/')
    await router.isReady()
    const pushSpy = vi.spyOn(router, 'replace')
    mount(LanGatePanel, {
      props: { variant: 'page', redirectPath: '/dashboard' },
      global: { plugins: [router] },
    })
    await flushPromises()
    expect(pushSpy).toHaveBeenCalledWith('/dashboard')
  })

  it('uses custom redirectPath when provided', async () => {
    setStatus({ enabled: false, in_whitelist: false })
    const wrapper = await mountPanel({ redirectPath: '/custom' })
    await flushPromises()
    expect(wrapper.find('.lan-gate-panel').exists()).toBe(true)
  })

  it('uses "/" when redirectPath is empty', async () => {
    setStatus({ enabled: false, in_whitelist: false })
    const wrapper = await mountPanel({ redirectPath: '   ' })
    await flushPromises()
    expect(wrapper.find('.lan-gate-panel').exists()).toBe(true)
  })

  it('shows "正在校验…" text when submitting', async () => {
    setStatus({ in_dynamic_allowlist: true })
    let resolveActivate: (v: unknown) => void
    activateMock.mockReturnValue(
      new Promise((resolve) => {
        resolveActivate = resolve
      }),
    )
    const wrapper = await mountPanel()
    await flushPromises()
    await wrapper.find('input[type="password"]').setValue('my-key')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(wrapper.find('.btn.primary.big').text()).toContain('正在校验')
    resolveActivate!({ success: true, is_admin: false })
    await flushPromises()
  })

  it('shows "正在提交…" text when submitting access request', async () => {
    setStatus({ in_whitelist: false })
    let resolveRequest: (v: unknown) => void
    requestAccessMock.mockReturnValue(
      new Promise((resolve) => {
        resolveRequest = resolve
      }),
    )
    const wrapper = await mountPanel()
    await flushPromises()
    await wrapper.find('.request-form').trigger('submit.prevent')
    await flushPromises()
    expect(wrapper.find('.request-form .btn.primary').text()).toContain('正在提交')
    resolveRequest!({ request: null })
    await flushPromises()
  })
  it.each([
    ['license_misconfigured', 'LAN_LICENSE_SECRET'], ['lan_mode_disabled', '未启用局域网模式'],
    ['admin_host_required', '管理员主机'], ['unknown_failure', 'unknown_failure'],
  ])('reports %s during activation without losing the entered key', async (detail, expected) => {
    setStatus({ in_dynamic_allowlist: true })
    const { ApiError } = await import('@/api/core')
    activateMock.mockRejectedValue(new ApiError('failed', 400, { detail }))
    const wrapper = await mountPanel(); await flushPromises()
    await wrapper.get('input[type="password"]').setValue(' key ')
    await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(wrapper.get('.error').text()).toContain(expected)
    expect((wrapper.get('input[type="password"]').element as HTMLInputElement).value).toBe(' key ')
    wrapper.unmount()
  })

  it('restores saved request details, blocks duplicate submissions and recovers from denial', async () => {
    setStatus()
    myAccessRequestMock.mockResolvedValue({ request: { status: 'unknown', device_label: '已保存的电脑', note: '已保存的用途' } })
    const wrapper = await mountPanel(); await flushPromises()
    expect(wrapper.findAll('.request-form input').map(input => (input.element as HTMLInputElement).value)).toEqual(['已保存的电脑', '已保存的用途'])
    expect(wrapper.get('.request-state').text()).toContain('待管理员审核')
    let reject!: (reason: Error) => void
    requestAccessMock.mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail }))
    await wrapper.get('.request-form').trigger('submit'); await wrapper.get('.request-form').trigger('submit')
    expect(requestAccessMock).toHaveBeenCalledOnce()
    reject(new Error('申请暂不可用')); await flushPromises()
    expect(wrapper.get('.request-form button').attributes('disabled')).toBeUndefined()
    await wrapper.get('.admin-key-entry button').trigger('click')
    expect(wrapper.get('.error').text()).toContain('申请暂不可用')
    wrapper.unmount()
  })

  it('activates a labeled administrator host once, opens its console and dismisses the modal', async () => {
    setStatus(); hostInfoMock.mockResolvedValue({ bootstrap_available: true })
    let finish!: (result: unknown) => void
    activateMock.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = await mountPanel({ variant: 'modal' }); await flushPromises()
    await wrapper.get('input[type="password"]').setValue(' admin-key ')
    await wrapper.get('input[maxlength="100"]').setValue(' 财务主机 ')
    await wrapper.get('form').trigger('submit'); await wrapper.get('form').trigger('submit')
    expect(activateMock).toHaveBeenCalledExactlyOnceWith('admin-key', '财务主机')
    finish({ success: true, is_admin: true }); await flushPromises()
    expect(initializeMock).toHaveBeenCalledOnce()
    expect(wrapper.vm.$router.currentRoute.value.path).toBe('/qsm-pro')
    expect(dismissLanGateModalMock).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it.each(['page', 'modal'])('enters the requested destination from a disabled %s gate', async variant => {
    setStatus({ enabled: false })
    const wrapper = await mountPanel({ variant, redirectPath: '/qsm-pro' }); await flushPromises()
    await wrapper.get('.state-banner button').trigger('click'); await flushPromises()
    expect(wrapper.vm.$router.currentRoute.value.path).toBe('/qsm-pro')
    expect(dismissLanGateModalMock).toHaveBeenCalledTimes(variant === 'modal' ? 1 : 0)
    wrapper.unmount()
  })

})
