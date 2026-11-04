import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, nextTick, type EffectScope } from 'vue'

const state = await vi.hoisted(async () => {
  const { reactive, ref } = await import('vue')
  return {
    api: { getIndustries: vi.fn(), getCurrentIndustry: vi.fn() },
    industry: reactive({ industries: [], currentIndustry: { id: 'server-default' }, currentConfig: {} }),
    mods: {
      clientModsUiOff: ref(false), loadError: ref(null), isLoaded: ref(true), mods: ref<unknown[]>([]),
      modRoutes: ref([]), activeModId: ref(''),
    },
  }
})
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/api', () => ({ default: { delete: vi.fn() }, ApiError: class extends Error {} }))
vi.mock('@/api/system', () => ({ systemApi: state.api }))
vi.mock('@/api/intentPackages', () => ({ intentPackagesApi: { getPackages: vi.fn() } }))
vi.mock('@/stores/industry', () => ({ useIndustryStore: () => state.industry }))
vi.mock('@/stores/mods', () => ({ useModsStore: () => state.mods }))
vi.mock('@/stores/accountProfile', () => ({ useAccountProfileStore: () => ({ displayBrand: '' }) }))
vi.mock('@/utils/appDialog', () => ({ appAlert: vi.fn(), appConfirm: vi.fn() }))
vi.mock('@/utils/adminConsoleUrl', () => ({ isAdminConsoleSpa: () => false }))

import { useSettingsMods } from './useSettingsMods'
function pending<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}
const industry = { id: 'verified', name: 'Verified Industry', code: 'verified' }
let scope: EffectScope
let settings: ReturnType<typeof useSettingsMods>
beforeEach(() => {
  vi.clearAllMocks()
  state.mods.mods.value = []
  state.mods.activeModId.value = ''
  state.api.getIndustries.mockReset().mockResolvedValue({ success: true, data: { industries: [industry], current: 'verified' } })
  state.api.getCurrentIndustry.mockReset().mockResolvedValue({ success: true, data: { ...industry, units: { primary: '小时' } } })
  scope = effectScope()
  settings = scope.run(useSettingsMods)!
})
afterEach(() => { scope.stop(); vi.restoreAllMocks() })

describe('required settings industry readiness', () => {
  it('waits for the real industry list response before populating the first screen', async () => {
    const response = pending<unknown>()
    state.api.getIndustries.mockReturnValue(response.promise)
    let done = false
    const loading = settings.loadIndustries({ required: true, current: () => true }).then(() => { done = true })
    await Promise.resolve()
    expect(done).toBe(false)
    expect(settings.industries.value).toEqual([])
    response.resolve({ success: true, data: { industries: [industry], current: 'verified' } })
    await loading
    expect(settings.industries.value).toEqual([industry])
    expect(settings.currentIndustry.value).toBe('verified')
  })

  it('waits for verified current industry details', async () => {
    const response = pending<unknown>()
    state.api.getCurrentIndustry.mockReturnValue(response.promise)
    let done = false
    const loading = settings.loadCurrentIndustryDetail({ required: true, current: () => true }).then(() => { done = true })
    await Promise.resolve()
    expect(done).toBe(false)
    response.resolve({ success: true, data: { ...industry, units: { primary: '小时' } } })
    await loading
    expect(settings.currentIndustryUnit.value).toBe('小时')
  })

  it.each([
    { success: false, data: { industries: [industry] } },
    { data: { industries: [industry] } },
    { success: true, data: null },
    { success: true, data: {} },
    { success: true, data: { industries: 'malformed' } },
  ])('rejects an unverified industry list payload: %j', async payload => {
    state.api.getIndustries.mockResolvedValue(payload)
    await expect(settings.loadIndustries({ required: true, current: () => true })).rejects.toThrow()
    expect(settings.industries.value).toEqual([])
  })

  it.each([
    { success: false, data: industry },
    { data: industry },
    { success: true, data: null },
    { success: true, data: [] },
    { success: true, data: {} },
    { success: true, data: { id: ' ' } },
  ])('rejects unverified current industry details: %j', async payload => {
    state.api.getCurrentIndustry.mockResolvedValue(payload)
    await expect(settings.loadCurrentIndustryDetail({ required: true, current: () => true })).rejects.toThrow()
  })

  it.each(['list', 'detail'])('surfaces a required %s transport failure', async resource => {
    const request = resource === 'list' ? state.api.getIndustries : state.api.getCurrentIndustry
    request.mockRejectedValue(new Error('synthetic settings outage'))
    const read = resource === 'list' ? settings.loadIndustries : settings.loadCurrentIndustryDetail
    await expect(read({ required: true, current: () => true })).rejects.toThrow('synthetic settings outage')
  })

  it('accepts the supported array industry list shape', async () => {
    state.api.getIndustries.mockResolvedValue({ success: true, data: [industry] })
    await settings.loadIndustries({ required: true, current: () => true })
    expect(settings.industries.value).toEqual([industry])
  })

  it('retires a delayed list response without overwriting the current first screen', async () => {
    const response = pending<unknown>()
    state.api.getIndustries.mockReturnValue(response.promise)
    let current = true
    const loading = settings.loadIndustries({ required: true, current: () => current })
    settings.industries.value = [industry]
    settings.currentIndustry.value = 'new-account'
    current = false
    response.resolve({ success: true, data: { industries: [{ ...industry, id: 'old-account' }], current: 'old-account' } })
    await loading
    expect(settings.industries.value).toEqual([industry])
    expect(settings.currentIndustry.value).toBe('new-account')
  })

  it('retires delayed current industry details without changing the visible unit', async () => {
    const response = pending<unknown>()
    state.api.getCurrentIndustry.mockReturnValue(response.promise)
    let current = true
    const loading = settings.loadCurrentIndustryDetail({ required: true, current: () => current })
    settings.currentIndustryUnit.value = 'new-unit'
    current = false
    response.resolve({ success: true, data: { ...industry, units: { primary: 'old-unit' } } })
    await loading
    expect(settings.currentIndustryUnit.value).toBe('new-unit')
  })

  it('applies a late Mod unit after verified server details have already rendered', async () => {
    await settings.loadCurrentIndustryDetail({ required: true, current: () => true })
    expect(settings.currentIndustryUnit.value).toBe('小时')
    state.mods.mods.value = [{ id: 'late-mod', industry: { units: { primary: '班次' } } }]
    state.mods.activeModId.value = 'late-mod'
    await nextTick()
    expect(settings.currentIndustryUnit.value).toBe('班次')
  })

  it('retains active Mod priority during server refresh and restores the latest server unit when removed', async () => {
    state.mods.mods.value = [{ id: 'active-mod', industry: { units: { primary: '班次' } } }]
    state.mods.activeModId.value = 'active-mod'
    await settings.loadCurrentIndustryDetail({ required: true, current: () => true })
    state.api.getCurrentIndustry.mockResolvedValue({ success: true, data: { ...industry, units: { primary: '分钟' } } })
    await settings.loadCurrentIndustryDetail({ required: true, current: () => true })
    expect(settings.currentIndustryUnit.value).toBe('班次')
    state.mods.mods.value = []
    await nextTick()
    expect(settings.currentIndustryUnit.value).toBe('分钟')
  })

  it('restores the server fallback when the active Mod no longer declares a nonempty unit', async () => {
    state.mods.mods.value = [{ id: 'active-mod', industry: { units: { primary: '班次' } } }]
    state.mods.activeModId.value = 'active-mod'
    await settings.loadCurrentIndustryDetail({ required: true, current: () => true })
    expect(settings.currentIndustryUnit.value).toBe('班次')
    state.mods.mods.value = [{ id: 'active-mod', industry: { units: { primary: '  ' } } }]
    await nextTick()
    expect(settings.currentIndustryUnit.value).toBe('小时')
  })

  it('retains ordinary detail fallback when startup strictness is not requested', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    state.mods.mods.value = [{ id: 'active', industry: { units: { primary: '班次' } } }]
    state.mods.activeModId.value = 'active'
    state.api.getCurrentIndustry.mockRejectedValue(new Error('optional display read unavailable'))
    await expect(settings.loadCurrentIndustryDetail()).resolves.toBeUndefined()
    expect(settings.currentIndustryUnit.value).toBe('班次')
  })
})
