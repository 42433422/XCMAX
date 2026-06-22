import { api, primeCsrfCookie } from './core';
import { LS_MARKET_ACCESS_TOKEN, LS_MARKET_USER_JSON } from './marketAccount';
import { invalidateEnterpriseSessionCache } from '@/utils/authSessionCache';
import { clearAutoLoginPreference } from '@/utils/loginPreferences';
import type { ApiResponse } from '@/types/api';

export type AccountKind = 'personal' | 'enterprise' | 'admin';
// 账号体系：等级（仅企业有意义）/ 预算区间 / 修茈市场会员等级
export type AccountTier = 'normal' | 'pro' | 'max' | 'ultra';
export type BudgetRange = '5 万以内' | '5–20 万' | '20–50 万' | '50 万以上';
export type MarketMembershipTier = string; // free | vip | vip_plus | svip1..svip8

export interface LoginRequest {
  username: string;
  password: string;
  account_kind?: AccountKind;
}

export interface User {
  id: number;
  username: string;
  display_name: string;
  email: string;
  role: string;
  is_active: boolean;
  avatar_url?: string;
}

export interface UserProfilePayload {
  display_name?: string;
  email?: string;
}

export interface LoginResponse {
  success: boolean;
  user?: User;
  session_id?: string;
  expires_at?: string;
  message?: string;
  error?: unknown;
  market_access_token?: string;
  market_refresh_token?: string;
}

export interface RegisterRequest {
  username: string;
  password: string;
  email?: string;
  verification_code?: string;
  display_name?: string;
  // 账号体系：预算区间（→ account_tier 派生）与行业
  budget_range?: string;
  industry_id?: string;
}

async function invalidateSessionScopedUiCaches(): Promise<void> {
  invalidateEnterpriseSessionCache();
  try {
    const { clearDeliverableStatusCache } = await import('@/utils/platformShellApi');
    clearDeliverableStatusCache();
  } catch {
    /* ignore */
  }
}

export const authApi = {
  async login(
    username: string,
    password: string,
    accountKind: AccountKind = 'enterprise',
  ): Promise<ApiResponse<LoginResponse>> {
    await primeCsrfCookie();
    invalidateEnterpriseSessionCache();
    const res = await api.post<ApiResponse<LoginResponse>>('/api/auth/login', {
      username,
      password,
      account_kind: accountKind,
    });
    await invalidateSessionScopedUiCaches();
    return res;
  },

  async loginWithPhoneCode(
    phone: string,
    code: string,
    accountKind: AccountKind = 'enterprise',
  ): Promise<ApiResponse<LoginResponse>> {
    await primeCsrfCookie();
    invalidateEnterpriseSessionCache();
    const res = await api.post<ApiResponse<LoginResponse>>('/api/auth/login-with-phone-code', {
      phone,
      code,
      account_kind: accountKind,
    });
    await invalidateSessionScopedUiCaches();
    return res;
  },

  async sendPhoneCode(phone: string): Promise<ApiResponse<{ message?: string }>> {
    await primeCsrfCookie();
    return api.post<ApiResponse<{ message?: string }>>('/api/market/send-phone-code', { phone });
  },

  async getOidcStatus(): Promise<ApiResponse<{ enabled?: boolean }>> {
    return api.get<ApiResponse<{ enabled?: boolean }>>('/api/auth/oidc/status');
  },

  async issueAuthQr(clientHint = '', accountKind = 'enterprise'): Promise<
    ApiResponse<{ qr_id?: string; poll_secret?: string; expires_at?: number; account_kind?: string }>
  > {
    await primeCsrfCookie();
    return api.post('/api/auth/qr/issue', { client_hint: clientHint, account_kind: accountKind });
  },

  async pollAuthQr(
    qrId: string,
    pollSecret: string,
  ): Promise<ApiResponse<{ status?: string; session_id?: string }>> {
    return api.get('/api/auth/qr/status', {
      qr_id: qrId,
      poll_secret: pollSecret,
    });
  },

  async getSubscriptionStatus(): Promise<ApiResponse<Record<string, unknown>>> {
    return api.get<ApiResponse<Record<string, unknown>>>('/api/auth/subscription/status');
  },

  async updateCompanyBrand(companyBrand: string) {
    return api.post('/api/auth/company-brand', { company_brand: companyBrand });
  },

  async register(payload: RegisterRequest): Promise<ApiResponse<LoginResponse>> {
    await primeCsrfCookie();
    invalidateEnterpriseSessionCache();
    const res = await api.post<ApiResponse<LoginResponse>>('/api/auth/register', payload);
    await invalidateSessionScopedUiCaches();
    return res;
  },

  async logout(): Promise<ApiResponse<void>> {
    clearAutoLoginPreference();
    await invalidateSessionScopedUiCaches();
    try {
      const { useAccountProfileStore } = await import('@/stores/accountProfile');
      useAccountProfileStore().clear();
    } catch {
      /* ignore */
    }
    try {
      window.localStorage.removeItem(LS_MARKET_ACCESS_TOKEN);
      window.localStorage.removeItem(LS_MARKET_USER_JSON);
    } catch {
      /* ignore */
    }
    await primeCsrfCookie();
    return api.post<ApiResponse<void>>('/api/auth/logout', {});
  },

  async getCurrentUser(): Promise<ApiResponse<{ user: User; permissions: string[] }>> {
    return api.get<ApiResponse<{ user: User; permissions: string[] }>>('/api/auth/me');
  },

  async getProfile(): Promise<ApiResponse<{ user: User }>> {
    return api.get<ApiResponse<{ user: User }>>('/api/auth/profile');
  },

  async updateProfile(payload: UserProfilePayload): Promise<ApiResponse<{ user: User }>> {
    await primeCsrfCookie();
    return api.patch<ApiResponse<{ user: User }>>('/api/auth/profile', payload);
  },

  async uploadAvatar(file: File): Promise<ApiResponse<{ avatar_url: string }>> {
    await primeCsrfCookie();
    const form = new FormData();
    form.append('file', file);
    return api.post<ApiResponse<{ avatar_url: string }>>('/api/auth/profile/avatar', form);
  },

  async validateSession(): Promise<ApiResponse<unknown>> {
    return api.get<ApiResponse<unknown>>('/api/auth/session/validate');
  },

  async forgotAccount(email: string): Promise<
    ApiResponse<{ usernames: string[]; found: boolean }>
  > {
    await primeCsrfCookie();
    return api.post<ApiResponse<{ usernames: string[]; found: boolean }>>('/api/auth/forgot-account', {
      email,
    });
  },

  async sendForgotPasswordCode(email: string): Promise<ApiResponse<unknown>> {
    await primeCsrfCookie();
    return api.post<ApiResponse<unknown>>('/api/auth/forgot-password/send-code', { email });
  },

  async resetForgotPassword(
    email: string,
    code: string,
    newPassword: string,
  ): Promise<ApiResponse<{ local_users_updated?: number }>> {
    await primeCsrfCookie();
    return api.post<ApiResponse<{ local_users_updated?: number }>>(
      '/api/auth/forgot-password/reset',
      { email, code, new_password: newPassword },
    );
  },
};

export default authApi;
