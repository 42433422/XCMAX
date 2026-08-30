import api from '@/api/core';
import type { DiagnosticTerminalResult } from './diagnosticTerminal';

export type { DiagnosticTerminalItem, DiagnosticTerminalResult } from './diagnosticTerminal';

export type MarketAdminUser = {
  id: number;
  username: string;
  email?: string;
  is_admin?: boolean;
  is_enterprise?: boolean;
  company?: string;
};

export type StandardDeliveryRecord = {
  delivery_no: string;
  delivery_type: 'standard_desktop' | string;
  status: 'pending_install' | 'pending_first_login' | 'completed' | string;
  status_label: string;
  started_at?: string;
  activated_at?: string;
  completed_at?: string;
  account: MarketAdminUser & {
    account_state?: string;
    first_login_at?: string;
    last_login_at?: string;
  };
  plan: {
    id: string;
    title: string;
    account_tier: 'normal' | 'pro' | 'max' | 'ultra' | string;
    license_type: 'permanent' | string;
    amount_cents?: number;
  };
  order?: {
    order_no?: string;
    status?: string;
    total_amount?: string;
    paid_at?: string;
    entitlement_id?: number | null;
  };
  install: {
    ok: boolean;
    installed_devices: number;
    customer_installed_devices?: number;
    internal_devices_excluded?: number;
    scope?: 'customer_external_desktop' | string;
    latest_receipt?: UpdateInstallReceipt | null;
  };
  first_login: { ok: boolean; at?: string };
  completion_rule: 'installed_and_first_login' | string;
  available_installers: string[];
};

export type StandardDeliveryPolicy = {
  id?: 'customer_external_desktop_delivery' | string;
  completion_rule?: 'customer_desktop_installed_and_first_login' | string;
  internal_device_exclusion_enabled?: boolean;
  internal_device_ids_configured?: number;
  login_only_counts_as_installation?: boolean;
};

export type EntitlementFastLanePlan = {
  id: string;
  title: string;
  description?: string;
  catalog: 'account_license' | 'membership' | string;
  license_type: 'permanent' | 'trial' | 'membership' | string;
  account_tier?: string;
  duration_days?: number;
  price?: string;
};

export type EntitlementFastLaneActivePlan = {
  user_plan_id: number;
  plan_id: string;
  title: string;
  catalog: 'account_license' | 'membership' | string;
  started_at?: string;
  expires_at?: string;
  auto_renew?: boolean;
};

export type EntitlementFastLaneResult = {
  ok?: boolean;
  duplicate?: boolean;
  action?: 'assign' | 'revoke' | string;
  account?: MarketAdminUser & { account_state?: string };
  active_plans?: EntitlementFastLaneActivePlan[];
  audit?: {
    idempotency_key?: string;
    actor_user_id?: number;
    actor_username?: string;
    aggregate_type?: string;
  };
  commerce?: {
    order_generated?: boolean;
    payment_generated?: boolean;
    transaction_generated?: boolean;
  };
};

export type CustomDeliveryArtifact = {
  kind: 'module' | 'employee' | string;
  id: string;
};

export type CustomDeliveryInstallReceipt = CustomDeliveryArtifact & {
  version?: string;
  host?: string;
  installed_at?: string;
};

export type CustomDeliveryRun = {
  attempt?: number;
  session_id?: string;
  status?: string;
  created_at?: string;
  error?: string;
  steps?: Array<Record<string, unknown>>;
  quality_report?: Record<string, unknown> | null;
  sandbox_report?: Record<string, unknown> | null;
  artifact?: Record<string, unknown> | null;
};

export type CustomDeliveryTicket = {
  id: number;
  user_id?: number;
  ticket_no?: string;
  title?: string;
  status?: string;
  priority?: string;
  created_at?: string;
  updated_at?: string;
  custom_delivery?: {
    kind?: string;
    requirements?: string;
    acceptance_criteria?: string;
    stage?: string;
    stage_label?: string;
    gate_ok?: boolean;
    gate_message?: string;
    acceptance_status?: string;
    pricing_mode?: 'initial_included' | 'post_delivery_addon' | 'legacy' | string;
    pricing_label?: string;
    included_in_purchase?: boolean;
    delivery_terms?: Record<string, unknown>;
    runs?: CustomDeliveryRun[];
    artifacts?: CustomDeliveryArtifact[];
    install_receipts?: CustomDeliveryInstallReceipt[];
    crm?: {
      assignment?: Record<string, unknown>;
      quote?: Record<string, unknown>;
      contract?: Record<string, unknown>;
      payment?: Record<string, unknown>;
    };
    commerce_ready?: boolean;
    commerce_blockers?: string[];
  };
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

export type UpdateInstallReceiptSummary = {
  reported_devices?: number;
  installed_devices?: number;
  failed_devices?: number;
  rolled_back_devices?: number;
};

export type UpdateInstallReceipt = {
  id?: number;
  user_id?: number;
  installation_id?: string;
  platform?: string;
  target_version?: string;
  target_build_sha?: string;
  installed_version?: string;
  installed_build_sha?: string;
  status?: 'installed' | 'failed' | 'rolled_back' | string;
  source?: string;
  device_scope?: 'internal' | 'customer' | string;
  error?: string;
  reported_at?: string;
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
  approver?: string;
  approved_at?: string;
  executed_at?: string;
  execution_failed_at?: string;
  rejected_at?: string;
  superseded_at?: string;
  superseded_by?: string;
  outcome?: Record<string, unknown>;
  admin_execution_ready?: boolean;
  execution_mode?: string;
  execution_guidance?: string;
}

export const xcmaxAdminApi = {
  listUsers(limit = 200, offset = 0, isEnterprise?: boolean) {
    const params: { limit: number; offset: number; is_enterprise?: boolean } = { limit, offset };
    if (typeof isEnterprise === 'boolean') params.is_enterprise = isEnterprise;
    return api.get<{ users?: MarketAdminUser[]; total?: number }>(
      '/api/xcmax/admin/market/users',
      params,
    );
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
  listCustomDeliveries(limit = 100) {
    return api.get<{ items?: CustomDeliveryTicket[] }>(
      '/api/xcmax/market-proxy/customer-service/custom-deliveries',
      { limit },
    );
  },
  listStandardDeliveries() {
    return api.get<{
      items?: StandardDeliveryRecord[];
      total?: number;
      summary?: {
        purchased_accounts?: number;
        pending_install?: number;
        pending_first_login?: number;
        completed?: number;
        customer_installed_devices?: number;
        internal_receipts_excluded?: number;
        internal_device_ids_configured?: number;
      };
      policy?: StandardDeliveryPolicy;
      ssot?: string;
    }>('/api/xcmax/admin/customer-deliveries/standard');
  },
  listEntitlementFastLanePlans() {
    return api.get<{
      items?: EntitlementFastLanePlan[];
      ssot?: string;
    }>('/api/xcmax/admin/market/entitlement-fast-lane/plans');
  },
  getEntitlementFastLaneAccount(account: string | number) {
    return api.get<EntitlementFastLaneResult>(
      `/api/xcmax/admin/market/entitlement-fast-lane/accounts/${encodeURIComponent(String(account))}`,
    );
  },
  mutateEntitlementFastLane(payload: {
    account: string;
    action: 'assign' | 'revoke';
    plan_id: string;
    reason: string;
    idempotency_key: string;
    duration_days?: number;
  }) {
    return api.post<EntitlementFastLaneResult>(
      '/api/xcmax/admin/market/entitlement-fast-lane/actions',
      payload,
    );
  },
  listDiagnosticTerminalCommands() {
    return api.get<{
      ok: boolean;
      read_only: boolean;
      items: Array<{ name: string; aliases: string[]; usage: string; description: string }>;
    }>('/api/xcmax/admin/market/diagnostic-terminal/commands');
  },
  executeDiagnosticTerminalCommand(command: string) {
    return api.post<DiagnosticTerminalResult>(
      '/api/xcmax/admin/market/diagnostic-terminal/execute',
      { command },
    );
  },
  decideCustomDelivery(ticketId: number, action: 'accept' | 'rework', note = '') {
    return api.post<CustomDeliveryTicket>(
      `/api/xcmax/market-proxy/customer-service/custom-deliveries/${ticketId}/decision`,
      { action, note },
    );
  },
  updateCustomDeliveryCrm(ticketId: number, payload: Record<string, unknown>) {
    return api.post<CustomDeliveryTicket>(
      `/api/xcmax/market-proxy/customer-service/custom-deliveries/${ticketId}/crm`,
      payload,
    );
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
    }>('/api/xcmax/admin/market/commerce/orders', params);
  },
  cancelOrder(orderNo: string, reason: string, idempotencyKey: string) {
    return api.post(`/api/xcmax/admin/market/commerce/orders/${encodeURIComponent(orderNo)}/cancel`, {
      reason,
      idempotency_key: idempotencyKey,
    });
  },
  repriceOrder(orderNo: string, newAmount: number, reason: string, idempotencyKey: string) {
    return api.post(`/api/xcmax/admin/market/commerce/orders/${encodeURIComponent(orderNo)}/reprice`, {
      new_amount: newAmount,
      reason,
      idempotency_key: idempotencyKey,
    });
  },
  requestOrderRefund(orderNo: string, reason: string, idempotencyKey: string) {
    return api.post(`/api/xcmax/admin/market/commerce/orders/${encodeURIComponent(orderNo)}/refund-request`, {
      reason,
      idempotency_key: idempotencyKey,
    });
  },
  listPendingRefunds() {
    return api.get<{ refunds?: Record<string, unknown>[]; total?: number }>(
      '/api/xcmax/admin/market/commerce/refunds/pending',
    );
  },
  reviewRefund(refundId: number, action: 'approve' | 'reject', adminNote = '') {
    return api.post(`/api/xcmax/admin/market/commerce/refunds/${refundId}/review`, {
      action,
      admin_note: adminNote,
    });
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
  listUpdateInstallReceipts(targetBuildSha = '') {
    return api.get<{
      items?: UpdateInstallReceipt[];
      summary?: UpdateInstallReceiptSummary;
    }>('/api/xcmax/admin/deploy/install-receipts', {
      ...(targetBuildSha ? { target_build_sha: targetBuildSha } : {}),
      limit: 500,
    });
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
    return api.get<{
      ok: boolean;
      count: number;
      items: AutonomyPendingAction[];
      summary?: {
        states?: Record<string, number>;
        execution_modes?: Record<string, number>;
        actionable?: number;
        waiting?: number;
      };
    }>(
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
