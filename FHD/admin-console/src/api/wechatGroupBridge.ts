import api from '@/api/core';

export type WechatGroupSyncBody = {
  market_user_id?: number;
  force_refresh?: boolean;
  message_limit?: number;
  group_limit?: number;
};

export const wechatGroupBridgeApi = {
  syncGroups(body: WechatGroupSyncBody = {}) {
    return api.post<Record<string, unknown>>('/api/wechat/groups/sync', body);
  },

  getContactContext(contactId: string | number, opts: { refresh?: boolean } = {}) {
    return api.get<{
      success?: boolean;
      messages?: unknown[];
      data?: unknown;
      count?: number;
    }>(`/api/wechat/contacts/${contactId}/context`, {
      refresh: opts.refresh ?? false,
    });
  },

  loadStarredGroupFeed(
    marketUserId: number,
    limit: number,
    opts: { sync?: boolean } = {},
  ) {
    return api.get<{ success?: boolean; data?: unknown[] }>('/api/wechat/starred-messages', {
      type: 'group',
      market_user_id: marketUserId,
      limit,
      sync: opts.sync ?? false,
    });
  },
};
