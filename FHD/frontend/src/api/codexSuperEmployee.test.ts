import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock('@/utils/apiBase', () => ({ apiFetch }));

import {
  fetchCodexSuperEmployeeMessages,
  sendCodexSuperEmployeeMessage,
} from './codexSuperEmployee';

function jsonRes(body: unknown, { status = 200, ct = 'application/json' } = {}) {
  return {
    status,
    headers: { get: () => ct },
    json: async () => body,
  } as unknown as Response;
}

beforeEach(() => {
  apiFetch.mockReset();
});

describe('codexSuperEmployee api', () => {
  it('fetches admin messages from admin endpoint', async () => {
    apiFetch.mockResolvedValueOnce(jsonRes({ success: true, messages: [{ id: 'm1' }] }));

    const messages = await fetchCodexSuperEmployeeMessages({ scope: 'admin' });

    expect(messages).toHaveLength(1);
    expect(apiFetch).toHaveBeenCalledWith(
      '/api/admin/codex-super-employee/messages',
      expect.anything(),
    );
  });

  it('unwraps mobile messages from mobile endpoint response data', async () => {
    apiFetch.mockResolvedValueOnce(
      jsonRes({ success: true, data: { messages: [{ id: 'm2' }] } }),
    );

    const messages = await fetchCodexSuperEmployeeMessages({ scope: 'mobile' });

    expect(messages[0]?.id).toBe('m2');
    expect(apiFetch).toHaveBeenCalledWith(
      '/api/mobile/v1/admin/codex-super-employee/messages',
      expect.anything(),
    );
  });

  it('sends mobile invocation and unwraps dispatch payload', async () => {
    apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: {
          dispatch: { request_id: 'req-1', status: 'accepted' },
          message: { id: 'user-1', role: 'user', body: 'run', created_at: '2026-06-19T00:00:00Z' },
          assistant_message: {
            id: 'dispatcher-1',
            role: 'system',
            kind: 'dispatcher',
            body: 'accepted',
            created_at: '2026-06-19T00:00:01Z',
          },
          messages: [{ id: 'user-1' }, { id: 'dispatcher-1' }],
        },
      }),
    );

    const result = await sendCodexSuperEmployeeMessage(
      'run',
      { source: 'mobile_im' },
      { scope: 'mobile' },
    );

    expect(result.dispatch?.status).toBe('accepted');
    expect(result.messages).toHaveLength(2);
    expect(apiFetch).toHaveBeenCalledWith(
      '/api/mobile/v1/admin/codex-super-employee/messages',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ message: 'run', context: { source: 'mobile_im' } }),
      }),
    );
  });
});
