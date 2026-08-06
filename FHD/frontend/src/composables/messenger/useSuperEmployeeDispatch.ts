/**
 * IM 信息页（ImMessengerView）「超级员工 / 值班员工」派工调度引擎。
 *
 * 收敛 Codex / Claude / Cursor 超级员工与值班员工的：
 *  - 会话状态（codexMessages / codexDraft / codexBusy / codexDispatch…
 *    / dutyEmployeeMessages / dutyEmployeeDraft / dutyEmployeeBusy）
 *  - 打字机流式回复（startCodexTypewriter / ensureCodexTypewriter / stopCodexTypewriter）
 *  - 轮询调度（startCodexPolling / stopCodexPolling）
 *  - 派工发送（onCodexSend / onDutyEmployeeSend）
 *  - 会话激活（activatePinnedEntry）与员工列表加载（loadDutyEmployees）
 *
 * 入参为父组件持有的共享 ref 与回调；返回的 ref / computed / 函数由父组件
 * 解构后继续供模板与其余 composable 使用。WebSocket / 普通会话 IO 仍由父组件负责。
 */
import { computed, nextTick, ref, type Ref } from 'vue';
import api from '@/api';
import { showAppToast } from '@/composables/useAppToast';
import { productErrorMessage } from '@/utils/productErrorMessage';
import { fetchEmployeeSsot } from '@/utils/platformShellApi';
import {
  dutyEmployeesFromEmployeeSsot,
  type EmployeeSsotPayload,
} from '@/utils/employeeSsotContacts';
import { type ImContact, type ImConversationSummary, type ImMessage } from '@/api/im';
import {
  fetchCodexSuperEmployeeMessages,
  sendCodexSuperEmployeeMessage,
  type CodexSuperEmployeeApiScope,
  type CodexSuperEmployeeDispatch,
  type CodexSuperEmployeeMessage,
} from '@/api/codexSuperEmployee';
import {
  fetchClaudeSuperEmployeeMessages,
  sendClaudeSuperEmployeeMessage,
} from '@/api/claudeSuperEmployee';
import {
  fetchCursorSuperEmployeeMessages,
  sendCursorSuperEmployeeMessage,
} from '@/api/cursorSuperEmployee';
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl';
import {
  CODEX_STREAM_PLACEHOLDER_ID,
  dutyEmployeeReplyFromExecution,
  fallbackDutyEmployees,
  isAiGroupChatEntry,
  isClaudeSuperEmployeeEntry,
  isCodexDispatcherMessage,
  isCodexSuperEmployeeEntry,
  isSuperEmployeeEntry,
  isCursorSuperEmployeeEntry,
  isDutyEmployeeEntry,
  isExternalAppEntry,
  latestCodexDispatcherMessage,
  normalizeDutyEmployee,
  uniqueDutyEmployees,
  type ActiveSuperTool,
  type CodexDisplayMessage,
  type DutyEmployeeChatMessage,
  type DutyEmployeeEntry,
  type EmployeeExecuteResponse,
  type ExternalAppEntry,
  type PinnedImEntry,
  type SystemEmployeeEntry,
} from './useMessengerEntries';
import { useCodexStreamEngine } from './useCodexStreamEngine';

type MobileApiResponse<T> = {
  success?: boolean;
  code?: number;
  message?: string;
  data?: T;
};

type AdminEmployeesPayload = {
  items?: import('./useMessengerEntries').AdminEmployeeApiItem[];
  employees?: import('./useMessengerEntries').AdminEmployeeApiItem[];
  count?: number;
};

export type UseSuperEmployeeDispatchParams = {
  activeSystemEntry: Ref<SystemEmployeeEntry | null>;
  activeExternalEntry: Ref<ExternalAppEntry | null>;
  activeConversationId: Ref<number | null>;
  activeGroupChat: Ref<boolean>;
  messages: Ref<ImMessage[]>;
  hasMoreHistory: Ref<boolean>;
  localUserId: Ref<number | null>;
  isAdminCustomerServiceConsole: Ref<boolean>;
  imApiReachable: Ref<boolean>;
  dutyEmployees: Ref<DutyEmployeeEntry[]>;
  closeContactPicker: () => void;
  startChatWith: (contact: ImContact) => Promise<void>;
  closeOverlappingAssistantFloat: () => void;
  restoreOverlappingAssistantFloat: () => void;
};

export function useSuperEmployeeDispatch(params: UseSuperEmployeeDispatchParams) {
  const {
    activeSystemEntry,
    activeExternalEntry,
    activeConversationId,
    activeGroupChat,
    messages,
    hasMoreHistory,
    localUserId,
    isAdminCustomerServiceConsole,
    imApiReachable,
    dutyEmployees,
    closeContactPicker,
    startChatWith,
    closeOverlappingAssistantFloat,
    restoreOverlappingAssistantFloat,
  } = params;

  const codexMessages = ref<CodexSuperEmployeeMessage[]>([]);
  const codexDraft = ref('');
  const codexBusy = ref(false);
  const codexDispatch = ref<CodexSuperEmployeeDispatch | null>(null);
  const dutyEmployeeMessages = ref<Record<string, DutyEmployeeChatMessage[]>>({});
  const dutyEmployeeDraft = ref('');
  const dutyEmployeeBusy = ref(false);
  const codexScrollEl = ref<HTMLElement | null>(null);
  const dutyEmployeeScrollEl = ref<HTMLElement | null>(null);
  const codexInputEl = ref<HTMLInputElement | null>(null);

  const codexApiScope = computed<CodexSuperEmployeeApiScope>(() =>
    isAdminConsoleSpa() ? 'admin' : 'mobile',
  );

  function activeSuperTool(entry: SystemEmployeeEntry | null): ActiveSuperTool | null {
    if (!entry) return null;
    if (isCodexSuperEmployeeEntry(entry)) return 'codex';
    if (isClaudeSuperEmployeeEntry(entry)) return 'claude';
    if (isCursorSuperEmployeeEntry(entry)) return 'cursor';
    return null;
  }

  function fetchActiveSuperMessages(): Promise<CodexSuperEmployeeMessage[]> {
    const tool = activeSuperTool(activeSystemEntry.value);
    if (tool === 'claude') {
      return fetchClaudeSuperEmployeeMessages({ scope: codexApiScope.value });
    }
    if (tool === 'cursor') {
      return fetchCursorSuperEmployeeMessages({ scope: codexApiScope.value });
    }
    return fetchCodexSuperEmployeeMessages({ scope: codexApiScope.value });
  }

  const {
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
  } = useCodexStreamEngine({
    codexMessages,
    codexScrollEl,
    activeSystemEntry,
    fetchActiveSuperMessages,
  });

  function sendActiveSuperMessage(message: string, context: Record<string, unknown>) {
    const tool = activeSuperTool(activeSystemEntry.value);
    if (tool === 'claude') {
      return sendClaudeSuperEmployeeMessage(message, context, { scope: codexApiScope.value });
    }
    if (tool === 'cursor') {
      return sendCursorSuperEmployeeMessage(message, context, { scope: codexApiScope.value });
    }
    return sendCodexSuperEmployeeMessage(message, context, { scope: codexApiScope.value });
  }

  const codexSenderLabel = computed(() =>
    codexApiScope.value === 'mobile' ? '手机端' : '管理端',
  );

  const codexContextSource = computed(() =>
    codexApiScope.value === 'mobile' ? 'mobile_im' : 'admin_im',
  );

  const codexLastStatus = computed(() => {
    const status = String(codexDispatch.value?.status || '').trim();
    if (!status) return '等待派工';
    if (status === 'accepted') return '已分发';
    if (status === 'queued') return '已入队';
    if (status === 'dispatch_failed' || status === 'dispatch_error') return '待重试';
    return status;
  });

  const codexVisibleMessages = computed<CodexDisplayMessage[]>(() => {
    const visible = codexMessages.value
      .filter((m) => !isCodexDispatcherMessage(m))
      .map<CodexDisplayMessage>((m) => {
        const streaming = m.id === codexStreamMessageId.value && Boolean(codexStreamBody.value);
        return {
          ...m,
          body: streaming ? codexStreamBody.value : m.body,
          streaming: streaming && codexStreamActive.value,
        };
      });

    if (
      codexStreamBody.value
      && codexStreamMessageId.value === CODEX_STREAM_PLACEHOLDER_ID
    ) {
      visible.push({
        id: CODEX_STREAM_PLACEHOLDER_ID,
        role: 'assistant',
        body: codexStreamBody.value,
        created_at: codexStreamCreatedAt.value || new Date().toISOString(),
        status: 'running',
        kind: 'codex_stream',
        dispatch_request_id: codexStreamRequestId.value,
        streaming: codexStreamActive.value,
        synthetic: true,
      });
    }
    return visible;
  });

  const activeDutyEmployeeMessages = computed<DutyEmployeeChatMessage[]>(() => {
    const entry = activeSystemEntry.value;
    if (!entry || !isDutyEmployeeEntry(entry)) return [];
    return dutyEmployeeMessages.value[entry.id] || [];
  });

  function systemEntryRuntimeStatus(entry: SystemEmployeeEntry): string {
    if (isSuperEmployeeEntry(entry)) {
      return codexBusy.value ? '提交中' : codexStreamActive.value ? '回复中' : '可派工';
    }
    return dutyEmployeeBusy.value && activeSystemEntry.value?.id === entry.id ? '执行中' : '可对话';
  }

  function systemEntryLastStatus(entry: SystemEmployeeEntry): string {
    if (isSuperEmployeeEntry(entry)) return codexLastStatus.value;
    const last = (dutyEmployeeMessages.value[entry.id] || []).at(-1);
    if (!last) return '等待任务';
    return last.role === 'assistant' ? (last.status || '已回复') : '已发送';
  }

  function appendDutyEmployeeMessage(employeeId: string, message: DutyEmployeeChatMessage): void {
    dutyEmployeeMessages.value = {
      ...dutyEmployeeMessages.value,
      [employeeId]: [...(dutyEmployeeMessages.value[employeeId] || []), message],
    };
    void nextTick(() => {
      const el = dutyEmployeeScrollEl.value;
      if (el) el.scrollTop = el.scrollHeight;
    });
  }

  function codexMessageRoleLabel(message: CodexSuperEmployeeMessage): string {
    if (message.role === 'user') return codexSenderLabel.value;
    const tool = activeSuperTool(activeSystemEntry.value);
    if (tool === 'claude') return 'Claude';
    if (tool === 'cursor') return 'Cursor';
    return 'Codex';
  }

  function focusCodexInput(): void {
    const tryFocus = () => {
      if (!isSuperEmployeeEntry(activeSystemEntry.value) || codexBusy.value) return;
      try {
        const active = document.activeElement;
        if (active instanceof HTMLElement && active !== codexInputEl.value) {
          active.blur();
        }
        codexInputEl.value?.focus({ preventScroll: true });
      } catch {
        codexInputEl.value?.focus();
      }
    };
    void nextTick(() => {
      tryFocus();
      window.setTimeout(tryFocus, 80);
      window.setTimeout(tryFocus, 240);
      window.setTimeout(tryFocus, 600);
    });
  }

  async function activatePinnedEntry(entry: PinnedImEntry): Promise<void> {
    if (isAiGroupChatEntry(entry)) {
      closeOverlappingAssistantFloat();
      stopCodexPolling();
      stopCodexTypewriter(true);
      activeExternalEntry.value = null;
      activeSystemEntry.value = null;
      activeConversationId.value = null;
      activeGroupChat.value = true;
      messages.value = [];
      hasMoreHistory.value = false;
      closeContactPicker();
      return;
    }
    if (isExternalAppEntry(entry)) {
      closeOverlappingAssistantFloat();
      stopCodexPolling();
      stopCodexTypewriter(true);
      activeExternalEntry.value = entry;
      activeSystemEntry.value = null;
      activeConversationId.value = null;
      messages.value = [];
      hasMoreHistory.value = false;
      closeContactPicker();
      return;
    }
    if (isSuperEmployeeEntry(entry)) {
      closeOverlappingAssistantFloat();
      stopCodexPolling();
      stopCodexTypewriter(true);
      activeExternalEntry.value = null;
      activeSystemEntry.value = entry;
      activeConversationId.value = null;
      activeGroupChat.value = false;
      messages.value = [];
      codexMessages.value = [];
      hasMoreHistory.value = false;
      closeContactPicker();
      await loadCodexConversation();
      focusCodexInput();
      return;
    }
    if (isDutyEmployeeEntry(entry)) {
      closeOverlappingAssistantFloat();
      stopCodexPolling();
      stopCodexTypewriter(true);
      activeExternalEntry.value = null;
      activeSystemEntry.value = entry;
      activeConversationId.value = null;
      activeGroupChat.value = false;
      messages.value = [];
      hasMoreHistory.value = false;
      closeContactPicker();
      await nextTick();
      const el = dutyEmployeeScrollEl.value;
      if (el) el.scrollTop = el.scrollHeight;
      return;
    }
    restoreOverlappingAssistantFloat();
    stopCodexPolling();
    stopCodexTypewriter(true);
    activeExternalEntry.value = null;
    activeSystemEntry.value = null;
    activeGroupChat.value = false;
    await startChatWith(entry);
  }

  async function loadCodexConversation(options: { syncStream?: boolean } = {}): Promise<void> {
    if (!isAdminCustomerServiceConsole.value) return;
    try {
      const next = await fetchActiveSuperMessages();
      codexMessages.value = next;
      if (options.syncStream !== false) {
        const shouldContinue = syncCodexStreamFromMessages(next, codexStreamRequestId.value);
        if (shouldContinue && !isCodexPollingActive.value) {
          const dispatcher = latestCodexDispatcherMessage(next, codexStreamRequestId.value);
          startCodexPolling(String(dispatcher?.dispatch_request_id || codexStreamRequestId.value || ''));
        }
      }
      await nextTick();
      scrollCodexToBottom();
    } catch (error) {
      showAppToast(error instanceof Error ? error.message : '加载 Codex 对话失败', 'error');
    } finally {
      focusCodexInput();
    }
  }

  async function loadDutyEmployees(): Promise<void> {
    if (!isAdminCustomerServiceConsole.value) {
      dutyEmployees.value = [];
      return;
    }
    if (!dutyEmployees.value.length) {
      dutyEmployees.value = uniqueDutyEmployees(fallbackDutyEmployees());
    }
    try {
      const ssot = (await fetchEmployeeSsot()) as EmployeeSsotPayload;
      const fromSsot = dutyEmployeesFromEmployeeSsot(ssot);
      if (fromSsot.length) {
        dutyEmployees.value = uniqueDutyEmployees(fromSsot as DutyEmployeeEntry[]);
        imApiReachable.value = true;
        return;
      }
    } catch {
      /* fallback to mobile admin employees */
    }
    try {
      const response = await api.get<MobileApiResponse<AdminEmployeesPayload>>('/api/mobile/v1/admin/employees');
      imApiReachable.value = true;
      const payload = response.data || {};
      const rawItems = payload.items || payload.employees || [];
      const normalized = rawItems
        .map(normalizeDutyEmployee)
        .filter((item): item is DutyEmployeeEntry => Boolean(item));
      if (normalized.length) {
        dutyEmployees.value = uniqueDutyEmployees(normalized);
      }
    } catch (error) {
      showAppToast(
        productErrorMessage(error, '员工通讯录暂时不可用，已使用本地编制兜底'),
        'warning',
      );
    }
  }

  async function onCodexSend(): Promise<void> {
    if (!isSuperEmployeeEntry(activeSystemEntry.value)) return;
    if (codexBusy.value) return;
    const text = codexDraft.value.trim();
    if (!text) return;
    closeOverlappingAssistantFloat();
    codexBusy.value = true;
    stopCodexPolling();
    const localRequestId = `local-${Date.now()}`;
    const now = new Date().toISOString();
    codexDraft.value = '';
    codexMessages.value = [
      ...codexMessages.value,
      {
        id: `local-user-${localRequestId}`,
        role: 'user',
        body: text,
        created_at: now,
        status: 'sent',
        dispatch_request_id: localRequestId,
      },
    ];
    startCodexTypewriter({
      body: 'Codex 正在接收任务，准备连接全设备执行环境。',
      requestId: localRequestId,
      createdAt: now,
      active: true,
      reset: true,
    });
    await nextTick();
    scrollCodexToBottom();
    try {
      const result = await sendActiveSuperMessage(text, {
        source: codexContextSource.value,
        client_surface: codexApiScope.value === 'mobile' ? 'mobile' : 'admin_console',
        target_devices: ['all'],
      });
      codexDispatch.value = result.dispatch ?? null;
      codexMessages.value = result.messages;
      const requestId = String(
        result.message?.dispatch_request_id
        || result.assistant_message?.dispatch_request_id
        || result.dispatch?.request_id
        || localRequestId,
      );
      const shouldContinue = syncCodexStreamFromMessages(result.messages, requestId);
      if (shouldContinue) startCodexPolling(requestId);
      await nextTick();
      scrollCodexToBottom();
      focusCodexInput();
    } catch (error) {
      stopCodexTypewriter(true);
      showAppToast(error instanceof Error ? error.message : 'Codex 调用失败', 'error');
    } finally {
      codexBusy.value = false;
      focusCodexInput();
    }
  }

  async function onDutyEmployeeSend(): Promise<void> {
    const entry = activeSystemEntry.value;
    if (!entry || !isDutyEmployeeEntry(entry)) return;
    if (dutyEmployeeBusy.value) return;
    const text = dutyEmployeeDraft.value.trim();
    if (!text) return;
    const localId = `duty-${entry.id}-${Date.now()}`;
    const now = new Date().toISOString();
    dutyEmployeeDraft.value = '';
    dutyEmployeeBusy.value = true;
    appendDutyEmployeeMessage(entry.id, {
      id: `${localId}-user`,
      role: 'user',
      body: text,
      created_at: now,
      status: 'sent',
    });
    try {
      const result = await api.post<EmployeeExecuteResponse>(
        `/api/xcmax/local/employees/${encodeURIComponent(entry.id)}/execute`,
        {
          task: text,
          user_id: localUserId.value || 0,
          input_data: {
            source: 'admin_im',
            client_surface: 'admin_console',
            invoke_mode: 'interactive_chat',
            allow_medium_risk: true,
            employee_id: entry.id,
            employee_name: entry.display_name,
          },
        },
      );
      appendDutyEmployeeMessage(entry.id, {
        id: `${localId}-assistant`,
        role: 'assistant',
        body: dutyEmployeeReplyFromExecution(result, entry),
        created_at: new Date().toISOString(),
        status: result.success === false ? '失败' : '已回复',
      });
    } catch (error) {
      appendDutyEmployeeMessage(entry.id, {
        id: `${localId}-error`,
        role: 'assistant',
        body: error instanceof Error ? `调用失败：${error.message}` : '调用失败：未知错误',
        created_at: new Date().toISOString(),
        status: '失败',
      });
    } finally {
      dutyEmployeeBusy.value = false;
    }
  }

  return {
    codexApiScope,
    codexMessages,
    codexDraft,
    codexBusy,
    codexDispatch,
    codexStreamBody,
    codexStreamMessageId,
    codexStreamRequestId,
    codexStreamCreatedAt,
    codexStreamActive,
    codexSenderLabel,
    codexContextSource,
    codexLastStatus,
    codexVisibleMessages,
    activeDutyEmployeeMessages,
    dutyEmployeeMessages,
    dutyEmployeeDraft,
    dutyEmployeeBusy,
    codexScrollEl,
    dutyEmployeeScrollEl,
    codexInputEl,
    activatePinnedEntry,
    loadCodexConversation,
    loadDutyEmployees,
    onCodexSend,
    onDutyEmployeeSend,
    systemEntryRuntimeStatus,
    systemEntryLastStatus,
    codexMessageRoleLabel,
    appendDutyEmployeeMessage,
    focusCodexInput,
    scrollCodexToBottom,
    stopCodexPolling,
    stopCodexTypewriter,
  };
}