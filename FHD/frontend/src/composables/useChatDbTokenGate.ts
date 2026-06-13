import { type Ref } from 'vue'
import {
  XCAGI_PROMPT_DB_READ_TOKEN_EVENT,
  XCAGI_PROMPT_DB_WRITE_TOKEN_EVENT,
  armNextPlannerChatDbWriteToken,
  consumePlannerChatDbWriteTokenArm,
  isPlannerChatDbWriteTokenArmed,
  isProductsReadGateGraceActive,
  readStoredDbTokens,
} from '@/fhd/dbTokenHeaders'

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
    const { read, write } = readStoredDbTokens()
    const out: { db_read_token?: string; db_write_token?: string } = {}
    if (isProductsReadGateGraceActive() && read) {
      out.db_read_token = read
    }
    if (write && isPlannerChatDbWriteTokenArmed()) {
      out.db_write_token = write
      consumePlannerChatDbWriteTokenArm()
    }
    return out
  }

  function handleChatRequiresToken(
    tokenName?: unknown,
    tokenDescription?: unknown,
    retryMessages?: string[] | null
  ) {
    const name = String(tokenName || '').trim().toUpperCase()
    const desc = String(tokenDescription || '').trim()
    if (name.includes('READ') || /只读|一级|查看/.test(desc)) {
      pendingDbWriteChatRetryMessages.value = null
      window.dispatchEvent(new CustomEvent(XCAGI_PROMPT_DB_READ_TOKEN_EVENT, { detail: {} }))
      return
    }
    /**
     * DB_WRITE_TOKEN / 二级 / 写入 / 导入：AI 识别到写入类工具（如 Excel 导入数据库）时，
     * 后端会在 Planner SSE / Unified Chat 中回传 requires_token。
     * 前端据此自动弹出 GlobalWriteTokenPrompt，让用户输入二级密钥后 AI 会自动续接执行。
     */
    if (name.includes('WRITE') || /二级|写入|导入|入库/.test(desc)) {
      if (retryMessages && retryMessages.length) {
        pendingDbWriteChatRetryMessages.value = [...retryMessages]
      }
      window.dispatchEvent(
        new CustomEvent(XCAGI_PROMPT_DB_WRITE_TOKEN_EVENT, {
          detail: { description: desc, tokenName: name },
        })
      )
    }
  }

  function onDbWriteUnlockedForChatRetry() {
    const msgs = pendingDbWriteChatRetryMessages.value
    pendingDbWriteChatRetryMessages.value = null
    if (!msgs?.length) return
    armNextPlannerChatDbWriteToken()
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
