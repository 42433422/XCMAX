import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { effectScope, ref, type EffectScope, type Ref } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises } from '@vue/test-utils'

const mock = vi.hoisted(() => ({ owner: null as unknown as Ref<string>, resolve: vi.fn() }))
vi.mock('@/api/employeeDirectory', () => ({ employeeDirectoryScope: () => mock.owner.value }))
vi.mock('@/utils/enterpriseModStackApi', () => ({ resolveEnterpriseModStack: mock.resolve }))
import { useEnterpriseScopedWorkflowRegistry } from './useEnterpriseScopedWorkflowRegistry'

describe('useEnterpriseScopedWorkflowRegistry', () => {
  let scope: EffectScope
  beforeEach(() => {
    setActivePinia(createPinia())
    mock.owner = ref('account-a')
    mock.resolve.mockReset()
    scope = effectScope()
  })
  afterEach(() => scope.stop())

  it('clears an old stack immediately and does not publish its late response', async () => {
    mock.resolve.mockResolvedValueOnce({ stackLabel: 'A' })
    const registry = scope.run(useEnterpriseScopedWorkflowRegistry)!
    await flushPromises()
    expect(registry.enterpriseStack.value?.stackLabel).toBe('A')
    let finish!: (stack: unknown) => void
    mock.resolve.mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const oldRefresh = registry.refresh()
    mock.resolve.mockResolvedValueOnce({ stackLabel: 'B' })
    mock.owner.value = 'account-b'
    expect(registry.enterpriseStack.value).toBeNull()
    await flushPromises()
    finish({ stackLabel: 'late A' })
    await oldRefresh
    expect(registry.enterpriseStack.value?.stackLabel).toBe('B')
    expect(registry.error.value).toBe('')
  })

  it('reports a current failure, recovers on retry and ignores an old account failure', async () => {
    mock.resolve.mockRejectedValueOnce(new Error('分区读取失败'))
    const registry = scope.run(useEnterpriseScopedWorkflowRegistry)!
    await flushPromises()
    expect(registry.error.value).toBe('分区读取失败')
    mock.resolve.mockResolvedValueOnce({ stackLabel: 'A' })
    await registry.refresh()
    expect(registry.error.value).toBe('')
    let reject!: (reason: Error) => void
    mock.resolve.mockReturnValueOnce(new Promise((_resolve, failure) => { reject = failure }))
    const oldRefresh = registry.refresh()
    mock.resolve.mockResolvedValueOnce({ stackLabel: 'B' })
    mock.owner.value = 'account-b'
    await flushPromises()
    reject(new Error('old failure'))
    await oldRefresh
    expect(registry.error.value).toBe('')
    expect(registry.enterpriseStack.value?.stackLabel).toBe('B')
  })
})
