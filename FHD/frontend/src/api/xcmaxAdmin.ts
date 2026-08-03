import api from './core';

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
  };
  update_hub: {
    version?: string;
    git_sha?: string;
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
  status: 'pending' | 'running' | 'done' | 'error' | string;
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

export type CurrentEntitlementsSyncStatus = {
  has_snapshot: boolean;
  updated_at_ms: number;
  account?: {
    market_user_id?: number | string | null;
    username?: string;
    account_kind?: string;
    market_is_enterprise?: boolean;
    market_is_admin?: boolean;
  } | null;
  snapshot?: {
    market_user_id?: string;
    username?: string;
    email?: string;
    is_admin?: boolean;
    is_enterprise?: boolean;
    profile?: {
      tier?: string;
      industry_id?: string;
      account_tier?: string;
      budget_range?: string;
      entitled_industries?: string[];
    };
    mod_ids?: string[];
    wallet?: Record<string, unknown> | null;
    meta?: {
      updated_at_ms?: number;
      target?: string;
      push_mode?: string;
    };
  } | null;
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
  getUserPrivateDelivery(userId: number) {
    return api.get(`/api/xcmax/admin/market/users/${userId}/private-delivery`);
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
  pullSync() {
    return api.post<{ data?: { pull?: Record<string, unknown>; apply?: Record<string, unknown> } }>(
      '/api/xcmax/sync/pull',
      {},
    );
  },
  getCurrentEntitlementsSyncStatus() {
    return api.get<{ data?: CurrentEntitlementsSyncStatus; message?: string }>(
      '/api/xcmax/sync/entitlements/current',
    );
  },
  startImpersonate(marketUserId: number, username: string) {
    return api.post('/api/xcmax/admin/impersonate', {
      market_user_id: marketUserId,
      username,
    });
  },
  activateEnterpriseImpersonation(bridgeToken: string) {
    return api.post('/api/xcmax/admin/impersonate/activate-enterprise', {
      bridge_token: bridgeToken,
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
};
