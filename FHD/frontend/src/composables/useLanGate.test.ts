import { beforeEach, describe, expect, it, vi } from 'vitest';

const statusMock = vi.fn();
const logoutMock = vi.fn();

vi.mock('@/api/lanGate', () => ({
  lanGateApi: {
    status: () => statusMock(),
    logout: () => logoutMock(),
  },
}));

import { useLanGate } from './useLanGate';

const sampleStatus = {
  enabled: true,
  authorized: true,
  is_admin_host: false,
  is_admin: true,
  in_whitelist: true,
};

beforeEach(() => {
  statusMock.mockReset();
  logoutMock.mockReset();
  useLanGate().reset();
});

describe('useLanGate', () => {
  it('refresh fetches status and exposes computed flags', async () => {
    statusMock.mockResolvedValue(sampleStatus);
    const gate = useLanGate();
    const s = await gate.refresh(true);
    expect(s).toEqual(sampleStatus);
    expect(gate.enabled.value).toBe(true);
    expect(gate.authorized.value).toBe(true);
    expect(gate.isAdminKey.value).toBe(true);
    expect(gate.isReady.value).toBe(true);
  });

  it('refresh returns cached status within TTL', async () => {
    statusMock.mockResolvedValue(sampleStatus);
    const gate = useLanGate();
    await gate.refresh(true);
    statusMock.mockClear();
    const cached = await gate.refresh();
    expect(cached).toEqual(sampleStatus);
    expect(statusMock).not.toHaveBeenCalled();
  });

  it('logout clears status even when api fails', async () => {
    statusMock.mockResolvedValue(sampleStatus);
    logoutMock.mockRejectedValue(new Error('net'));
    const gate = useLanGate();
    await gate.refresh(true);
    await gate.logout();
    expect(gate.isReady.value).toBe(false);
  });

  it('modal open/dismiss tracks redirect path', () => {
    const gate = useLanGate();
    gate.openLanGateModal('/admin');
    expect(gate.modalVisible.value).toBe(true);
    expect(gate.modalRedirect.value).toBe('/admin');
    gate.dismissLanGateModal();
    expect(gate.modalVisible.value).toBe(false);
    expect(gate.modalRedirect.value).toBeNull();
  });
});
