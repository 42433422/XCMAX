import { type Ref } from 'vue'
import { readAiSessionIdFromStorage } from '@/utils/xcagiStorageKeys'

export interface UseChatDbTokenGateDeps {
  sessionId: Ref<string>
  pendingDbWriteChatRetryMessages: Ref<string[] | null>
  plannerWriteUnlockResumeDraft: Ref<string>
  executeRemoteChatRound: (msgs: string[], opts?: { fromWriteUnlock?: boolean }) => Promise<void>
}

/** 与对话请求 body.user_id 同源：``web_normal_<session>``。 */
export function resolveModeScopedChatUserId(): string {
  const sid = String(readAiSessionIdFromStorage() || '').trim() || 'default'
  return `web_normal_${sid}`
}

export function useChatDbTokenGate(deps: UseChatDbTokenGateDeps) {
  const {
    sessionId,
    pendingDbWriteChatRetryMessages,
    plannerWriteUnlockResumeDraft,
    executeRemoteChatRound,
  } = deps

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
    resolveChatDbTokensForPayload,
    handleChatRequiresToken,
    onDbWriteUnlockedForChatRetry,
  }
}
