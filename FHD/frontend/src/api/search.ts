import { api } from './core';

export type SearchScope = 'products' | 'customers' | 'excel' | 'all';

export interface SearchV0Response {
  success: boolean;
  query: string;
  scope: SearchScope;
  results: {
    products?: { success?: boolean; data?: Record<string, unknown>[]; message?: string };
    customers?: { success?: boolean; data?: Record<string, unknown>[]; message?: string };
    excel_vector?: { success?: boolean; hits?: Record<string, unknown>[]; message?: string };
  };
}

export const searchApi = {
  searchV0(q: string, scope: SearchScope = 'all', perPage = 20): Promise<SearchV0Response> {
    return api.get<SearchV0Response>('/api/search/v0', { q, scope, per_page: perPage });
  },
};

export default searchApi;
