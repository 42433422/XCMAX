import { type Ref } from 'vue'
export interface UseChatDbTokenGateDeps {
  sessionId: Ref<string>
  isProMode: Ref<boolean>
  pendingDbWriteChatRetryMessages: Ref<string[] | null>
  plannerWriteUnlockResumeDraft: Ref<string>
  executeRemoteChatRound: (msgs: string[], opts?: { fromWriteUnlock?: boolean }) => Promise<void>
}

export function useChatDbTokenGate(deps: UseChatDbTokenGateDeps) {
  const {
    sessionId,
    isProMode,
    pendingDbWriteChatRetryMessages,
    plannerWriteUnlockResumeDraft,
    executeRemoteChatRound,
  } = deps

  function isProModeActiveFromDom(): boolean {
    const overlay = document.getElementById('proModeOverlay')
    const bodyActive = document.body.classList.contains('pro-mode-active')
    const overlayActive = !!overlay?.classList.contains('active')
    const overlayVisible = !!overlay && overlay.style.display !== 'none'
    return bodyActive || (overlayActive && overlayVisible)
  }

  function resolveEffectiveProModeState(): boolean {
    const overlay = document.getElementById('proModeOverlay')
    if (!overlay && typeof window.__XCAGI_IS_PRO_MODE === 'boolean') {
      return !!window.__XCAGI_IS_PRO_MODE
    }
    const domState = isProModeActiveFromDom()
    if (typeof window.__XCAGI_IS_PRO_MODE === 'boolean') {
      if (window.__XCAGI_IS_PRO_MODE !== domState) {
        window.__XCAGI_IS_PRO_MODE = domState
        window.dispatchEvent(new CustomEvent('xcagi:pro-mode-changed', {
          detail: { isProMode: domState }
        }))
      }
    }
    return domState
  }

  function syncProModeState() {
    isProMode.value = resolveEffectiveProModeState()
  }

  function getModeScopedUserId(proEnabled: boolean): string {
    const sid = String(sessionId.value || '').trim() || 'default'
    return proEnabled ? `web_pro_${sid}` : `web_normal_${sid}`
  }

  function resolveChatDbTokensForPayload(): { db_read_token?: string; db_write_token?: string } {
    return {}
  }

  function handleChatRequiresToken(
    tokenName?: unknown,
    tokenDescription?: unknown,
    retryMessages?: string[] | null
  ) {
    void tokenName
    void tokenDescription
    void retryMessages
    pendingDbWriteChatRetryMessages.value = null
  }

  function onDbWriteUnlockedForChatRetry() {
    const msgs = pendingDbWriteChatRetryMessages.value
    pendingDbWriteChatRetryMessages.value = null
    if (!msgs?.length) return
    void executeRemoteChatRound(msgs, { fromWriteUnlock: true })
  }

  return {
    resolveEffectiveProModeState,
    syncProModeState,
    getModeScopedUserId,
    resolveChatDbTokensForPayload,
    handleChatRequiresToken,
    onDbWriteUnlockedForChatRetry,
  }
}
