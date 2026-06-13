import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';

const getStarredContacts = vi.fn();
const refreshMessagesCache = vi.fn();
const sendMessageApi = vi.fn();

vi.mock('@/api/wechat', () => ({
  wechatApi: {
    getStarredContacts: () => getStarredContacts(),
    refreshMessagesCache: () => refreshMessagesCache(),
    sendMessage: (id: string, msg: string) => sendMessageApi(id, msg),
  },
}));

import { useWorkModeStore } from './workMode';

beforeEach(() => {
  setActivePinia(createPinia());
  getStarredContacts.mockReset();
  refreshMessagesCache.mockReset();
  sendMessageApi.mockReset();
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('workMode computed', () => {
  it('filters starred and unread contacts', () => {
    const s = useWorkModeStore();
    s.contacts = [
      { id: 1, is_starred: true, unreadCount: 2 },
      { id: 2, is_starred: false, unreadCount: 0 },
      { id: 3, is_starred: true, unreadCount: 0 },
    ] as never;
    expect(s.starredContacts.map((c) => c.id)).toEqual([1, 3]);
    expect(s.unreadContacts.map((c) => c.id)).toEqual([1]);
  });
});

describe('workMode loadContacts', () => {
  it('stores contacts on success', async () => {
    getStarredContacts.mockResolvedValue({ data: [{ id: 1, is_starred: true }] });
    const s = useWorkModeStore();
    await s.loadContacts();
    expect(s.contacts).toHaveLength(1);
    expect(s.loading).toBe(false);
    expect(s.error).toBeNull();
  });

  it('captures error message on failure', async () => {
    getStarredContacts.mockRejectedValue(new Error('boom'));
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const s = useWorkModeStore();
    await s.loadContacts();
    expect(s.error).toBe('boom');
    expect(s.loading).toBe(false);
  });
});

describe('workMode getMessageSourceSize', () => {
  it('reads numeric size', async () => {
    refreshMessagesCache.mockResolvedValue({ data: { size: 42 } });
    const s = useWorkModeStore();
    await s.getMessageSourceSize();
    expect(s.lastMessageSourceSize).toBe(42);
  });

  it('null when size is not a number', async () => {
    refreshMessagesCache.mockResolvedValue({ data: {} });
    const s = useWorkModeStore();
    await s.getMessageSourceSize();
    expect(s.lastMessageSourceSize).toBeNull();
  });

  it('swallows errors', async () => {
    refreshMessagesCache.mockRejectedValue(new Error('x'));
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const s = useWorkModeStore();
    await s.getMessageSourceSize();
    expect(s.lastMessageSourceSize).toBeNull();
  });
});

describe('workMode message processing', () => {
  it('processNewMessages updates matching contact', () => {
    const s = useWorkModeStore();
    s.contacts = [{ id: 7, unreadCount: 0 }] as never;
    s.processNewMessages([{ contactId: 7, content: 'hi', timestamp: 't1' }] as never);
    const c = s.contacts[0] as never as { lastMessage: string; unreadCount: number };
    expect(c.lastMessage).toBe('hi');
    expect(c.unreadCount).toBe(1);
  });

  it('handleTaskAcquisition flags order on keyword', () => {
    const s = useWorkModeStore();
    s.handleTaskAcquisition({ content: '我要下订单', order: { id: 'o1' } } as never);
    expect(s.isTaskAcquisition).toBe(true);
    expect(s.currentOrder).toEqual({ id: 'o1' });
  });

  it('handleTaskAcquisition ignores non-task content', () => {
    const s = useWorkModeStore();
    s.handleTaskAcquisition({ content: '你好啊' } as never);
    expect(s.isTaskAcquisition).toBe(false);
  });

  it('resetTaskAcquisition clears state', () => {
    const s = useWorkModeStore();
    s.isTaskAcquisition = true;
    s.currentOrder = { id: 'x' } as never;
    s.resetTaskAcquisition();
    expect(s.isTaskAcquisition).toBe(false);
    expect(s.currentOrder).toBeNull();
  });
});

describe('workMode sendMessage', () => {
  it('updates contact on success', async () => {
    sendMessageApi.mockResolvedValue({});
    const s = useWorkModeStore();
    s.contacts = [{ id: 5, unreadCount: 3 }] as never;
    await s.sendMessage(5, 'yo');
    const c = s.contacts[0] as never as { lastMessage: string; unreadCount: number };
    expect(c.lastMessage).toBe('yo');
    expect(c.unreadCount).toBe(0);
  });

  it('rethrows and records error on failure', async () => {
    sendMessageApi.mockRejectedValue(new Error('net'));
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const s = useWorkModeStore();
    await expect(s.sendMessage(5, 'yo')).rejects.toThrow('net');
    expect(s.error).toBe('net');
  });

  it('sendOpeningMessage picks a preset and sends', async () => {
    sendMessageApi.mockResolvedValue({});
    const s = useWorkModeStore();
    await s.sendOpeningMessage(9);
    expect(sendMessageApi).toHaveBeenCalledTimes(1);
    expect(sendMessageApi.mock.calls[0][0]).toBe('9');
  });
});

describe('workMode polling', () => {
  it('start/stop polling toggles interval handle', () => {
    vi.useFakeTimers();
    const s = useWorkModeStore();
    s.startPolling();
    expect(s.pollingInterval).not.toBeNull();
    s.stopPolling();
    expect(s.pollingInterval).toBeNull();
  });
});

describe('workMode fetchWorkModeFeed', () => {
  it('processes messages and task from feed', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      json: async () => ({
        messages: [{ contactId: 1, content: '订单来了', timestamp: 't' }],
        taskAcquisition: { content: '需要采购', order: { id: 'o9' } },
      }),
    });
    vi.stubGlobal('fetch', fetchMock);
    const s = useWorkModeStore();
    s.contacts = [{ id: 1, unreadCount: 0 }] as never;
    await s.fetchWorkModeFeed();
    expect((s.contacts[0] as never as { unreadCount: number }).unreadCount).toBe(1);
    expect(s.isTaskAcquisition).toBe(true);
    vi.unstubAllGlobals();
  });

  it('swallows fetch errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('down')));
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const s = useWorkModeStore();
    await s.fetchWorkModeFeed();
    expect(s.isTaskAcquisition).toBe(false);
    vi.unstubAllGlobals();
  });
});

describe('workMode downloadOrder', () => {
  it('triggers a blob download', async () => {
    const blob = new Blob(['x']);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ blob: async () => blob }));
    const createURL = vi.fn().mockReturnValue('blob:url');
    const revokeURL = vi.fn();
    Object.defineProperty(window.URL, 'createObjectURL', { value: createURL, configurable: true });
    Object.defineProperty(window.URL, 'revokeObjectURL', { value: revokeURL, configurable: true });
    const s = useWorkModeStore();
    await s.downloadOrder('o1');
    expect(createURL).toHaveBeenCalledWith(blob);
    expect(revokeURL).toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it('records error when download fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('dl')));
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const s = useWorkModeStore();
    await expect(s.downloadOrder('o1')).rejects.toThrow('dl');
    expect(s.error).toBe('dl');
    vi.unstubAllGlobals();
  });
});
