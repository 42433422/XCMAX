import { apiFetch } from '@/utils/apiBase';

export const LS_MARKET_ACCESS_TOKEN = 'xcagi_market_access_token';
export const LS_MARKET_USER_JSON = 'xcagi_market_user_json';

export type MarketUserProfile = {
  id?: number | string;
  username?: string;
  email?: string;
  phone?: string;
  is_admin?: boolean;
  experience?: number;
  level_profile?: Record<string, unknown>;
  created_at?: string;
};

export type MarketWalletOverview = {
  balance?: number;
  membership_reference_yuan?: number;
};

export type MarketMembershipOverview = {
  tier?: string;
  label?: string;
  is_member?: boolean;
  can_byok?: boolean;
};

export type MarketAccountOverviewData = {
  user: MarketUserProfile;
  market_base_url: string;
  wallet?: MarketWalletOverview;
  plan?: Record<string, unknown> | null;
  membership?: MarketMembershipOverview | null;
  quotas?: Array<Record<string, unknown>>;
};

export type MarketAccountSyncData = {
  user: MarketUserProfile;
  market_base_url: string;
};

export type MarketAuthResult = {
  token: string;
  market_base_url: string;
  raw?: Record<string, unknown>;
};

export type MarketLlmProvider = {
  provider: string;
  label?: string;
  models?: string[];
  models_detailed?: Array<Record<string, unknown>>;
  error?: string | null;
  fetch_source?: string | null;
};

export type MarketLlmCatalogData = {
  providers: MarketLlmProvider[];
  preferences?: Record<string, unknown>;
  cache_ttl_seconds?: number;
  market_base_url?: string;
};

export function normalizePastedAuthorization(raw: string): string {
  let t = (raw || '').trim();
  if (!t) return '';
  if (/^authorization:\s*/i.test(t)) {
    t = t.replace(/^authorization:\s*/i, '').trim();
  }
  return t;
}

function marketBearerHeaders(rawAuth: string): Record<string, string> {
  const normalized = normalizePastedAuthorization(rawAuth).trim();
  if (!normalized) return {};
  const v = normalized.toLowerCase().startsWith('bearer ') ? normalized : `Bearer ${normalized}`;
  return { Authorization: v };
}

export async function syncMarketAccount(authorization: string): Promise<MarketAccountSyncData> {
  const res = await apiFetch('/api/market/account-sync', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...marketBearerHeaders(authorization) },
    body: JSON.stringify({ authorization }),
  });
  const j = (await res.json()) as {
    success?: boolean;
    detail?: string;
    message?: string;
    data?: MarketAccountSyncData;
  };
  if (!j.success || !j.data) {
    throw new Error(j.detail || j.message || '账号同步失败');
  }
  return j.data;
}

export async function fetchMarketAccountOverview(authorization: string): Promise<MarketAccountOverviewData> {
  const res = await apiFetch('/api/market/account-overview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...marketBearerHeaders(authorization) },
    body: JSON.stringify({ authorization }),
  });
  const j = (await res.json()) as {
    success?: boolean;
    detail?: string;
    message?: string;
    data?: MarketAccountOverviewData;
  };
  if (!j.success || !j.data) {
    throw new Error(j.detail || j.message || '线上额度同步失败');
  }
  return j.data;
}

export async function fetchMarketLlmCatalog(
  authorization = '',
  refresh = false,
): Promise<MarketLlmCatalogData> {
  const p = new URLSearchParams();
  if (refresh) p.set('refresh', 'true');
  const res = await apiFetch(`/api/market/llm-catalog${p.toString() ? `?${p}` : ''}`, {
    headers: { ...marketBearerHeaders(authorization) },
  });
  const j = (await res.json()) as {
    success?: boolean;
    detail?: string;
    message?: string;
    data?: MarketLlmCatalogData;
  };
  if (!j.success || !j.data) {
    throw new Error(j.detail || j.message || '模型目录同步失败');
  }
  return j.data;
}

export async function fetchSessionMarketHandoff(): Promise<MarketAuthResult | null> {
  const res = await apiFetch('/api/market/session-handoff');
  const j = (await res.json()) as {
    success?: boolean;
    message?: string;
    data?: { market_access_token?: string; market_base_url?: string };
  };
  if (!res.ok || !j.success || !j.data?.market_access_token) {
    console.warn('[fetchSessionMarketHandoff] 返回无效: status=', res.status, 'success=', j.success, 'hasToken=', !!j.data?.market_access_token, 'message=', j.message);
    return null;
  }
  return {
    token: j.data.market_access_token.trim(),
    market_base_url: String(j.data.market_base_url || ''),
  };
}

export async function loginMarketAccount(username: string, password: string): Promise<MarketAuthResult> {
  const res = await apiFetch('/api/market/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  const j = (await res.json()) as {
    success?: boolean;
    detail?: string;
    message?: string;
    data?: MarketAuthResult;
  };
  if (!j.success || !j.data?.token) {
    throw new Error(j.detail || j.message || '市场登录失败');
  }
  return j.data;
}

export async function registerMarketAccount(
  username: string,
  password: string,
  email: string,
  verificationCode = '',
): Promise<MarketAuthResult> {
  const res = await apiFetch('/api/market/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      username,
      password,
      email,
      verification_code: verificationCode,
    }),
  });
  const j = (await res.json()) as {
    success?: boolean;
    detail?: string;
    message?: string;
    data?: MarketAuthResult;
  };
  if (!j.success || !j.data?.token) {
    throw new Error(j.detail || j.message || '市场注册失败');
  }
  return j.data;
}
