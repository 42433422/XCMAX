import { api } from './core';
import { ApiError } from './core';
import type { ApiResponse } from '@/types/api';
import { resolveErpApiPath } from '@/utils/erpDomainPaths';
import { wechatContactWriteSchema } from '@/schemas/wechat';

const erp = (path: string) => resolveErpApiPath(path);

const AUTO_CONFIGURE_CANDIDATES = [
  '/api/wechat_contacts/auto_configure',
  '/api/wechat/contacts/auto_configure',
  '/api/mod/private-db-read-assistant/wechat/auto_configure',
];

export interface WechatTask {
  id: number;
  type: string;
  content: string;
  status: 'pending' | 'confirmed' | 'ignored' | 'completed';
  created_at?: string;
  [key: string]: any;
}

export interface WechatContact {
  id: number;
  name: string;
  wechat_id?: string;
  phone?: string;
  tags?: string[];
  is_starred: boolean;
  created_at?: string;
  updated_at?: string;
  [key: string]: any;
}

export interface WechatSearchResult {
  id?: number;
  display_name?: string;
  username?: string;
  remark?: string;
  contact_type?: string;
  already_starred?: boolean;
  [key: string]: any;
}

function parseContactWrite(data: unknown) {
  const parsed = wechatContactWriteSchema.safeParse(data);
  if (!parsed.success) {
    const issue = parsed.error.issues[0];
    throw new Error(issue?.message || '联系人信息无效');
  }
  return parsed.data;
}

function mapSearchRow(row: Record<string, any>): WechatSearchResult {
  const contactName = row.contact_name ?? row.name;
  const wechatId = row.wechat_id;
  return {
    id: row.id,
    display_name: contactName,
    username: wechatId ?? contactName,
    remark: row.remark,
    contact_type: row.contact_type,
    already_starred: Boolean(row.is_starred),
  };
}

function pickStarId(data: Record<string, any>): number | string | null {
  if (data.id != null && data.id !== '') return data.id;
  if (data.contact_id != null && data.contact_id !== '') return data.contact_id;
  return null;
}

function hasSearchableFields(data: Record<string, any>): boolean {
  const fields = [data.contact_name, data.wechat_id, data.display_name, data.name, data.username];
  return fields.some((v) => String(v ?? '').trim().length > 0);
}

function buildSearchKeyword(data: Record<string, any>): string {
  const candidates = [data.wechat_id, data.username, data.contact_name, data.display_name, data.name];
  for (const c of candidates) {
    const s = String(c ?? '').trim();
    if (s) return s;
  }
  return '';
}

async function searchPrimaryContacts(keyword: string): Promise<Record<string, any>[]> {
  const res = await api.get<ApiResponse<any[]>>(erp('/api/wechat/contacts'), {
    keyword,
    type: 'all',
    starred: 'false',
    limit: 50,
  });
  const rows = res?.data;
  return Array.isArray(rows) ? rows : [];
}

async function legacySearchContacts(keyword: string): Promise<ApiResponse<any>> {
  return api.get<ApiResponse<any>>(erp('/api/wechat_contacts/search'), { q: keyword });
}

function matchSearchHit(rows: Record<string, any>[], data: Record<string, any>): Record<string, any> | null {
  const needle = [
    data.wechat_id,
    data.username,
    data.contact_name,
    data.display_name,
    data.name,
  ]
    .map((v) => String(v ?? '').trim().toLowerCase())
    .filter(Boolean);
  if (!needle.length) return null;
  for (const row of rows) {
    const hay = [
      row.wechat_id,
      row.contact_name,
      row.name,
    ]
      .map((v) => String(v ?? '').trim().toLowerCase())
      .filter(Boolean);
    if (needle.some((n) => hay.some((h) => h.includes(n) || n.includes(h)))) {
      return row;
    }
  }
  return null;
}

export const wechatApi = {
  getTasks(params: Record<string, any> = {}): Promise<ApiResponse<WechatTask[]>> {
    return api.get<ApiResponse<WechatTask[]>>(erp('/api/wechat/tasks'), params);
  },

  confirmTask(id: number | string): Promise<ApiResponse<any>> {
    return api.post<ApiResponse<any>>(erp(`/api/wechat/task/${id}/confirm`));
  },

  ignoreTask(id: number | string): Promise<ApiResponse<any>> {
    return api.post<ApiResponse<any>>(erp(`/api/wechat/task/${id}/ignore`));
  },

  getContacts(params: Record<string, any> = {}): Promise<ApiResponse<WechatContact[]>> {
    return api.get<ApiResponse<WechatContact[]>>(erp('/api/wechat/contacts'), params);
  },

  addContact(data: any): Promise<ApiResponse<WechatContact>> {
    const payload = parseContactWrite(data);
    return api.post<ApiResponse<WechatContact>>(erp('/api/wechat/contacts'), payload);
  },

  getContact(id: number | string): Promise<ApiResponse<WechatContact>> {
    return api.get<ApiResponse<WechatContact>>(erp(`/api/wechat/contacts/${id}`));
  },

  updateContact(id: number | string, data: any): Promise<ApiResponse<WechatContact>> {
    const payload = parseContactWrite(data);
    return api.put<ApiResponse<WechatContact>>(erp(`/api/wechat/contacts/${id}`), payload);
  },

  deleteContact(id: number | string): Promise<ApiResponse<void>> {
    return api.delete<ApiResponse<void>>(erp(`/api/wechat/contacts/${id}`));
  },

  scanMessages(): Promise<ApiResponse<any>> {
    return api.post<ApiResponse<any>>(erp('/api/wechat/scan'));
  },

  getContactContext(id: number | string): Promise<ApiResponse<any>> {
    return api.get<ApiResponse<any>>(erp(`/api/wechat/contacts/${id}/context`));
  },

  async ensureContactCache(): Promise<ApiResponse<any>> {
    const normalizeNoSource404 = (error: unknown): string => {
      if (!(error instanceof ApiError) || error.status !== 404) return '';
      const message = String(error?.data?.message || error.message || '');
      if (!message) return '';
      if (/未找到可导入的联系人源|contact\.db|Name2Id/i.test(message)) {
        return message;
      }
      return '';
    };

    const tryPostFallback = async (): Promise<ApiResponse<any>> => {
      try {
        return await api.post<ApiResponse<any>>(erp('/api/wechat_contacts/ensure_contact_cache'), {});
      } catch (postError) {
        const noSourceMessage = normalizeNoSource404(postError);
        if (noSourceMessage) {
          return { success: true, message: noSourceMessage, data: { skipped: true } };
        }
        if (postError instanceof ApiError && (postError.status === 404 || postError.status === 405)) {
          return api.post<ApiResponse<any>>(erp('/api/wechat_contacts/refresh_contact_cache'), {});
        }
        throw postError;
      }
    };

    try {
      return await api.get<ApiResponse<any>>(erp('/api/wechat_contacts/ensure_contact_cache'));
    } catch (error) {
      const noSourceMessage = normalizeNoSource404(error);
      if (noSourceMessage) {
        return { success: true, message: noSourceMessage, data: { skipped: true } };
      }
      if (error instanceof ApiError && (error.status === 404 || error.status === 405)) {
        return tryPostFallback();
      }
      throw error;
    }
  },

  async searchContacts(query: string): Promise<ApiResponse<any> & { results?: WechatSearchResult[] }> {
    const keyword = String(query ?? '').trim();
    if (!keyword) {
      return { success: true, data: [] };
    }
    try {
      const rows = await searchPrimaryContacts(keyword);
      if (rows.length) {
        const results = rows.map((row) => mapSearchRow(row));
        return { success: true, data: rows, results };
      }
    } catch {
      /* legacy fallback */
    }
    return legacySearchContacts(keyword);
  },

  async autoConfigure(options: { force_key_scan?: boolean } = {}): Promise<any> {
    const paths =
      options.force_key_scan === true
        ? [AUTO_CONFIGURE_CANDIDATES[0]]
        : Array.from(new Set(AUTO_CONFIGURE_CANDIDATES.map((p) => erp(p))));
    const body = { force_key_scan: options.force_key_scan ?? false };
    let lastApiError: ApiError | null = null;
    for (const path of paths) {
      try {
        return await api.post(path, body);
      } catch (error) {
        if (error instanceof ApiError) {
          if (error.status === 404 || error.status === 405) {
            lastApiError = error;
            continue;
          }
          throw error;
        }
        throw error;
      }
    }
    if (lastApiError) throw lastApiError;
    throw new ApiError('auto configure failed', 404, null);
  },

  getStarredContacts(params: Record<string, any> = {}): Promise<ApiResponse<WechatContact[]>> {
    const query = {
      starred: 'true',
      limit: params.limit ?? 200,
      type: params.type ?? 'all',
      ...params,
    };
    return api.get<ApiResponse<WechatContact[]>>(erp('/api/wechat/contacts'), query);
  },

  async addStarredContact(data: any): Promise<ApiResponse<WechatContact>> {
    const payload = { ...(data || {}) } as Record<string, any>;
    const starId = pickStarId(payload);
    if (starId != null) {
      return api.post<ApiResponse<WechatContact>>(erp(`/api/wechat/contacts/${starId}/star`), {
        starred: true,
      });
    }
    if (!hasSearchableFields(payload)) {
      return api.post<ApiResponse<WechatContact>>(erp('/api/wechat/contacts'), {
        ...payload,
        is_starred: true,
      });
    }
    const keyword = buildSearchKeyword(payload);
    let hit: Record<string, any> | null = null;
    try {
      const rows = await searchPrimaryContacts(keyword);
      hit = matchSearchHit(rows, payload);
      if (!hit) {
        const legacy = await legacySearchContacts(keyword);
        const legacyRows = Array.isArray(legacy?.data) ? legacy.data : [];
        hit = matchSearchHit(legacyRows, payload);
      }
    } catch {
      /* create below */
    }
    if (hit?.id != null) {
      return api.post<ApiResponse<WechatContact>>(erp(`/api/wechat/contacts/${hit.id}/star`), {
        starred: true,
      });
    }
    const createPayload = { ...payload, is_starred: true };
    if (createPayload.contact_name == null && createPayload.name) {
      createPayload.contact_name = createPayload.name;
    }
    return api.post<ApiResponse<WechatContact>>(erp('/api/wechat/contacts'), createPayload);
  },

  updateStarredContact(id: number | string, data: any): Promise<ApiResponse<WechatContact>> {
    return api.put<ApiResponse<WechatContact>>(erp(`/api/wechat/contacts/${id}`), data);
  },

  deleteStarredContact(id: number | string): Promise<ApiResponse<void>> {
    return api.post<ApiResponse<void>>(erp(`/api/wechat/contacts/${id}/star`), { starred: false });
  },

  unstarAllContacts(): Promise<ApiResponse<any>> {
    return api.post<ApiResponse<any>>(erp('/api/wechat/contacts/unstar-all'), {});
  },

  getStarredContactContext(id: number | string): Promise<ApiResponse<any>> {
    return api.get<ApiResponse<any>>(erp(`/api/wechat/contacts/${id}/context`));
  },

  refreshContactMessages(
    id: number | string,
    options: { limit?: number; force_live_refresh?: boolean } = {},
  ): Promise<ApiResponse<any>> {
    return api.post<ApiResponse<any>>(erp(`/api/wechat_contacts/${id}/refresh_messages`), {
      limit: options.limit ?? 80,
      force_live_refresh: options.force_live_refresh ?? false,
    });
  },

  refreshMessagesCache(): Promise<ApiResponse<any>> {
    return api.post<ApiResponse<any>>(erp('/api/wechat_contacts/refresh_messages_cache'), {});
  },

  refreshContactCache(): Promise<ApiResponse<any>> {
    return api.post<ApiResponse<any>>(erp('/api/wechat_contacts/refresh_contact_cache'), {});
  },

  openChat(contactName: string): Promise<ApiResponse<any>> {
    return api.post<ApiResponse<any>>(erp('/api/wechat_contacts/open_chat'), { contact_name: contactName });
  },

  sendMessage(contactName: string, message: string): Promise<ApiResponse<any>> {
    return api.post<ApiResponse<any>>(erp('/api/wechat_contacts/send_message'), {
      contact_name: contactName,
      message,
    });
  },
};

export default wechatApi;
