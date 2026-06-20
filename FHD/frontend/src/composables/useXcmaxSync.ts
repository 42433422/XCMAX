import type { ImMessage } from '@/api/im';

const CURSOR_STORAGE_KEY = 'xcmax_sync_cursor';

export const XCMAX_SYNC_IM_MESSAGE_EVENT = 'xcmax:sync:im-message';
export const XCMAX_SYNC_IM_READ_EVENT = 'xcmax:sync:im-read-state';

export type XcmaxSyncChange = {
  id: number;
  entity_type: string;
  entity_id: string;
  operation: string;
  payload: Record<string, unknown>;
};

export type XcmaxImMessageDetail = {
  conversation_id: number;
  message: ImMessage;
  change?: XcmaxSyncChange;
};

export type XcmaxImReadStateDetail = {
  conversation_id: number;
  user_id: number;
  last_message_id: number;
  change?: XcmaxSyncChange;
};

type SsePayload = {
  type?: string;
  cursor?: number;
  changes?: XcmaxSyncChange[];
  status?: Record<string, unknown>;
};

let eventSource: EventSource | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let reconnectDelayMs = 3000;
let streamActive = false;
let streamCreatedAt = 0;

function readStoredCursor(): number {
  if (typeof window === 'undefined') return 0;
  try {
    const raw = window.localStorage.getItem(CURSOR_STORAGE_KEY);
    const n = Number(raw);
    return Number.isFinite(n) && n >= 0 ? n : 0;
  } catch {
    return 0;
  }
}

function writeStoredCursor(cursor: number): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(CURSOR_STORAGE_KEY, String(Math.max(0, cursor)));
  } catch {
    /* ignore */
  }
}

function parseImMessageFromPayload(payload: Record<string, unknown>): ImMessage | null {
  const raw = (payload.message ?? payload) as Record<string, unknown>;
  const id = Number(raw.id);
  const conversationId = Number(raw.conversation_id ?? payload.conversation_id);
  const senderUserId = Number(raw.sender_user_id);
  if (!Number.isFinite(id) || id <= 0 || !Number.isFinite(conversationId) || conversationId <= 0) {
    return null;
  }
  return {
    id,
    conversation_id: conversationId,
    sender_user_id: Number.isFinite(senderUserId) ? senderUserId : 0,
    sender_display_name: raw.sender_display_name ? String(raw.sender_display_name) : undefined,
    body: String(raw.body ?? ''),
    created_at: raw.created_at ? String(raw.created_at) : null,
  };
}

function parseImReadStateFromPayload(payload: Record<string, unknown>): XcmaxImReadStateDetail | null {
  const conversationId = Number(payload.conversation_id);
  const userId = Number(payload.user_id);
  const lastMessageId = Number(payload.last_message_id);
  if (
    !Number.isFinite(conversationId) ||
    conversationId <= 0 ||
    !Number.isFinite(userId) ||
    userId <= 0 ||
    !Number.isFinite(lastMessageId) ||
    lastMessageId < 0
  ) {
    return null;
  }
  return {
    conversation_id: conversationId,
    user_id: userId,
    last_message_id: lastMessageId,
  };
}

function dispatchImChange(change: XcmaxSyncChange): void {
  if (typeof window === 'undefined') return;
  if (change.entity_type === 'im_message') {
    const message = parseImMessageFromPayload(change.payload);
    if (!message) return;
    const detail: XcmaxImMessageDetail = {
      conversation_id: message.conversation_id,
      message,
      change,
    };
    window.dispatchEvent(new CustomEvent(XCMAX_SYNC_IM_MESSAGE_EVENT, { detail }));
    return;
  }
  if (change.entity_type === 'im_read_state') {
    const readState = parseImReadStateFromPayload(change.payload);
    if (!readState) return;
    const detail: XcmaxImReadStateDetail = { ...readState, change };
    window.dispatchEvent(new CustomEvent(XCMAX_SYNC_IM_READ_EVENT, { detail }));
  }
}

function handleSseData(raw: string): void {
  let data: SsePayload;
  try {
    data = JSON.parse(raw) as SsePayload;
  } catch {
    return;
  }
  if (data.type === 'connected') {
    reconnectDelayMs = 3000;
    return;
  }
  if (data.type === 'heartbeat') {
    if (typeof data.cursor === 'number' && data.cursor >= 0) {
      writeStoredCursor(data.cursor);
    }
    return;
  }
  if (!Array.isArray(data.changes) || !data.changes.length) return;
  if (typeof data.cursor === 'number' && data.cursor >= 0) {
    writeStoredCursor(data.cursor);
  } else {
    const lastId = data.changes[data.changes.length - 1]?.id;
    if (typeof lastId === 'number' && lastId >= 0) {
      writeStoredCursor(lastId);
    }
  }
  for (const change of data.changes) {
    dispatchImChange(change);
  }
}

function scheduleReconnect(): void {
  if (!streamActive || reconnectTimer != null) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    if (streamActive) openEventSource();
  }, reconnectDelayMs);
  reconnectDelayMs = Math.min(reconnectDelayMs * 2, 30_000);
}

function openEventSource(): void {
  if (typeof window === 'undefined' || typeof EventSource === 'undefined' || eventSource) return;
  const cursor = readStoredCursor();
  const url = `/api/xcmax/sync/stream?since_cursor=${cursor}`;
  eventSource = new EventSource(url);
  streamCreatedAt = Date.now();
  eventSource.onmessage = (e) => handleSseData(String(e.data ?? ''));
  eventSource.onerror = () => {
    const es = eventSource;
    eventSource = null;
    if (es) {
      try {
        es.close();
      } catch {
        /* ignore */
      }
    }
    if (!streamActive) return;
    scheduleReconnect();
  };
}

function closeEventSource(): void {
  if (reconnectTimer != null) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  reconnectDelayMs = 3000;
  const age = Date.now() - streamCreatedAt;
  if (age < 2000 && eventSource) {
    const es = eventSource;
    eventSource = null;
    setTimeout(() => {
      try {
        es.close();
      } catch {
        /* ignore */
      }
    }, 500);
    return;
  }
  if (eventSource) {
    try {
      eventSource.close();
    } catch {
      /* ignore */
    }
    eventSource = null;
  }
}

export function useXcmaxSync() {
  function start(): void {
    if (streamActive) return;
    streamActive = true;
    openEventSource();
  }

  function stop(): void {
    streamActive = false;
    closeEventSource();
  }

  function onImMessage(handler: (detail: XcmaxImMessageDetail) => void): () => void {
    const listener = (evt: Event) => {
      handler((evt as CustomEvent<XcmaxImMessageDetail>).detail);
    };
    window.addEventListener(XCMAX_SYNC_IM_MESSAGE_EVENT, listener as EventListener);
    return () => window.removeEventListener(XCMAX_SYNC_IM_MESSAGE_EVENT, listener as EventListener);
  }

  function onImReadState(handler: (detail: XcmaxImReadStateDetail) => void): () => void {
    const listener = (evt: Event) => {
      handler((evt as CustomEvent<XcmaxImReadStateDetail>).detail);
    };
    window.addEventListener(XCMAX_SYNC_IM_READ_EVENT, listener as EventListener);
    return () => window.removeEventListener(XCMAX_SYNC_IM_READ_EVENT, listener as EventListener);
  }

  return {
    start,
    stop,
    readCursor: readStoredCursor,
    onImMessage,
    onImReadState,
  };
}
