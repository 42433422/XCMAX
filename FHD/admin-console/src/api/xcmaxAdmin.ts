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

export interface AutonomyPendingAction {
  action_id: string;
  action: string;
  state: string;
  source: string;
  executor_name?: string;
  payload?: Record<string, unknown>;
  risk_decision?: {
    risk_level: string;
    decision: string;
    reason?: string;
    policy?: string;
    rollback_path?: string;
  };
  timestamp?: string;
  approval_id?: string;
  approval_requested_at?: string;
  admin_execution_ready?: boolean;
  execution_mode?: string;
  execution_guidance?: string;
}

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
  listOrders(params: { status?: string; limit?: number; offset?: number } = {}) {
    return api.get<{
      items?: Record<string, unknown>[];
      total?: number;
      summary?: {
        total_orders?: number;
        paid_orders?: number;
        pending_orders?: number;
        paid_revenue?: number;
        by_status?: Record<string, number>;
      };
      source?: string;
    }>('/api/xcmax/admin/market/orders', params);
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
  fetchPendingAutonomyActions() {
    return api.get<{ ok: boolean; count: number; items: AutonomyPendingAction[] }>(
      '/api/xcmax/admin/autonomy/actions/pending',
    );
  },
  resumeAutonomyAction(actionId: string, approvalId?: string) {
    return api.post<{ ok: boolean; execution_dispatched: boolean; action: AutonomyPendingAction }>(
      `/api/xcmax/admin/autonomy/actions/${encodeURIComponent(actionId)}/resume`,
      { approval_id: approvalId },
    );
  },
  rejectAutonomyAction(actionId: string, reason?: string, approvalId?: string) {
    return api.post<{ ok: boolean; action: AutonomyPendingAction }>(
      `/api/xcmax/admin/autonomy/actions/${encodeURIComponent(actionId)}/reject`,
      { reason, approval_id: approvalId },
    );
  },
  fetchAutonomyAuditLog(params: {
    limit?: number;
    days?: number;
    risk_level?: string;
    decision?: string;
    veto_only?: boolean;
  } = {}) {
    return api.get<{
      success?: boolean;
      items?: Record<string, unknown>[];
      count?: number;
      summary?: Record<string, unknown>;
    }>('/api/xcmax/admin/autonomy/audit-log', params);
  },
  fetchAutonomyHealth() {
    return api.get<{ ok: boolean; service?: string }>('/api/xcmax/admin/autonomy/health');
  },
  fetchAutonomyOverview() {
    return api.get<Record<string, unknown>>('/api/xcmax/admin/autonomy/overview');
  },
  fetchAutonomyDeployEvents(params: { limit?: number; since_cursor?: string } = {}) {
    return api.get<{ ok: boolean; items?: AutonomyDeployEvent[]; count?: number }>(
      '/api/xcmax/admin/autonomy/deploy-events',
      params,
    );
  },
  fetchAutonomyOperatingMetrics() {
    return api.get<Record<string, unknown>>('/api/xcmax/admin/autonomy/operating-metrics');
  },
  fetchAutonomyGithubItems(limit = 30) {
    return api.get<{ ok: boolean; items?: AutonomyGithubItem[]; errors?: string[] }>(
      '/api/xcmax/admin/autonomy/github-items',
      { limit },
    );
  },
  fetchAutonomyCrossTierGate() {
    return api.get<Record<string, unknown>>('/api/xcmax/admin/autonomy/cross-tier-gate');
  },
  fetchAutonomyAuditCrossTier(params: { tier?: string; limit?: number } = {}) {
    return api.get<{ ok: boolean; items?: Record<string, unknown>[]; tier?: string }>(
      '/api/xcmax/admin/autonomy/audit-cross-tier',
      params,
    );
  },
  forceSelfMaintenanceRun(reason = 'admin_console_force_run') {
    return api.post<{ ok: boolean; result?: Record<string, unknown>; message?: string }>(
      '/api/xcmax/admin/autonomy/self-maintenance/run',
      { reason },
    );
  },
};

export type AutonomyDeployEvent = {
  deploy_id?: string;
  deployed_at?: string;
  commit_at?: string;
  status?: string;
  restored_at?: string | null;
  source_workflow?: string;
  head_branch?: string;
};

export type AutonomyGithubItem = {
  kind?: string;
  number?: number;
  title?: string;
  url?: string;
  labels?: string[];
  updated_at?: string;
  author?: string;
  head_ref?: string;
};
