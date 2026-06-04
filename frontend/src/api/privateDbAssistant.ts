import { api } from './index';
import type { ApiResponse } from '@/types/api';

const BASE = '/api/mod/private-db-read-assistant';

export interface PrivateDbSource {
  id: string;
  label: string;
  description?: string;
  status?: 'available' | 'planned';
  category?: 'im' | 'mail' | 'erp' | 'office' | 'ecommerce' | 'generic';
  icon?: string;
  capabilities?: string[];
  requires_authorization?: boolean;
}

export interface PrivateDbContact {
  id?: number | null;
  display_name: string;
  contact_name?: string;
  remark?: string;
  source_user_id?: string;
  contact_type?: string;
  is_starred?: boolean;
}

export const privateDbAssistantApi = {
  status(): Promise<ApiResponse<any>> {
    return api.get<ApiResponse<any>>(`${BASE}/status`);
  },

  listSources(): Promise<ApiResponse<PrivateDbSource[]>> {
    return api.get<ApiResponse<PrivateDbSource[]>>(`${BASE}/sources`);
  },

  selectSource(sourceId: string): Promise<ApiResponse<any>> {
    return api.post<ApiResponse<any>>(`${BASE}/sources/select`, { source_id: sourceId });
  },

  refreshSource(sourceId: string, refreshType: 'contacts' | 'messages' | 'all' = 'contacts'): Promise<ApiResponse<any>> {
    return api.post<ApiResponse<any>>(`${BASE}/sources/refresh`, {
      source_id: sourceId,
      refresh_type: refreshType,
    });
  },

  searchContacts(sourceId: string, q: string): Promise<ApiResponse<PrivateDbContact[]>> {
    return api.get<ApiResponse<PrivateDbContact[]>>(`${BASE}/contacts/search`, {
      source_id: sourceId,
      q,
    });
  },

  getContext(sourceId: string, contactId: number | string): Promise<ApiResponse<any[]>> {
    return api.get<ApiResponse<any[]>>(`${BASE}/contacts/${contactId}/context`, {
      source_id: sourceId,
    });
  },

  sendMessage(sourceId: string, contactName: string, message: string): Promise<ApiResponse<any>> {
    return api.post<ApiResponse<any>>(`${BASE}/send`, {
      source_id: sourceId,
      contact_name: contactName,
      message,
    });
  },
};

export default privateDbAssistantApi;
