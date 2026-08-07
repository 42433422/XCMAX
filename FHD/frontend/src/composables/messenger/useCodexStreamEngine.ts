/**
 * Codex 超级员工「流式打字机 + 轮询调度」引擎。
 *
 * 从 useSuperEmployeeDispatch 中拆出的独立 composable，收敛：
 *  - codexStream*（body/messageId/requestId/createdAt/active）反应式状态
 *  - 打字机流式回复（ensureCodexTypewriter / startCodexTypewriter / stopCodexTypewriter）
 *  - 轮询调度（startCodexPolling / stopCodexPolling）
 *  - 从 dispatcher/result 消息同步流式正文（syncCodexStreamFromMessages）
 *
 * 入参为父 composable 持有的共享 ref 与消息拉取回调；返回的 ref / 函数由父组件
 * 解构后继续供模板与其余逻辑使用。所有内部计时器 / 目标字符串均封装在本引擎内。
 */
import { computed, nextTick, ref, type Ref } from 'vue';

import { type CodexSuperEmployeeMessage } from '@/api/codexSuperEmployee';
import {
  CODEX_POLL_INTERVAL_MS,
  CODEX_POLL_MAX_ROUNDS,
  CODEX_STREAM_PLACEHOLDER_ID,
  codexReplyFromDispatcher,
  isCodexDispatchStillOpen,
  isSuperEmployeeEntry,
  latestCodexDispatcherMessage,
  latestCodexResultMessage,
  sanitizeCodexReplyText,
  type SystemEmployeeEntry,
} from './useMessengerEntries';

export type CodexStreamEngineInput = {
  codexMessages: Ref<CodexSuperEmployeeMessage[]>;
  codexScrollEl: Ref<HTMLElement | null>;
  activeSystemEntry: Ref<SystemEmployeeEntry | null>;
  fetchActiveSuperMessages: () => Promise<CodexSuperEmployeeMessage[]>;
};

export function useCodexStreamEngine(input: CodexStreamEngineInput) {
  const {
    codexMessages,
    codexScrollEl,
    activeSystemEntry,
    fetchActiveSuperMessages,
  } = input;

  const codexStreamBody = ref('');
  const codexStreamMessageId = ref('');
  const codexStreamRequestId = ref('');
  const codexStreamCreatedAt = ref('');
  const codexStreamActive = ref(false);

  let codexStreamTarget = '';
  let codexStreamTimer: ReturnType<typeof setInterval> | null = null;
  let codexPollTimer: ReturnType<typeof setTimeout> | null = null;
  let codexPollRound = 0;

  const isCodexPollingActive = computed(() => Boolean(codexPollTimer));

  function scrollCodexToBottom(): void {
    const el = codexScrollEl.value;
    if (el) el.scrollTop = el.scrollHeight;
  }

  function stopCodexTypewriter(clearBody = false): void {
    if (codexStreamTimer) {
      clearInterval(codexStreamTimer);
      codexStreamTimer = null;
    }
    if (clearBody) {
      codexStreamBody.value = '';
      codexStreamTarget = '';
      codexStreamMessageId.value = '';
      codexStreamRequestId.value = '';
      codexStreamCreatedAt.value = '';
      codexStreamActive.value = false;
    }
  }

  function stopCodexPolling(): void {
    if (codexPollTimer) {
      clearTimeout(codexPollTimer);
      codexPollTimer = null;
    }
    codexPollRound = 0;
  }

  function ensureCodexTypewriter(): void {
    if (codexStreamTimer) return;
    codexStreamTimer = setInterval(() => {
      if (!codexStreamTarget) {
        stopCodexTypewriter();
        return;
      }
      const current = codexStreamBody.value;
      if (current.length >= codexStreamTarget.length) {
        stopCodexTypewriter();
        codexStreamActive.value = codexStreamMessageId.value === CODEX_STREAM_PLACEHOLDER_ID
          && Boolean(codexPollTimer);
        return;
      }
      const remaining = codexStreamTarget.length - current.length;
      const step = Math.max(1, Math.min(8, Math.ceil(remaining / 18)));
      codexStreamBody.value = codexStreamTarget.slice(0, current.length + step);
      codexStreamActive.value = true;
      void nextTick().then(scrollCodexToBottom);
    }, 34);
  }

  function startCodexTypewriter(options: {
    body: string;
    messageId?: string;
    requestId?: string;
    createdAt?: string;
    active?: boolean;
    reset?: boolean;
  }): void {
    const target = sanitizeCodexReplyText(options.body);
    if (!target) return;
    const nextMessageId = options.messageId || CODEX_STREAM_PLACEHOLDER_ID;
    const messageChanged = codexStreamMessageId.value !== nextMessageId;
    codexStreamTarget = target;
    codexStreamMessageId.value = nextMessageId;
    codexStreamRequestId.value = options.requestId || codexStreamRequestId.value;
    codexStreamCreatedAt.value = options.createdAt || codexStreamCreatedAt.value || new Date().toISOString();
    if (
      options.reset
      || messageChanged
      || !target.startsWith(codexStreamBody.value)
      || codexStreamBody.value.length > target.length
    ) {
      codexStreamBody.value = target.slice(0, Math.min(target.length, 10));
    }
    codexStreamActive.value = options.active !== false || codexStreamBody.value.length < target.length;
    ensureCodexTypewriter();
    void nextTick().then(scrollCodexToBottom);
  }

  function syncCodexStreamFromMessages(
    items: CodexSuperEmployeeMessage[],
    requestId = '',
  ): boolean {
    const effectiveRequestId = requestId || String(
      latestCodexDispatcherMessage(items)?.dispatch_request_id || '',
    );
    const dispatcher = latestCodexDispatcherMessage(items, effectiveRequestId);
    if (!requestId && !isCodexDispatchStillOpen(dispatcher)) {
      return false;
    }
    const result = effectiveRequestId ? latestCodexResultMessage(items, effectiveRequestId) : null;
    if (result) {
      startCodexTypewriter({
        body: result.body,
        messageId: result.id,
        requestId: String(result.dispatch_request_id || effectiveRequestId || ''),
        createdAt: result.created_at,
        active: false,
        reset: codexStreamMessageId.value !== result.id,
      });
      return false;
    }
    if (!dispatcher) return false;
    startCodexTypewriter({
      body: codexReplyFromDispatcher(dispatcher),
      messageId: CODEX_STREAM_PLACEHOLDER_ID,
      requestId: String(dispatcher.dispatch_request_id || effectiveRequestId || ''),
      createdAt: dispatcher.created_at,
      active: isCodexDispatchStillOpen(dispatcher),
      reset: codexStreamMessageId.value !== CODEX_STREAM_PLACEHOLDER_ID,
    });
    return isCodexDispatchStillOpen(dispatcher);
  }

  function startCodexPolling(requestId = ''): void {
    stopCodexPolling();
    codexPollRound = 0;
    const poll = async () => {
      if (!isSuperEmployeeEntry(activeSystemEntry.value)) return;
      codexPollRound += 1;
      try {
        const next = await fetchActiveSuperMessages();
        codexMessages.value = next;
        const shouldContinue = syncCodexStreamFromMessages(next, requestId);
        if (shouldContinue && codexPollRound < CODEX_POLL_MAX_ROUNDS) {
          codexPollTimer = setTimeout(poll, CODEX_POLL_INTERVAL_MS);
        } else {
          codexPollTimer = null;
        }
        await nextTick();
        scrollCodexToBottom();
      } catch {
        if (codexPollRound < CODEX_POLL_MAX_ROUNDS) {
          codexPollTimer = setTimeout(poll, CODEX_POLL_INTERVAL_MS);
        } else {
          codexPollTimer = null;
        }
      }
    };
    codexPollTimer = setTimeout(poll, CODEX_POLL_INTERVAL_MS);
  }

  return {
    codexStreamBody,
    codexStreamMessageId,
    codexStreamRequestId,
    codexStreamCreatedAt,
    codexStreamActive,
    scrollCodexToBottom,
    stopCodexTypewriter,
    stopCodexPolling,
    startCodexTypewriter,
    syncCodexStreamFromMessages,
    startCodexPolling,
    isCodexPollingActive,
  };
}