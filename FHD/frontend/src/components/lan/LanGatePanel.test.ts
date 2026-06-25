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

const statusRef = container.mocks.statusRef as ReturnType<typeof import('vue')['ref']>
const refreshMock = container.mocks.refreshMock as ReturnType<typeof vi.fn>
const dismissLanGateModalMock = container.mocks.dismissLanGateModalMock as ReturnType<typeof vi.fn>
const hostInfoMock = container.mocks.hostInfoMock as ReturnType<typeof vi.fn>
const myAccessRequestMock = container.mocks.myAccessRequestMock as ReturnType<typeof vi.fn>
const requestAccessMock = container.mocks.requestAccessMock as ReturnType<typeof vi.fn>
const activateMock = container.mocks.activateMock as ReturnType<typeof vi.fn>
const initializeMock = container.mocks.initializeMock as ReturnType<typeof vi.fn>

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
    statusRef.value = { enabled: false, in_whitelist: false, in_dynamic_allowlist: false, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.lan-gate-panel').exists()).toBe(true)
  })

  it('renders page brand with FHD title when variant is page', async () => {
    statusRef.value = { enabled: false, in_whitelist: false, in_dynamic_allowlist: false, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    const wrapper = await mountPanel({ variant: 'page' })
    await flushPromises()
    expect(wrapper.find('.brand h1').text()).toContain('FHD')
  })

  it('renders compact brand when variant is modal', async () => {
    statusRef.value = { enabled: false, in_whitelist: false, in_dynamic_allowlist: false, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    const wrapper = await mountPanel({ variant: 'modal' })
    await flushPromises()
    expect(wrapper.find('.brand-compact').exists()).toBe(true)
    expect(wrapper.find('.brand-compact h1').text()).toBe('局域网授权')
  })

  it('renders modal bar with dismiss button when variant is modal', async () => {
    statusRef.value = { enabled: false, in_whitelist: false, in_dynamic_allowlist: false, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    const wrapper = await mountPanel({ variant: 'modal' })
    await flushPromises()
    expect(wrapper.find('.lan-gate-modal-bar').exists()).toBe(true)
    expect(wrapper.find('.lan-gate-modal-title').text()).toBe('局域网授权')
  })

  it('shows "未启用" banner when enabled is false', async () => {
    statusRef.value = { enabled: false, in_whitelist: false, in_dynamic_allowlist: false, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.state-banner.ok').exists()).toBe(true)
    expect(wrapper.text()).toContain('未启用局域网模式')
  })

  it('renders "进入系统" button when not enabled', async () => {
    statusRef.value = { enabled: false, in_whitelist: false, in_dynamic_allowlist: false, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.state-banner.ok .btn.primary').text()).toBe('进入系统')
  })

  it('shows gate wait section when enabled but not in whitelist and no clearance', async () => {
    statusRef.value = { enabled: true, in_whitelist: false, in_dynamic_allowlist: false, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.gate-wait').exists()).toBe(true)
  })

  it('shows "非授权网络" message when not in whitelist', async () => {
    statusRef.value = { enabled: true, in_whitelist: false, in_dynamic_allowlist: false, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.state-banner.danger').exists()).toBe(true)
    expect(wrapper.text()).toContain('非授权网络')
  })

  it('shows IP in danger banner', async () => {
    statusRef.value = { enabled: true, in_whitelist: false, in_dynamic_allowlist: false, authorized: false, is_admin_host: false, ip: '192.168.1.1' }
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.text()).toContain('192.168.1.1')
  })

  it('shows "未知" when IP is empty', async () => {
    statusRef.value = { enabled: true, in_whitelist: false, in_dynamic_allowlist: false, authorized: false, is_admin_host: false, ip: '' }
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.text()).toContain('未知')
  })

  it('shows "普通密钥须先经审批" message when in whitelist but no clearance', async () => {
    statusRef.value = { enabled: true, in_whitelist: true, in_dynamic_allowlist: false, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.state-banner.warn').exists()).toBe(true)
    expect(wrapper.text()).toContain('普通密钥须先经审批')
  })

  it('renders access request form in gate wait', async () => {
    statusRef.value = { enabled: true, in_whitelist: false, in_dynamic_allowlist: false, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.request-form').exists()).toBe(true)
    expect(wrapper.find('input[placeholder*="财务室"]').exists()).toBe(true)
  })

  it('renders admin key entry button in gate wait', async () => {
    statusRef.value = { enabled: true, in_whitelist: false, in_dynamic_allowlist: false, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.admin-key-entry').exists()).toBe(true)
    expect(wrapper.find('.admin-key-entry .btn.ghost').text()).toContain('管理员密钥')
  })

  it('shows key form when admin key button is clicked', async () => {
    statusRef.value = { enabled: true, in_whitelist: false, in_dynamic_allowlist: false, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('input[type="password"]').exists()).toBe(false)
    await wrapper.find('.admin-key-entry .btn.ghost').trigger('click')
    expect(wrapper.find('input[type="password"]').exists()).toBe(true)
  })

  it('shows key form directly when userKeyClearance is true', async () => {
    statusRef.value = { enabled: true, in_whitelist: true, in_dynamic_allowlist: true, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('input[type="password"]').exists()).toBe(true)
  })

  it('shows key form directly when bootstrap is available', async () => {
    statusRef.value = { enabled: true, in_whitelist: true, in_dynamic_allowlist: false, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    hostInfoMock.mockResolvedValue({ bootstrap_available: true, token_ttl_seconds: 28800 })
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('input[type="password"]').exists()).toBe(true)
    expect(wrapper.find('.hint-box').exists()).toBe(true)
  })

  it('renders submit button with "激活本机" text', async () => {
    statusRef.value = { enabled: true, in_whitelist: true, in_dynamic_allowlist: true, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    const wrapper = await mountPanel()
    await flushPromises()
    const btn = wrapper.find('.btn.primary.big')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toContain('激活本机')
  })

  it('disables submit button when keyInput is empty', async () => {
    statusRef.value = { enabled: true, in_whitelist: true, in_dynamic_allowlist: true, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.btn.primary.big').attributes('disabled')).toBeDefined()
  })

  it('enables submit button when key is entered', async () => {
    statusRef.value = { enabled: true, in_whitelist: true, in_dynamic_allowlist: true, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    const wrapper = await mountPanel()
    await flushPromises()
    await wrapper.find('input[type="password"]').setValue('my-key')
    expect(wrapper.find('.btn.primary.big').attributes('disabled')).toBeUndefined()
  })

  it('calls activate API when form is submitted', async () => {
    statusRef.value = { enabled: true, in_whitelist: true, in_dynamic_allowlist: true, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    activateMock.mockResolvedValue({ success: true, is_admin: false })
    const wrapper = await mountPanel()
    await flushPromises()
    await wrapper.find('input[type="password"]').setValue('my-key')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(activateMock).toHaveBeenCalledWith('my-key', undefined)
  })

  it('shows error when activate returns success=false', async () => {
    statusRef.value = { enabled: true, in_whitelist: true, in_dynamic_allowlist: true, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    activateMock.mockResolvedValue({ success: false, is_admin: false })
    const wrapper = await mountPanel()
    await flushPromises()
    await wrapper.find('input[type="password"]').setValue('bad-key')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(wrapper.find('.error').text()).toContain('激活失败')
  })

  it('shows mapped error for bad_key', async () => {
    statusRef.value = { enabled: true, in_whitelist: true, in_dynamic_allowlist: true, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
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
    statusRef.value = { enabled: true, in_whitelist: true, in_dynamic_allowlist: true, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
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
    statusRef.value = { enabled: true, in_whitelist: true, in_dynamic_allowlist: true, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
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
    statusRef.value = { enabled: true, in_whitelist: true, in_dynamic_allowlist: true, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
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
    statusRef.value = { enabled: true, in_whitelist: true, in_dynamic_allowlist: true, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
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
    statusRef.value = { enabled: true, in_whitelist: true, in_dynamic_allowlist: true, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
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
    statusRef.value = { enabled: true, in_whitelist: true, in_dynamic_allowlist: true, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.meta').exists()).toBe(true)
    expect(wrapper.find('.meta').text()).toContain('局域网授权已启用')
  })

  it('shows IP in footer when present', async () => {
    statusRef.value = { enabled: true, in_whitelist: true, in_dynamic_allowlist: true, authorized: false, is_admin_host: false, ip: '10.0.0.1' }
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.meta').text()).toContain('10.0.0.1')
  })

  it('shows "主机管理员位" when is_admin_host is true', async () => {
    statusRef.value = { enabled: true, in_whitelist: true, in_dynamic_allowlist: true, authorized: false, is_admin_host: true, ip: '1.1.1.1' }
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.meta').text()).toContain('主机管理员位')
  })

  it('renders ttl hours in lead text', async () => {
    statusRef.value = { enabled: true, in_whitelist: true, in_dynamic_allowlist: true, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    hostInfoMock.mockResolvedValue({ bootstrap_available: false, token_ttl_seconds: 36000 })
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.lead').text()).toContain('10 小时')
  })

  it('renders access request state when present', async () => {
    statusRef.value = { enabled: true, in_whitelist: false, in_dynamic_allowlist: false, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
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
    statusRef.value = { enabled: true, in_whitelist: false, in_dynamic_allowlist: false, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    myAccessRequestMock.mockResolvedValue({
      request: { status: 'approved', device_label: '', review_note: '' },
    })
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.text()).toContain('已批准')
  })

  it('shows "已拒绝" status text for rejected request', async () => {
    statusRef.value = { enabled: true, in_whitelist: false, in_dynamic_allowlist: false, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    myAccessRequestMock.mockResolvedValue({
      request: { status: 'rejected', device_label: '', review_note: '' },
    })
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.text()).toContain('已拒绝')
  })

  it('submits access request when form is submitted', async () => {
    statusRef.value = { enabled: true, in_whitelist: false, in_dynamic_allowlist: false, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    requestAccessMock.mockResolvedValue({ request: { status: 'pending', device_label: 'PC1', review_note: '' } })
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
    statusRef.value = { enabled: true, in_whitelist: false, in_dynamic_allowlist: false, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    myAccessRequestMock.mockResolvedValue({
      request: { status: 'pending', device_label: '', review_note: '' },
    })
    const wrapper = await mountPanel()
    await flushPromises()
    const submitBtn = wrapper.find('.request-form .btn.primary')
    expect(submitBtn.text()).toContain('更新申请')
  })

  it('shows "提交访问申请" button text when no request', async () => {
    statusRef.value = { enabled: true, in_whitelist: false, in_dynamic_allowlist: false, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    myAccessRequestMock.mockResolvedValue({ request: null })
    const wrapper = await mountPanel()
    await flushPromises()
    const submitBtn = wrapper.find('.request-form .btn.primary')
    expect(submitBtn.text()).toContain('提交访问申请')
  })

  it('calls dismissLanGateModal when dismiss button is clicked in modal variant', async () => {
    statusRef.value = { enabled: false, in_whitelist: false, in_dynamic_allowlist: false, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    const wrapper = await mountPanel({ variant: 'modal' })
    await flushPromises()
    await wrapper.find('.btn-text').trigger('click')
    expect(dismissLanGateModalMock).toHaveBeenCalled()
  })

  it('shows initialization error when load fails', async () => {
    statusRef.value = { enabled: true, in_whitelist: true, in_dynamic_allowlist: true, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    refreshMock.mockRejectedValue(new Error('refresh failed'))
    hostInfoMock.mockRejectedValue(new Error('hostInfo failed'))
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.error').text()).toContain('初始化失败')
  })

  it('renders bootstrap hint box when bootstrap is available', async () => {
    statusRef.value = { enabled: true, in_whitelist: true, in_dynamic_allowlist: false, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    hostInfoMock.mockResolvedValue({ bootstrap_available: true, token_ttl_seconds: 28800 })
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.hint-box').exists()).toBe(true)
    expect(wrapper.find('.hint-box').text()).toContain('LAN_ADMIN_BOOTSTRAP_KEY')
  })

  it('renders label input when bootstrap is available', async () => {
    statusRef.value = { enabled: true, in_whitelist: true, in_dynamic_allowlist: false, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    hostInfoMock.mockResolvedValue({ bootstrap_available: true, token_ttl_seconds: 28800 })
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('input[placeholder*="财务老李"]').exists()).toBe(true)
  })

  it('shows warn-lead when admin key unlocked but no clearance and no bootstrap', async () => {
    statusRef.value = { enabled: true, in_whitelist: true, in_dynamic_allowlist: false, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    hostInfoMock.mockResolvedValue({ bootstrap_available: false, token_ttl_seconds: 28800 })
    const wrapper = await mountPanel()
    await flushPromises()
    await wrapper.find('.admin-key-entry .btn.ghost').trigger('click')
    expect(wrapper.find('.warn-lead').exists()).toBe(true)
    expect(wrapper.find('.warn-lead').text()).toContain('管理员密钥')
  })

  it('shows different lead text when userKeyClearance is true', async () => {
    statusRef.value = { enabled: true, in_whitelist: true, in_dynamic_allowlist: true, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    const wrapper = await mountPanel()
    await flushPromises()
    expect(wrapper.find('.lead').text()).toContain('一级密钥')
  })

  it('redirects to home when authorized on load', async () => {
    statusRef.value = { enabled: true, in_whitelist: true, in_dynamic_allowlist: true, authorized: true, is_admin_host: false, ip: '1.1.1.1' }
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
    statusRef.value = { enabled: false, in_whitelist: false, in_dynamic_allowlist: false, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    const wrapper = await mountPanel({ redirectPath: '/custom' })
    await flushPromises()
    expect(wrapper.find('.lan-gate-panel').exists()).toBe(true)
  })

  it('uses "/" when redirectPath is empty', async () => {
    statusRef.value = { enabled: false, in_whitelist: false, in_dynamic_allowlist: false, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
    const wrapper = await mountPanel({ redirectPath: '   ' })
    await flushPromises()
    expect(wrapper.find('.lan-gate-panel').exists()).toBe(true)
  })

  it('shows "正在校验…" text when submitting', async () => {
    statusRef.value = { enabled: true, in_whitelist: true, in_dynamic_allowlist: true, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
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
    statusRef.value = { enabled: true, in_whitelist: false, in_dynamic_allowlist: false, authorized: false, is_admin_host: false, ip: '1.1.1.1' }
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
})
