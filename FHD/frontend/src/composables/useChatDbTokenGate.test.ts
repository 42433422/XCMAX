import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { ref } from 'vue';

const executeRemote = vi.fn();

import { useChatDbTokenGate } from './useChatDbTokenGate';

function makeDeps() {
  return {
    sessionId: ref('sess-1'),
    isProMode: ref(false),
    pendingDbWriteChatRetryMessages: ref<string[] | null>(null),
    plannerWriteUnlockResumeDraft: ref(''),
    executeRemoteChatRound: executeRemote,
  };
}

beforeEach(() => {
  setActivePinia(createPinia());
  document.body.className = '';
  delete (window as Window & { __XCAGI_IS_PRO_MODE?: boolean }).__XCAGI_IS_PRO_MODE;
  executeRemote.mockReset();
});

describe('useChatDbTokenGate', () => {
  it('getModeScopedUserId scopes by pro mode', () => {
    const deps = makeDeps();
    const gate = useChatDbTokenGate(deps);
    expect(gate.getModeScopedUserId(false)).toBe('web_normal_sess-1');
    expect(gate.getModeScopedUserId(true)).toBe('web_pro_sess-1');
  });

  it('resolveChatDbTokensForPayload never attaches database password tokens', () => {
    const deps = makeDeps();
    const gate = useChatDbTokenGate(deps);
    expect(gate.resolveChatDbTokensForPayload()).toEqual({});
  });

  it('handleChatRequiresToken ignores legacy database token requests', () => {
    const deps = makeDeps();
    const gate = useChatDbTokenGate(deps);
    const handler = vi.fn();
    window.addEventListener('xcagi:prompt-db-read', handler);
    window.addEventListener('xcagi:prompt-db-write', handler);
    gate.handleChatRequiresToken('DB_READ_TOKEN', '只读密钥');
    gate.handleChatRequiresToken('DB_WRITE_TOKEN', '写入');
    expect(deps.pendingDbWriteChatRetryMessages.value).toBeNull();
    expect(handler).not.toHaveBeenCalled();
    window.removeEventListener('xcagi:prompt-db-read', handler);
    window.removeEventListener('xcagi:prompt-db-write', handler);
  });

  it('onDbWriteUnlockedForChatRetry resumes pending messages', async () => {
    const deps = makeDeps();
    deps.pendingDbWriteChatRetryMessages.value = ['hello'];
    executeRemote.mockResolvedValue(undefined);
    const gate = useChatDbTokenGate(deps);
    gate.onDbWriteUnlockedForChatRetry();
    expect(executeRemote).toHaveBeenCalledWith(['hello'], { fromWriteUnlock: true });
    expect(deps.pendingDbWriteChatRetryMessages.value).toBeNull();
  });

  it('syncProModeState reads DOM overlay', () => {
    document.body.classList.add('pro-mode-active');
    const deps = makeDeps();
    const gate = useChatDbTokenGate(deps);
    gate.syncProModeState();
    expect(deps.isProMode.value).toBe(true);
  });
});
