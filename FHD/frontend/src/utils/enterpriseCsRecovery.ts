/** In-memory, principal-bound recovery; never put customer message drafts into shared storage. */
import { computed, watch, type Ref } from 'vue'
import { productReadAccountEpoch } from './productReadAccountScope'
import { getRuntimeTenantStorageScopeInput } from './tenantStorageScopeRuntime'

type Snapshot = { principal: string; conversation: number; draft: string; error: string; uncertain: boolean }
let saved: Snapshot | null = null

function principal(): string {
  const scope = getRuntimeTenantStorageScopeInput()
  if (!scope || (!scope.marketUserId && !(scope.tenantId && scope.localUserId))) return ''
  return JSON.stringify([scope.tenantId ?? null, scope.marketUserId ?? null, scope.localUserId ?? null, scope.accountKind ?? ''])
}

export function clearEnterpriseCsRecovery(): void { saved = null }

// A temporarily invalid session may recover as the same principal. A verified
// different principal must never inherit the previous user's retained draft.
watch(productReadAccountEpoch, () => {
  const next = principal()
  if (next && saved && saved.principal !== next) saved = null
}, { flush: 'sync' })

export function useEnterpriseCsRecovery(options: {
  draft: Ref<string>; error: Ref<string>; uncertain: Ref<boolean>
  conversationId: Ref<number | null>; active: () => boolean
}): void {
  let restoring = false
  const key = computed(() => {
    void productReadAccountEpoch.value
    const owner = principal()
    return options.active() && options.conversationId.value && owner
      ? JSON.stringify([owner, options.conversationId.value]) : ''
  })
  watch(key, (next, previous) => {
    const owner = principal()
    if (!next && !previous) return
    if (next && (!saved || saved.principal !== owner || saved.conversation !== options.conversationId.value)) {
      saved = { principal: owner, conversation: options.conversationId.value!, draft: '', error: '', uncertain: false }
    }
    const restore = next && saved ? { ...saved } : null
    restoring = true
    options.draft.value = restore?.draft ?? ''
    options.error.value = restore?.error ?? ''
    options.uncertain.value = restore?.uncertain ?? false
    restoring = false
  }, { immediate: true, flush: 'sync' })
  watch([options.draft, options.error, options.uncertain], () => {
    if (!restoring && key.value && saved) {
      saved.draft = options.draft.value
      saved.error = options.error.value
      saved.uncertain = options.uncertain.value
    }
  }, { flush: 'sync' })
}
