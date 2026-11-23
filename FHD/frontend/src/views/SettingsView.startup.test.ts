import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, h, KeepAlive } from 'vue'
import { startupPageReadyKey } from '@/composables/useStartupSplash'

const boundary = await vi.hoisted(async () => {
  const { ref } = await import('vue')
  return {
    account: { avatarInputRef: ref(null), localUser: ref({ id: 41, username: 'synthetic-user' }), isLoggedIn: ref(true), loadLocalUser: vi.fn(), loadAuditLogs: vi.fn() },
    mods: { currentIndustry: ref('default'), loadIndustries: vi.fn(), loadCurrentIndustryDetail: vi.fn(), loadIntentPackages: vi.fn() },
    basics: { sidebarThemePreset: ref('dark'), loadPreferences: vi.fn(), loadAutoLaunch: vi.fn(), loadDesktopDatabaseStatus: vi.fn(), loadDistillationVersions: vi.fn() },
    memory: { persyLoading: ref(false), loadPersyProfile: vi.fn() },
    runtimeCheck: vi.fn(),
  }
})
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {}, fullPath: '/settings' }) }))
vi.mock('@/api/core', () => ({ api: { post: boundary.runtimeCheck } }))
vi.mock('@/stores/mods', () => ({ useModsStore: () => ({ isLoaded: true, initialize: vi.fn() }) }))
vi.mock('@/stores/industry', () => ({ useIndustryStore: () => ({ currentIndustry: { id: 'server-selected' }, initialize: vi.fn().mockResolvedValue(undefined) }) }))
vi.mock('@/stores/accountProfile', () => ({ useAccountProfileStore: () => ({ accountKind: 'personal', isAdminAccount: false, isImpersonating: false }) }))
vi.mock('@/composables/settings/useSettingsAccount', () => ({ useSettingsAccount: () => boundary.account }))
vi.mock('@/composables/settings/useSettingsMods', () => ({ useSettingsMods: () => boundary.mods }))
vi.mock('@/composables/settings/useSettingsBasics', () => ({ useSettingsBasics: () => boundary.basics }))
vi.mock('@/composables/settings/useSettingsMemory', () => ({ useSettingsMemory: () => boundary.memory }))
vi.mock('@/utils/sidebarTheme', () => ({ readStoredSidebarTheme: () => 'dark', applySidebarTheme: vi.fn() }))
vi.mock('@/components/HostModBridgeView.vue', () => ({ default: { render: () => null } }))
vi.mock('./settings-view/SettingsAuditLogsCard.vue', () => ({ default: { render: () => null } }))
vi.mock('./settings-view/SettingsIntentCard.vue', () => ({ default: { render: () => null } }))
vi.mock('./settings-view/SettingsMemoryV2Card.vue', () => ({ default: { render: () => null } }))
vi.mock('./settings-view/SettingsBasicCard.vue', () => ({ default: { render: () => null } }))
vi.mock('./settings-view/SettingsVersionsCard.vue', () => ({ default: { render: () => null } }))
vi.mock('./settings-view/SettingsAboutCard.vue', () => ({ default: { render: () => null } }))
vi.mock('./settings-view/SettingsPlatformModelCard.vue', () => ({ default: { render: () => null } }))
import SettingsView from './SettingsView.vue'

function pending() {
  let resolve!: () => void
  const promise = new Promise<void>(done => { resolve = done })
  return { promise, resolve }
}
let wrapper: VueWrapper | undefined
let prepare!: (signal: AbortSignal) => Promise<void>
const unregister = vi.fn()
function open() {
  wrapper = mount(defineComponent({ setup() { return () => h(KeepAlive, null, { default: () => h(SettingsView) }) } }), {
    global: { provide: { [startupPageReadyKey as symbol]: (read: typeof prepare) => { prepare = read; return unregister } }, stubs: { RouterLink: true } },
  })
}
beforeEach(() => {
  vi.clearAllMocks()
  boundary.account.isLoggedIn.value = true
  boundary.account.localUser.value = { id: 41, username: 'synthetic-user' }
  boundary.runtimeCheck.mockReset().mockResolvedValue({ success: true, qualification: 'passed', route: { model: 'litellm/account-model' } })
  boundary.account.loadLocalUser.mockReset().mockResolvedValue(undefined)
  boundary.mods.loadIndustries.mockReset().mockResolvedValue(undefined)
  boundary.mods.loadCurrentIndustryDetail.mockReset().mockResolvedValue(undefined)
  for (const background of [boundary.account.loadAuditLogs, boundary.mods.loadIntentPackages,
    boundary.basics.loadPreferences, boundary.basics.loadAutoLaunch, boundary.basics.loadDesktopDatabaseStatus,
    boundary.basics.loadDistillationVersions, boundary.memory.loadPersyProfile]) {
    background.mockReset().mockReturnValue(new Promise(() => {}))
  }
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined })

describe('settings first-screen startup registration', () => {
  it('checks the account runtime only on an explicit click without posting credentials or model overrides', async () => {
    open()
    await flushPromises()
    expect(boundary.runtimeCheck).not.toHaveBeenCalled()
    await wrapper!.get('[data-testid="runtime-check"]').trigger('click')
    await flushPromises()
    expect(boundary.runtimeCheck).toHaveBeenCalledOnce()
    expect(boundary.runtimeCheck).toHaveBeenCalledWith('/api/desktop/agent-runtime/qualification', { retry: true }, expect.objectContaining({ timeoutMs: 600_000, retry: false, signal: expect.any(AbortSignal) }))
    expect(wrapper!.text()).toContain('本次运行验收已通过（litellm/account-model）')
  })

  it('disables repeat attempts and discards a late qualification result after account change', async () => {
    let finish!: (value: object) => void
    boundary.runtimeCheck.mockReturnValue(new Promise(resolve => { finish = resolve }))
    open()
    await flushPromises()
    await wrapper!.get('[data-testid="runtime-check"]').trigger('click')
    expect(wrapper!.get('[data-testid="runtime-check"]').attributes('disabled')).toBeDefined()
    await wrapper!.get('[data-testid="runtime-check"]').trigger('click')
    expect(boundary.runtimeCheck).toHaveBeenCalledOnce()
    const signal = boundary.runtimeCheck.mock.calls[0][2].signal as AbortSignal
    boundary.account.localUser.value = { id: 42, username: 'second-user' }
    await flushPromises()
    expect(signal.aborted).toBe(true)
    finish({ success: true, qualification: 'passed', route: { model: 'previous-account-model' } })
    await flushPromises()
    expect(wrapper!.text()).not.toContain('previous-account-model')
    boundary.account.isLoggedIn.value = false
    await flushPromises()
    expect(wrapper!.find('[data-testid="runtime-check"]').exists()).toBe(false)
  })

  it('shows a blocked qualification without claiming runtime readiness', async () => {
    boundary.runtimeCheck.mockRejectedValue({ data: { error_code: 'runtime_configuration_required', message: '请补全模型容量' } })
    open()
    await flushPromises()
    await wrapper!.get('[data-testid="runtime-check"]').trigger('click')
    await flushPromises()
    expect(wrapper!.text()).toContain('请补全模型容量')
    expect(wrapper!.text()).not.toContain('本次运行验收已通过')
  })

  it.each(['account', 'industries', 'details'] as const)('keeps startup pending for actual %s data and coalesces first keep-alive activation', async resource => {
    const delayed = pending()
    const read = resource === 'account' ? boundary.account.loadLocalUser : resource === 'industries' ? boundary.mods.loadIndustries : boundary.mods.loadCurrentIndustryDetail
    read.mockReturnValue(delayed.promise)
    open()
    await flushPromises()
    let ready = false
    const startup = prepare(new AbortController().signal).then(() => { ready = true })
    await flushPromises()
    expect(ready).toBe(false)
    expect(read).toHaveBeenCalledOnce()
    if (resource === 'account') {
      expect(read).toHaveBeenCalledWith(expect.objectContaining({ required: true, current: expect.any(Function) }))
    } else if (resource === 'industries') {
      expect(boundary.mods.loadCurrentIndustryDetail).toHaveBeenCalledOnce()
    } else {
      expect(boundary.mods.loadIndustries).toHaveBeenCalledOnce()
    }
    delayed.resolve()
    await startup
    expect(ready).toBe(true)
    expect(boundary.account.loadLocalUser).toHaveBeenCalledOnce()
    expect(boundary.mods.loadIndustries).toHaveBeenCalledOnce()
    expect(boundary.mods.loadCurrentIndustryDetail).toHaveBeenCalledOnce()
  })

  it('propagates required data failure to startup and performs fresh reads on explicit retry', async () => {
    boundary.mods.loadCurrentIndustryDetail.mockRejectedValueOnce(new Error('synthetic required details failure'))
    open()
    await flushPromises()
    await expect(prepare(new AbortController().signal)).rejects.toThrow('synthetic required details failure')
    await expect(prepare(new AbortController().signal)).resolves.toBeUndefined()
    expect(boundary.account.loadLocalUser).toHaveBeenCalledTimes(2)
    expect(boundary.mods.loadCurrentIndustryDetail).toHaveBeenCalledTimes(2)
  })

  it('unregisters page readiness when leaving the settings component', async () => {
    open()
    await flushPromises()
    wrapper!.unmount(); wrapper = undefined
    expect(unregister).toHaveBeenCalled()
  })
})
