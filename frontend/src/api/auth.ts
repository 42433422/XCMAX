import { api, primeCsrfCookie } from './core';
import { LS_MARKET_ACCESS_TOKEN, LS_MARKET_USER_JSON } from './marketAccount';
import type { ApiResponse } from '@/types/api';

export type AccountKind = 'personal' | 'enterprise' | 'admin';

export interface LoginRequest {
  username: string;
  password: string;
}

export interface User {
  id: number;
  username: string;
  display_name: string;
  email: string;
  role: string;
  is_active: boolean;
}

export interface LoginResponse {
  success: boolean;
  user?: User;
  session_id?: string;
  expires_at?: string;
  message?: string;
  error?: any;
  market_access_token?: string;
}

export const authApi = {
  async login(username: string, password: string): Promise<ApiResponse<LoginResponse>> {
    await primeCsrfCookie();
    return api.post<ApiResponse<LoginResponse>>('/api/auth/login', { username, password });
  },

  async logout(): Promise<ApiResponse<void>> {
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

  async validateSession(): Promise<ApiResponse<any>> {
    return api.get<ApiResponse<any>>('/api/auth/session/validate');
  }
};

export default authApi;
