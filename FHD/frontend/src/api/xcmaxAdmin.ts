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
  checkDeployUpdates() {
    return api.get<{ data?: DeployCheckData; message?: string }>(
      '/api/xcmax/admin/deploy/check',
    );
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
