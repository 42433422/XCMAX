import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('./core', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status: number;
    data: unknown;
    constructor(message: string, status = 500, data: unknown = null) {
      super(message);
      this.status = status;
      this.data = data;
    }
  },
}));

vi.mock('@/utils/erpDomainPaths', () => ({
  resolveErpApiPath: (p: string) => p,
}));

import { api, ApiError } from './core';
import { wechatApi } from './wechat';

describe('wechatApi', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    vi.mocked(api.post).mockReset();
    vi.mocked(api.put).mockReset();
    vi.mocked(api.delete).mockReset();
  });

  it('getTasks calls ERP tasks endpoint', async () => {
    vi.mocked(api.get).mockResolvedValue({ success: true, data: [] });
    await wechatApi.getTasks({ status: 'open' });
    expect(api.get).toHaveBeenCalledWith('/api/wechat/tasks', { status: 'open' });
  });

  it('getContacts passes query params', async () => {
    vi.mocked(api.get).mockResolvedValue({ success: true, data: [] });
    await wechatApi.getContacts({ starred: true });
    expect(api.get).toHaveBeenCalledWith('/api/wechat/contacts', { starred: true });
  });

  it('sendMessage posts payload', async () => {
    vi.mocked(api.post).mockResolvedValue({ success: true });
    await wechatApi.sendMessage('wx-1', 'hello');
    expect(api.post).toHaveBeenCalledWith('/api/wechat_contacts/send_message', {
      contact_name: 'wx-1',
      message: 'hello',
    });
  });

  it('searchContacts returns empty for blank query', async () => {
    const res = await wechatApi.searchContacts('   ');
    expect(res.success).toBe(true);
    expect(res.data).toEqual([]);
    expect(api.get).not.toHaveBeenCalled();
  });

  it('ensureContactCache treats no-source 404 as skipped success', async () => {
    vi.mocked(api.get).mockRejectedValue(
      new ApiError('未找到可导入的联系人源', 404, { message: '未找到可导入的联系人源' }),
    );
    const res = await wechatApi.ensureContactCache();
    expect(res.success).toBe(true);
    expect(res.data).toEqual({ skipped: true });
  });

  it('ensureContactCache falls back to POST on 405', async () => {
    vi.mocked(api.get).mockRejectedValue(new ApiError('method', 405));
    vi.mocked(api.post)
      .mockRejectedValueOnce(new ApiError('post fail', 405))
      .mockResolvedValueOnce({ success: true, data: { refreshed: true } });
    const res = await wechatApi.ensureContactCache();
    expect(res.data).toEqual({ refreshed: true });
    expect(api.post).toHaveBeenCalledWith('/api/wechat_contacts/refresh_contact_cache', {});
  });

  it('autoConfigure tries alternate paths after 404', async () => {
    vi.mocked(api.post)
      .mockRejectedValueOnce(new ApiError('a', 404))
      .mockRejectedValueOnce(new ApiError('b', 404))
      .mockResolvedValueOnce({ success: true, configured: true });
    const res = await wechatApi.autoConfigure();
    expect(res).toEqual({ success: true, configured: true });
    expect(api.post).toHaveBeenCalledTimes(3);
  });

  it('autoConfigure throws when every candidate is 404', async () => {
    vi.mocked(api.post).mockRejectedValue(new ApiError('missing', 404));
    await expect(wechatApi.autoConfigure()).rejects.toBeInstanceOf(ApiError);
  });

  it('addContact rejects invalid payload via schema', () => {
    expect(() => wechatApi.addContact({} as never)).toThrow();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('confirmTask and ignoreTask post to task endpoints', async () => {
    vi.mocked(api.post).mockResolvedValue({ success: true });
    await wechatApi.confirmTask(42);
    await wechatApi.ignoreTask('99');
    expect(api.post).toHaveBeenCalledWith('/api/wechat/task/42/confirm');
    expect(api.post).toHaveBeenCalledWith('/api/wechat/task/99/ignore');
  });

  it('getContact updateContact deleteContact use REST paths', async () => {
    vi.mocked(api.get).mockResolvedValue({ success: true, data: { id: 1 } });
    vi.mocked(api.put).mockResolvedValue({ success: true, data: { id: 1 } });
    vi.mocked(api.delete).mockResolvedValue({ success: true });
    await wechatApi.getContact(1);
    await wechatApi.updateContact(1, { contact_name: 'A' });
    await wechatApi.deleteContact(1);
    expect(api.get).toHaveBeenCalledWith('/api/wechat/contacts/1');
    expect(api.put).toHaveBeenCalledWith('/api/wechat/contacts/1', { contact_name: 'A' });
    expect(api.delete).toHaveBeenCalledWith('/api/wechat/contacts/1');
  });

  it('scanMessages and getStarredContacts hit expected endpoints', async () => {
    vi.mocked(api.post).mockResolvedValue({ success: true, data: { scanned: 1 } });
    vi.mocked(api.get).mockResolvedValue({ success: true, data: [] });
    await wechatApi.scanMessages();
    await wechatApi.getStarredContacts({ keyword: '群', limit: 10, type: 'group' });
    expect(api.post).toHaveBeenCalledWith('/api/wechat/scan');
    expect(api.get).toHaveBeenCalledWith('/api/wechat/contacts', {
      starred: 'true',
      limit: 10,
      type: 'group',
      keyword: '群',
    });
  });

  it('ensureContactCache returns GET result on success', async () => {
    vi.mocked(api.get).mockResolvedValue({ success: true, data: { refreshed: true } });
    const res = await wechatApi.ensureContactCache();
    expect(res.data).toEqual({ refreshed: true });
  });

  it('ensureContactCache POST no-source 404 returns skipped', async () => {
    vi.mocked(api.get).mockRejectedValue(new ApiError('missing', 404));
    vi.mocked(api.post).mockRejectedValue(
      new ApiError('no db', 404, { message: '未找到可导入的联系人源 contact.db' }),
    );
    const res = await wechatApi.ensureContactCache();
    expect(res.data).toEqual({ skipped: true });
  });

  it('searchContacts maps primary API rows to results', async () => {
    vi.mocked(api.get).mockResolvedValue({
      success: true,
      data: [
        {
          id: 7,
          contact_name: 'Alice',
          wechat_id: 'wx-alice',
          remark: 'vip',
          contact_type: 'friend',
          is_starred: true,
        },
      ],
    });
    const res = await wechatApi.searchContacts('ali');
    expect(res.results?.[0]).toMatchObject({
      id: 7,
      display_name: 'Alice',
      username: 'wx-alice',
      already_starred: true,
    });
  });

  it('searchContacts falls back to legacy endpoint when primary returns empty', async () => {
    vi.mocked(api.get)
      .mockResolvedValueOnce({ success: true, data: [] })
      .mockResolvedValueOnce({ success: true, data: [{ id: 2, name: 'Bob' }] });
    const res = await wechatApi.searchContacts('bob');
    expect(api.get).toHaveBeenLastCalledWith('/api/wechat_contacts/search', { q: 'bob' });
    expect(res.data).toEqual([{ id: 2, name: 'Bob' }]);
  });

  it('searchContacts falls back when primary GET throws', async () => {
    vi.mocked(api.get)
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValueOnce({ success: true, data: [] });
    await wechatApi.searchContacts('x');
    expect(api.get).toHaveBeenLastCalledWith('/api/wechat_contacts/search', { q: 'x' });
  });

  it('addStarredContact stars by contact id when provided', async () => {
    vi.mocked(api.post).mockResolvedValue({ success: true, data: { id: 3 } });
    await wechatApi.addStarredContact({ id: 3, contact_name: 'C' });
    expect(api.post).toHaveBeenCalledWith('/api/wechat/contacts/3/star', { starred: true });
  });

  it('addStarredContact resolves hit from search then stars', async () => {
    vi.mocked(api.get).mockResolvedValue({
      success: true,
      data: [{ id: 9, contact_name: 'Target', wechat_id: 'wx-target' }],
    });
    vi.mocked(api.post).mockResolvedValue({ success: true });
    await wechatApi.addStarredContact({ wechat_id: 'wx-target', contact_name: 'Target' });
    expect(api.post).toHaveBeenCalledWith('/api/wechat/contacts/9/star', { starred: true });
  });

  it('addStarredContact creates contact when search misses', async () => {
    vi.mocked(api.get)
      .mockResolvedValueOnce({ success: true, data: [] })
      .mockResolvedValueOnce({ success: true, data: [] });
    vi.mocked(api.post).mockResolvedValue({ success: true });
    await wechatApi.addStarredContact({ contact_name: 'New', wechat_id: 'wx-new' });
    expect(api.post).toHaveBeenLastCalledWith('/api/wechat/contacts', {
      contact_name: 'New',
      wechat_id: 'wx-new',
      is_starred: true,
    });
  });

  it('starred contact helpers and refresh endpoints', async () => {
    vi.mocked(api.put).mockResolvedValue({ success: true });
    vi.mocked(api.post).mockResolvedValue({ success: true });
    vi.mocked(api.get).mockResolvedValue({ success: true, data: {} });
    await wechatApi.updateStarredContact(1, { contact_name: 'Z' });
    await wechatApi.deleteStarredContact(1);
    await wechatApi.unstarAllContacts();
    await wechatApi.getStarredContactContext(1);
    await wechatApi.refreshContactMessages(2, { limit: 20, force_live_refresh: true });
    await wechatApi.refreshMessagesCache();
    await wechatApi.refreshContactCache();
    expect(api.post).toHaveBeenCalledWith('/api/wechat/contacts/1/star', { starred: false });
    expect(api.post).toHaveBeenCalledWith('/api/wechat/contacts/unstar-all', {});
    expect(api.post).toHaveBeenCalledWith('/api/wechat_contacts/2/refresh_messages', {
      limit: 20,
      force_live_refresh: true,
    });
  });

  it('openChat posts contact_name payload', async () => {
    vi.mocked(api.post).mockResolvedValue({ success: true });
    await wechatApi.openChat('联系人');
    expect(api.post).toHaveBeenCalledWith('/api/wechat_contacts/open_chat', {
      contact_name: '联系人',
    });
  });

  it('autoConfigure rethrows non-404 errors immediately', async () => {
    vi.mocked(api.post).mockRejectedValue(new ApiError('server', 500));
    await expect(wechatApi.autoConfigure()).rejects.toMatchObject({ status: 500 });
    expect(api.post).toHaveBeenCalledTimes(1);
  });

  it('getContactContext uses context subpath', async () => {
    vi.mocked(api.get).mockResolvedValue({ success: true, data: { messages: [] } });
    await wechatApi.getContactContext(5);
    expect(api.get).toHaveBeenCalledWith('/api/wechat/contacts/5/context');
  });

  it('searchContacts maps name fallback when contact_name missing', async () => {
    vi.mocked(api.get).mockResolvedValue({
      success: true,
      data: [{ id: 1, name: 'Bob', wechat_id: 'wx-bob' }],
    });
    const res = await wechatApi.searchContacts('bob');
    expect(res.results?.[0]?.display_name).toBe('Bob');
  });

  it('getStarredContacts uses default limit and type', async () => {
    vi.mocked(api.get).mockResolvedValue({ success: true, data: [] });
    await wechatApi.getStarredContacts();
    expect(api.get).toHaveBeenCalledWith('/api/wechat/contacts', {
      starred: 'true',
      limit: 200,
      type: 'all',
    });
  });

  it('ensureContactCache rethrows non-404 errors', async () => {
    vi.mocked(api.get).mockRejectedValue(new ApiError('server', 500));
    await expect(wechatApi.ensureContactCache()).rejects.toMatchObject({ status: 500 });
  });

  it('ensureContactCache POST fallback succeeds on ensure path', async () => {
    vi.mocked(api.get).mockRejectedValue(new ApiError('missing', 404));
    vi.mocked(api.post).mockResolvedValueOnce({ success: true, data: { cached: true } });
    const res = await wechatApi.ensureContactCache();
    expect(res.data).toEqual({ cached: true });
    expect(api.post).toHaveBeenCalledWith('/api/wechat_contacts/ensure_contact_cache', {});
  });

  it('ensureContactCache propagates POST errors that are not cache fallbacks', async () => {
    vi.mocked(api.get).mockRejectedValue(new ApiError('missing', 404));
    vi.mocked(api.post).mockRejectedValue(new ApiError('db locked', 500));
    await expect(wechatApi.ensureContactCache()).rejects.toMatchObject({ status: 500 });
  });

  it('ensureContactCache treats Name2Id 404 message as skipped', async () => {
    vi.mocked(api.get).mockRejectedValue(
      new ApiError('missing', 404, { message: 'Name2Id mapping unavailable' }),
    );
    const res = await wechatApi.ensureContactCache();
    expect(res.data).toEqual({ skipped: true });
  });

  it('addStarredContact stars by contact_id field', async () => {
    vi.mocked(api.post).mockResolvedValue({ success: true });
    await wechatApi.addStarredContact({ contact_id: 11, contact_name: 'Star' });
    expect(api.post).toHaveBeenCalledWith('/api/wechat/contacts/11/star', { starred: true });
  });

  it('addStarredContact matches search hit by display name substring', async () => {
    vi.mocked(api.get).mockResolvedValue({
      success: true,
      data: [{ id: 4, contact_name: 'Team Alpha', wechat_id: 'wx-other' }],
    });
    vi.mocked(api.post).mockResolvedValue({ success: true });
    await wechatApi.addStarredContact({ display_name: 'Alpha' });
    expect(api.post).toHaveBeenCalledWith('/api/wechat/contacts/4/star', { starred: true });
  });

  it('updateContact rejects invalid payload via schema', () => {
    expect(() => wechatApi.updateContact(1, {} as never)).toThrow();
    expect(api.put).not.toHaveBeenCalled();
  });

  it('autoConfigure uses force_key_scan option', async () => {
    vi.mocked(api.post).mockResolvedValue({ success: true });
    await wechatApi.autoConfigure({ force_key_scan: true });
    expect(api.post).toHaveBeenCalledWith(
      '/api/wechat_contacts/auto_configure',
      { force_key_scan: true },
    );
  });

  it('refreshContactMessages uses default options', async () => {
    vi.mocked(api.post).mockResolvedValue({ success: true });
    await wechatApi.refreshContactMessages(3);
    expect(api.post).toHaveBeenCalledWith('/api/wechat_contacts/3/refresh_messages', {
      limit: 80,
      force_live_refresh: false,
    });
  });

  it('addStarredContact searches by username when wechat_id is absent', async () => {
    vi.mocked(api.get).mockResolvedValue({
      success: true,
      data: [{ id: 15, contact_name: 'User', wechat_id: 'wx-user' }],
    });
    vi.mocked(api.post).mockResolvedValue({ success: true });
    await wechatApi.addStarredContact({ username: 'wx-user', contact_name: 'User' });
    expect(api.get).toHaveBeenCalledWith('/api/wechat/contacts', {
      keyword: 'wx-user',
      type: 'all',
      starred: 'false',
      limit: 50,
    });
    expect(api.post).toHaveBeenCalledWith('/api/wechat/contacts/15/star', { starred: true });
  });

  it('addStarredContact creates starred contact when search finds no hit', async () => {
    vi.mocked(api.get)
      .mockResolvedValueOnce({ success: true, data: [] })
      .mockResolvedValueOnce({ success: true, data: [] });
    vi.mocked(api.post).mockResolvedValue({ success: true });
    await wechatApi.addStarredContact({ contact_name: 'OnlyName' });
    expect(api.post).toHaveBeenLastCalledWith('/api/wechat/contacts', {
      contact_name: 'OnlyName',
      is_starred: true,
    });
  });

  it('searchContacts treats non-array data as empty before legacy fallback', async () => {
    vi.mocked(api.get)
      .mockResolvedValueOnce({ success: true, data: null })
      .mockResolvedValueOnce({ success: true, data: [{ id: 1, name: 'Legacy' }] });
    const res = await wechatApi.searchContacts('legacy');
    expect(api.get).toHaveBeenLastCalledWith('/api/wechat_contacts/search', { q: 'legacy' });
    expect(res.data).toEqual([{ id: 1, name: 'Legacy' }]);
  });

  it('ensureContactCache treats contact.db 404 message as skipped on POST', async () => {
    vi.mocked(api.get).mockRejectedValue(new ApiError('missing', 404));
    vi.mocked(api.post).mockRejectedValue(
      new ApiError('db', 404, { message: 'contact.db not readable' }),
    );
    const res = await wechatApi.ensureContactCache();
    expect(res.data).toEqual({ skipped: true });
  });

  it('autoConfigure skips duplicate candidate paths', async () => {
    vi.mocked(api.post).mockResolvedValue({ success: true, configured: true });
    await wechatApi.autoConfigure();
    const paths = vi.mocked(api.post).mock.calls.map((call) => call[0]);
    expect(new Set(paths).size).toBe(paths.length);
  });

  it('getTasks uses empty params by default', async () => {
    vi.mocked(api.get).mockResolvedValue({ success: true, data: [] });
    await wechatApi.getTasks();
    expect(api.get).toHaveBeenCalledWith('/api/wechat/tasks', {});
  });

  it('getContacts uses empty params by default', async () => {
    vi.mocked(api.get).mockResolvedValue({ success: true, data: [] });
    await wechatApi.getContacts();
    expect(api.get).toHaveBeenCalledWith('/api/wechat/contacts', {});
  });

  it('searchContacts passes keyword query params to primary endpoint', async () => {
    vi.mocked(api.get).mockResolvedValue({ success: true, data: [] });
    await wechatApi.searchContacts('keyword');
    expect(api.get).toHaveBeenCalledWith('/api/wechat/contacts', {
      keyword: 'keyword',
      type: 'all',
      starred: 'false',
      limit: 50,
    });
  });

  it('ensureContactCache treats no-source message on ApiError.message field', async () => {
    vi.mocked(api.get).mockRejectedValue(
      new ApiError('未找到可导入的联系人源', 404, null),
    );
    const res = await wechatApi.ensureContactCache();
    expect(res.data).toEqual({ skipped: true });
  });

  it('autoConfigure tries all unique candidates on repeated 405 responses', async () => {
    vi.mocked(api.post).mockRejectedValue(new ApiError('method not allowed', 405));
    await expect(wechatApi.autoConfigure()).rejects.toMatchObject({ status: 405 });
    expect(api.post).toHaveBeenCalledTimes(3);
  });

  it('autoConfigure succeeds on last unique candidate path', async () => {
    vi.mocked(api.post)
      .mockRejectedValueOnce(new ApiError('a', 404))
      .mockRejectedValueOnce(new ApiError('b', 404))
      .mockResolvedValueOnce({ success: true, configured: true, path: 'mod' });
    const res = await wechatApi.autoConfigure({ force_key_scan: false });
    expect(res).toMatchObject({ success: true, configured: true });
    expect(api.post).toHaveBeenLastCalledWith(
      '/api/mod/private-db-read-assistant/wechat/auto_configure',
      { force_key_scan: false },
    );
  });

  it('addStarredContact skips search when neither id nor searchable fields exist', async () => {
    vi.mocked(api.post).mockResolvedValue({ success: true, data: { id: 1 } });
    await wechatApi.addStarredContact({ contact_name: '   ', wechat_id: '  ' });
    expect(api.get).not.toHaveBeenCalled();
    expect(api.post).toHaveBeenCalledWith('/api/wechat/contacts', {
      contact_name: '   ',
      wechat_id: '  ',
      is_starred: true,
    });
  });

  it('deleteStarredContact unstars via star endpoint', async () => {
    vi.mocked(api.post).mockResolvedValue({ success: true });
    await wechatApi.deleteStarredContact(88);
    expect(api.post).toHaveBeenCalledWith('/api/wechat/contacts/88/star', { starred: false });
  });

  it('refreshMessagesCache and refreshContactCache post empty bodies', async () => {
    vi.mocked(api.post).mockResolvedValue({ success: true, data: { refreshed: true } });
    await wechatApi.refreshMessagesCache();
    await wechatApi.refreshContactCache();
    expect(api.post).toHaveBeenCalledWith('/api/wechat_contacts/refresh_messages_cache', {});
    expect(api.post).toHaveBeenCalledWith('/api/wechat_contacts/refresh_contact_cache', {});
  });

  it('ensureContactCache rethrows non-ApiError failures from GET', async () => {
    vi.mocked(api.get).mockRejectedValue(new Error('network down'));
    await expect(wechatApi.ensureContactCache()).rejects.toThrow('network down');
  });

  it('addContact validates payload before POST', async () => {
    vi.mocked(api.post).mockResolvedValue({ success: true, data: { id: 1 } });
    await wechatApi.addContact({ contact_name: 'Valid', wechat_id: 'wx-1' });
    expect(api.post).toHaveBeenCalledWith('/api/wechat/contacts', {
      contact_name: 'Valid',
      wechat_id: 'wx-1',
    });
  });

  it('sendMessage and openChat use erp-prefixed paths', async () => {
    vi.mocked(api.post).mockResolvedValue({ success: true });
    await wechatApi.sendMessage('Bob', 'hi');
    await wechatApi.openChat('Bob');
    expect(api.post).toHaveBeenCalledWith('/api/wechat_contacts/send_message', {
      contact_name: 'Bob',
      message: 'hi',
    });
    expect(api.post).toHaveBeenCalledWith('/api/wechat_contacts/open_chat', {
      contact_name: 'Bob',
    });
  });

  it('getStarredContacts forwards keyword param when provided', async () => {
    vi.mocked(api.get).mockResolvedValue({ success: true, data: [] });
    await wechatApi.getStarredContacts({ keyword: 'vip', limit: 5, type: 'friend' });
    expect(api.get).toHaveBeenCalledWith('/api/wechat/contacts', {
      starred: 'true',
      limit: 5,
      type: 'friend',
      keyword: 'vip',
    });
  });

  it('updateStarredContact puts contact payload', async () => {
    vi.mocked(api.put).mockResolvedValue({ success: true, data: { id: 3 } });
    await wechatApi.updateStarredContact(3, { contact_name: 'Renamed', wechat_id: 'wx-3' });
    expect(api.put).toHaveBeenCalledWith('/api/wechat/contacts/3', {
      contact_name: 'Renamed',
      wechat_id: 'wx-3',
    });
  });

  it('ensureContactCache GET 405 falls back to POST ensure path', async () => {
    vi.mocked(api.get).mockRejectedValue(new ApiError('method', 405));
    vi.mocked(api.post).mockResolvedValue({ success: true, data: { cached: true } });
    const res = await wechatApi.ensureContactCache();
    expect(res.data).toEqual({ cached: true });
    expect(api.post).toHaveBeenCalledWith('/api/wechat_contacts/ensure_contact_cache', {});
  });

  it('searchContacts maps username from wechat_id when contact_name is missing', async () => {
    vi.mocked(api.get).mockResolvedValue({
      success: true,
      data: [{ id: 2, wechat_id: 'wx-only', contact_type: 'friend' }],
    });
    const res = await wechatApi.searchContacts('wx-only');
    expect(res.results?.[0]).toMatchObject({
      username: 'wx-only',
      already_starred: false,
    });
  });

  it('addStarredContact prefers id over contact_id when both present', async () => {
    vi.mocked(api.post).mockResolvedValue({ success: true });
    await wechatApi.addStarredContact({
      id: 99,
      contact_id: 12,
      contact_name: 'Pick id',
    } as never);
    expect(api.post).toHaveBeenCalledWith('/api/wechat/contacts/99/star', { starred: true });
  });

  it('exports default wechatApi alias', async () => {
    const mod = await import('./wechat');
    expect(mod.default).toBe(wechatApi);
  });

  it('searchContacts maps remark and starred flag on primary hits', async () => {
    vi.mocked(api.get).mockResolvedValue({
      success: true,
      data: [
        {
          id: 3,
          contact_name: 'VIP',
          wechat_id: 'wx-vip',
          remark: '重要客户',
          is_starred: true,
        },
      ],
    });
    const res = await wechatApi.searchContacts('vip');
    expect(res.results?.[0]).toMatchObject({
      display_name: 'VIP',
      remark: '重要客户',
      already_starred: true,
    });
  });

  it('ensureContactCache GET generic 404 without no-source message uses POST fallback', async () => {
    vi.mocked(api.get).mockRejectedValue(new ApiError('missing endpoint', 404));
    vi.mocked(api.post).mockResolvedValue({ success: true, data: { cached: true } });
    const res = await wechatApi.ensureContactCache();
    expect(res.data).toEqual({ cached: true });
    expect(api.post).toHaveBeenCalledWith('/api/wechat_contacts/ensure_contact_cache', {});
  });

  it('autoConfigure throws default message when no candidate succeeds without ApiError', async () => {
    vi.mocked(api.post).mockRejectedValue(new Error('network down'));
    await expect(wechatApi.autoConfigure()).rejects.toThrow('network down');
  });

  it('searchContacts trims whitespace before querying primary endpoint', async () => {
    vi.mocked(api.get).mockResolvedValue({ success: true, data: [] });
    await wechatApi.searchContacts('  keyword  ');
    expect(api.get).toHaveBeenCalledWith('/api/wechat/contacts', {
      keyword: 'keyword',
      type: 'all',
      starred: 'false',
      limit: 50,
    });
  });

  it('addStarredContact matches search hit by name field', async () => {
    vi.mocked(api.get).mockResolvedValue({
      success: true,
      data: [{ id: 6, name: 'NickOnly', wechat_id: 'wx-nick' }],
    });
    vi.mocked(api.post).mockResolvedValue({ success: true });
    await wechatApi.addStarredContact({ name: 'NickOnly' });
    expect(api.post).toHaveBeenCalledWith('/api/wechat/contacts/6/star', { starred: true });
  });

  it('ensureContactCache POST ensure 404 falls back to refresh endpoint', async () => {
    vi.mocked(api.get).mockRejectedValue(new ApiError('missing', 404));
    vi.mocked(api.post)
      .mockRejectedValueOnce(new ApiError('ensure missing', 404))
      .mockResolvedValueOnce({ success: true, data: { refreshed: true } });
    const res = await wechatApi.ensureContactCache();
    expect(res.data).toEqual({ refreshed: true });
    expect(api.post).toHaveBeenLastCalledWith('/api/wechat_contacts/refresh_contact_cache', {});
  });

  it('unstarAllContacts posts to unstar-all endpoint', async () => {
    vi.mocked(api.post).mockResolvedValue({ success: true, data: { count: 3 } });
    await wechatApi.unstarAllContacts();
    expect(api.post).toHaveBeenCalledWith('/api/wechat/contacts/unstar-all', {});
  });

  it('getStarredContactContext uses starred contact context path', async () => {
    vi.mocked(api.get).mockResolvedValue({ success: true, data: { messages: [] } });
    await wechatApi.getStarredContactContext(12);
    expect(api.get).toHaveBeenCalledWith('/api/wechat/contacts/12/context');
  });

  it('searchContacts maps contact_type on primary hits', async () => {
    vi.mocked(api.get).mockResolvedValue({
      success: true,
      data: [{ id: 8, contact_name: 'Group', contact_type: 'group', wechat_id: 'wx-group' }],
    });
    const res = await wechatApi.searchContacts('group');
    expect(res.results?.[0]?.contact_type).toBe('group');
  });

  it('autoConfigure throws default ApiError when every candidate returns non-ApiError', async () => {
    vi.mocked(api.post).mockRejectedValue(new TypeError('fetch failed'));
    await expect(wechatApi.autoConfigure()).rejects.toThrow('fetch failed');
    expect(api.post).toHaveBeenCalledTimes(1);
  });

  it('autoConfigure throws last 404 ApiError after exhausting unique candidates', async () => {
    vi.mocked(api.post).mockRejectedValue(new ApiError('missing', 404));
    await expect(wechatApi.autoConfigure()).rejects.toMatchObject({ status: 404 });
    expect(api.post).toHaveBeenCalledTimes(3);
  });
});
