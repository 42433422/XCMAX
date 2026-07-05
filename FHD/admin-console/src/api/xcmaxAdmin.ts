import api from '@/api/core';

export type MarketAdminUser = {
  id: number;
  username: string;
  email?: string;
  is_admin?: boolean;
  is_enterprise?: boolean;
  company?: string;
};

export type DeployCheckData = {
  admin_local: {
    version?: string;
    git_sha?: string;
    packed_git_sha?: string | null;
  };
  update_hub: {
    version?: string | null;
    git_sha?: string | null;
    sha256?: string | null;
    built_at?: string | null;
    manifest_url?: string;
    reachable?: boolean;
  };
  enterprise: {
    reachable?: boolean;
    version?: string;
    deploy_sha256?: string;
  };
  flags: {
    up_to_date?: boolean;
    enterprise_pending?: boolean;
    needs_push?: boolean;
    needs_pack?: boolean;
  };
};

export type DeployJobStep = {
  id: string;
  label: string;
  status: 'pending' | 'running' | 'done' | 'error' | 'skipped' | string;
  detail?: string;
};

export type DeployJobData = {
  job_id: string;
  status: 'queued' | 'running' | 'done' | 'error' | string;
  steps: DeployJobStep[];
  error?: string;
};

export type ForcePushUserEntitlementsPayload = {
  user: Partial<MarketAdminUser> & Record<string, unknown>;
  profile: {
    tier?: string;
    industry_id?: string;
    account_tier?: string;
    budget_range?: string;
    entitled_industries?: string[];
  };
  mod_ids?: string[];
  wallet?: Record<string, unknown> | null;
  workflow_employees?: Record<string, unknown>[];
  installed_mods?: Record<string, unknown>[];
};

export const xcmaxAdminApi = {
  listUsers() {
    return api.get('/api/xcmax/admin/market/users');
  },
  createMarketUser(payload: { username: string; password: string; email: string; verification_code?: string }) {
    return api.post('/api/xcmax/admin/market/users', payload);
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
    payload: {
      username: string;
      tier?: string;
      industry_id?: string;
      account_tier?: string;
      budget_range?: string;
      entitled_industries?: string[];
    },
  ) {
    return api.put(`/api/xcmax/admin/users/${userId}/profile`, payload);
  },
  listWallets(limit = 500, offset = 0) {
    return api.get('/api/xcmax/admin/market/wallets', { limit, offset });
  },
  creditWallet(userId: number, payload: { amount: number; description?: string }) {
    return api.post(`/api/xcmax/admin/market/users/${userId}/wallet/credit`, payload);
  },
  forcePushUserEntitlements(userId: number, payload: ForcePushUserEntitlementsPayload) {
    return api.post(`/api/xcmax/admin/market/users/${userId}/entitlements/push`, payload);
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
  checkDeployUpdates(channel?: string) {
    if (channel) {
      return api.get<{ data?: DeployCheckData; message?: string }>(
        '/api/xcmax/admin/deploy/check',
        { channel },
      );
    }
    return api.get<{ data?: DeployCheckData; message?: string }>('/api/xcmax/admin/deploy/check');
  },
  startDeployPush(body: Record<string, unknown>) {
    return api.post<{ data?: DeployJobData; message?: string }>(
      '/api/xcmax/admin/deploy/push',
      body,
    );
  },
  getDeployJob(jobId: string) {
    return api.get<{ data?: DeployJobData; message?: string }>(
      `/api/xcmax/admin/deploy/jobs/${encodeURIComponent(jobId)}`,
    );
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
