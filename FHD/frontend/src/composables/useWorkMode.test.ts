import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';

const startWorkMode = vi.fn();
const stopWorkMode = vi.fn();
const loadContacts = vi.fn();
const sendMessage = vi.fn();
const sendOpeningMessage = vi.fn();
const refreshMessagesCache = vi.fn();
const resetTaskAcquisition = vi.fn();
const downloadOrder = vi.fn();
const stopPolling = vi.fn();

vi.mock('@/stores/workMode', () => ({
  useWorkModeStore: () => ({
    loading: false,
    error: null,
    isActive: true,
    contacts: [{ id: 1 }],
    starredContacts: [{ id: 1 }],
    unreadContacts: [],
    isTaskAcquisition: false,
    currentOrder: null,
    startWorkMode,
    stopWorkMode,
    loadContacts,
    sendMessage,
    sendOpeningMessage,
    refreshMessagesCache,
    resetTaskAcquisition,
    downloadOrder,
    stopPolling,
  }),
}));

import { useWorkMode } from './useWorkMode';

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useWorkMode', () => {
  it('exposes store state via computed refs', () => {
    const wm = useWorkMode();
    expect(wm.isActive.value).toBe(true);
    expect(wm.contacts.value).toHaveLength(1);
    expect(wm.starredContacts.value).toHaveLength(1);
  });

  it('delegates actions to store', async () => {
    const wm = useWorkMode();
    await wm.startWorkMode();
    await wm.loadContacts();
    await wm.sendMessage(1, 'hi');
    await wm.sendOpeningMessage(1);
    await wm.refreshMessages();
    wm.resetTaskAcquisition();
    await wm.downloadOrder(9);
    await wm.stopWorkMode();
    expect(startWorkMode).toHaveBeenCalled();
    expect(loadContacts).toHaveBeenCalled();
    expect(sendMessage).toHaveBeenCalledWith(1, 'hi');
    expect(sendOpeningMessage).toHaveBeenCalledWith(1);
    expect(refreshMessagesCache).toHaveBeenCalled();
    expect(resetTaskAcquisition).toHaveBeenCalled();
    expect(downloadOrder).toHaveBeenCalledWith(9);
    expect(stopWorkMode).toHaveBeenCalled();
  });
});
