import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { ref } from 'vue';

const executeRemote = vi.fn();
const readAiSessionIdFromStorageMock = vi.fn(() => 'stored-sid');

vi.mock('@/utils/xcagiStorageKeys', () => ({
  readAiSessionIdFromStorage: () => readAiSessionIdFromStorageMock(),
}));

import { resolveModeScopedChatUserId, useChatDbTokenGate } from './useChatDbTokenGate';

function makeDeps() {
  return {
    sessionId: ref('sess-1'),
    pendingDbWriteChatRetryMessages: ref<string[] | null>(null),
    plannerWriteUnlockResumeDraft: ref(''),
    executeRemoteChatRound: executeRemote,
  };
}

beforeEach(() => {
  setActivePinia(createPinia());
  document.body.className = '';
  executeRemote.mockReset();
  readAiSessionIdFromStorageMock.mockReset();
  readAiSessionIdFromStorageMock.mockReturnValue('stored-sid');
});

describe('useChatDbTokenGate', () => {
  it('resolveModeScopedChatUserId matches chat web_normal key', () => {
    expect(resolveModeScopedChatUserId()).toBe('web_normal_stored-sid');
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
});
