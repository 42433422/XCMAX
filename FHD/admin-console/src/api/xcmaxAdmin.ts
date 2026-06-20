import api from '@/api/core';

export type MarketAdminUser = {
  id: number;
  username: string;
  email?: string;
  is_admin?: boolean;
  is_enterprise?: boolean;
  company?: string;
};

export const xcmaxAdminApi = {
  listUsers() {
    return api.get('/api/xcmax/admin/market/users');
  },
  listAssignableMods() {
    return api.get('/api/xcmax/admin/market/assignable-mods');
  },
  listUserMods(userId: number) {
    return api.get(`/api/xcmax/admin/market/users/${userId}/mods`);
  },
  bindUserMod(userId: number, modId: string) {
    return api.post(`/api/xcmax/admin/market/users/${userId}/mods/${encodeURIComponent(modId)}`, {});
  },
  unbindUserMod(userId: number, modId: string) {
    return api.delete(`/api/xcmax/admin/market/users/${userId}/mods/${encodeURIComponent(modId)}`);
  },
  setUserAdmin(userId: number, isAdmin: boolean) {
    return api.put(`/api/xcmax/admin/market/users/${userId}/admin?is_admin=${isAdmin}`);
  },
  setUserEnterprise(userId: number, isEnterprise: boolean) {
    return api.put(
      `/api/xcmax/admin/market/users/${userId}/enterprise?is_enterprise=${isEnterprise}`,
    );
  },
  getUserProfiles() {
    return api.get('/api/xcmax/admin/users/profiles');
  },
  setUserProfile(
    userId: number,
    payload: { username: string; tier?: string; industry_id?: string },
  ) {
    return api.put(`/api/xcmax/admin/users/${userId}/profile`, payload);
  },
  listWallets(limit = 500, offset = 0) {
    return api.get('/api/xcmax/admin/market/wallets', { limit, offset });
  },
  startImpersonate(marketUserId: number, username: string) {
    return api.post('/api/xcmax/admin/impersonate', {
      market_user_id: marketUserId,
      username,
    });
  },
  endImpersonate() {
    return api.post('/api/xcmax/admin/impersonate/end', {});
  },
  listWechatGroups(params: { keyword?: string; limit?: number } = {}) {
    return api.get('/api/xcmax/admin/wechat/groups', params);
  },
  getUserWechatBindings(userId: number) {
    return api.get(`/api/xcmax/admin/market/users/${userId}/wechat-customers`);
  },
  saveUserWechatBindings(userId: number, contactIds: number[]) {
    return api.put(`/api/xcmax/admin/market/users/${userId}/wechat-customers`, {
      contact_ids: contactIds,
    });
  },
};
