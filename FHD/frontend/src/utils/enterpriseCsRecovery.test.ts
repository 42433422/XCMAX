import { afterEach, describe, expect, it, vi } from 'vitest'
import { effectScope, ref } from 'vue'
const state = vi.hoisted(() => ({ owner: { tenantId: 't1', marketUserId: 1, localUserId: 1 } }))
vi.mock('./tenantStorageScopeRuntime', () => ({ getRuntimeTenantStorageScopeInput: () => state.owner }))
import { clearEnterpriseCsRecovery, useEnterpriseCsRecovery } from './enterpriseCsRecovery'
import { productReadAccountEpoch } from './productReadAccountScope'
const scopes: ReturnType<typeof effectScope>[] = []
function mount() {
  const scope = effectScope(); scopes.push(scope)
  const options = { draft: ref(''), error: ref(''), uncertain: ref(false), conversationId: ref<number | null>(7), active: () => true }
  scope.run(() => useEnterpriseCsRecovery(options))
  return { ...options, stop: () => scope.stop() }
}
afterEach(() => { scopes.splice(0).forEach(s => s.stop()); clearEnterpriseCsRecovery(); state.owner = { tenantId: 't1', marketUserId: 1, localUserId: 1 } })
describe('enterprise CS principal-bound memory recovery', () => {
  it('retains an unsent draft and uncertainty across route remount', () => {
    const first = mount(); first.draft.value = 'synthetic unsent report'; first.error.value = 'receipt unknown'; first.uncertain.value = true; first.stop()
    const next = mount()
    expect(next.draft.value).toBe('synthetic unsent report'); expect(next.error.value).toBe('receipt unknown'); expect(next.uncertain.value).toBe(true)
  })
  it('does not expose another account draft', () => {
    const first = mount(); first.draft.value = 'private synthetic draft'; first.stop()
    state.owner = { tenantId: 't2', marketUserId: 2, localUserId: 2 }; productReadAccountEpoch.value++
    expect(mount().draft.value).toBe('')
  })
  it('clears retained content on explicit logout', () => {
    const first = mount(); first.draft.value = 'discard on logout'; first.stop(); clearEnterpriseCsRecovery()
    expect(mount().draft.value).toBe('')
  })
})
