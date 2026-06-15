import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { ref } from 'vue';

const armNext = vi.fn();
const consumeArm = vi.fn();
const isArmed = vi.fn();
const isGrace = vi.fn();
const readTokens = vi.fn();
const executeRemote = vi.fn();

vi.mock('@/fhd/dbTokenHeaders', () => ({
  XCAGI_PROMPT_DB_READ_TOKEN_EVENT: 'xcagi:prompt-db-read',
  XCAGI_PROMPT_DB_WRITE_TOKEN_EVENT: 'xcagi:prompt-db-write',
  armNextPlannerChatDbWriteToken: () => armNext(),
  consumePlannerChatDbWriteTokenArm: () => consumeArm(),
  isPlannerChatDbWriteTokenArmed: () => isArmed(),
  isProductsReadGateGraceActive: () => isGrace(),
  readStoredDbTokens: () => readTokens(),
}));

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
  armNext.mockReset();
  consumeArm.mockReset();
  isArmed.mockReset();
  isGrace.mockReset();
  readTokens.mockReset();
  executeRemote.mockReset();
  readTokens.mockReturnValue({ read: 'r1', write: 'w1' });
  isGrace.mockReturnValue(true);
  isArmed.mockReturnValue(true);
});

describe('useChatDbTokenGate', () => {
  it('getModeScopedUserId scopes by pro mode', () => {
    const deps = makeDeps();
    const gate = useChatDbTokenGate(deps);
    expect(gate.getModeScopedUserId(false)).toBe('web_normal_sess-1');
    expect(gate.getModeScopedUserId(true)).toBe('web_pro_sess-1');
  });

  it('resolveChatDbTokensForPayload attaches tokens when armed', () => {
    const deps = makeDeps();
    const gate = useChatDbTokenGate(deps);
    expect(gate.resolveChatDbTokensForPayload()).toEqual({
      db_read_token: 'r1',
      db_write_token: 'w1',
    });
    expect(consumeArm).toHaveBeenCalled();
  });

  it('handleChatRequiresToken dispatches read prompt', () => {
    const deps = makeDeps();
    const gate = useChatDbTokenGate(deps);
    const handler = vi.fn();
    window.addEventListener('xcagi:prompt-db-read', handler);
    gate.handleChatRequiresToken('DB_READ_TOKEN', '只读密钥');
    expect(deps.pendingDbWriteChatRetryMessages.value).toBeNull();
    expect(handler).toHaveBeenCalled();
    window.removeEventListener('xcagi:prompt-db-read', handler);
  });

  it('onDbWriteUnlockedForChatRetry resumes pending messages', async () => {
    const deps = makeDeps();
    deps.pendingDbWriteChatRetryMessages.value = ['hello'];
    executeRemote.mockResolvedValue(undefined);
    const gate = useChatDbTokenGate(deps);
    gate.onDbWriteUnlockedForChatRetry();
    expect(armNext).toHaveBeenCalled();
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
