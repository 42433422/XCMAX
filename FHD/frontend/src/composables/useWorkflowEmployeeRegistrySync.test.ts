import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, reactive, ref, type Ref } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  owner: null as unknown as Ref<string>,
  mods: null as unknown as { clientModsUiOff: boolean; activeModId: string; modsForWorkflowUi: unknown[]; entitledModIds: string[]; initialize: ReturnType<typeof vi.fn> },
  workflow: null as unknown as { registryEntries: { id: string }[] },
  sync: vi.fn(),
}))
vi.mock('@/stores/mods', () => ({ useModsStore: () => mocks.mods }))
vi.mock('@/stores/workflowAiEmployees', () => ({ useWorkflowAiEmployeesStore: () => mocks.workflow }))
vi.mock('@/api/employeeDirectory', () => ({ employeeDirectoryScope: () => mocks.owner.value }))
vi.mock('@/utils/syncEnterpriseWorkflowRegistry', () => ({ syncEnterpriseWorkflowRegistry: mocks.sync }))

import { useWorkflowEmployeeRegistrySync } from './useWorkflowEmployeeRegistrySync'

describe('useWorkflowEmployeeRegistrySync', () => {
  let wrapper: VueWrapper | undefined
  function mountSync() {
    let result!: ReturnType<typeof useWorkflowEmployeeRegistrySync>
    wrapper = mount(defineComponent({
      setup() { result = useWorkflowEmployeeRegistrySync(); return () => null },
    }))
    return result
  }

  beforeEach(() => {
    mocks.owner = ref('account-a')
    mocks.mods = reactive({ clientModsUiOff: false, activeModId: '', modsForWorkflowUi: [], entitledModIds: [], initialize: vi.fn().mockResolvedValue(undefined) })
    mocks.workflow = reactive({ registryEntries: [{ id: 'verified-employee' }] })
    mocks.sync.mockReset().mockResolvedValue({})
  })
  afterEach(() => wrapper?.unmount())

  it('keeps the last directory on error, exposes a retry and clears the error after recovery', async () => {
    mocks.sync.mockRejectedValueOnce(new Error('directory unavailable'))
    const sync = mountSync()
    await flushPromises()
    expect(sync.error.value).toBe('directory unavailable')
    expect(mocks.workflow.registryEntries).toEqual([{ id: 'verified-employee' }])
    await sync.refresh()
    expect(sync.error.value).toBe('')
    expect(mocks.sync).toHaveBeenLastCalledWith({ forceDirectory: true })
  })

  it('clears the old account immediately and ignores its late failure', async () => {
    let reject!: (reason: Error) => void
    mocks.sync.mockReturnValueOnce(new Promise((_resolve, failure) => { reject = failure }))
    const sync = mountSync()
    await flushPromises()
    mocks.owner.value = 'account-b'
    await flushPromises()
    expect(mocks.workflow.registryEntries).toEqual([])
    expect(mocks.sync).toHaveBeenCalledTimes(2)
    reject(new Error('old account failure'))
    await flushPromises()
    expect(sync.error.value).toBe('')
  })

  it('does not fetch when employee extensions are disabled', async () => {
    mocks.mods.clientModsUiOff = true
    const sync = mountSync()
    await flushPromises()
    await sync.refresh()
    expect(mocks.mods.initialize).not.toHaveBeenCalled()
    expect(mocks.sync).not.toHaveBeenCalled()
  })
})
