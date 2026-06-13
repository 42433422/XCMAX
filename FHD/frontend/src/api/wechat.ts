import { api } from './core';
import { ApiError } from './core';
import type { ApiResponse } from '@/types/api';
import type {
  WechatContact,
  WechatContactCacheResult,
  WechatContactInput,
  WechatMessageContext,
  WechatTask,
} from '@/types/wechat';
import type { StringMap } from '@/types/json';
import { resolveErpApiPath } from '@/utils/erpDomainPaths';

const erp = (path: string) => resolveErpApiPath(path);

export type { WechatTask, WechatContact };

/** Runtime fields not in base API schema */
export interface WechatContactRuntime extends WechatContact {
  lastMessage?: string;
  lastMessageTime?: string;
  unreadCount?: number;
}

export interface WorkModeFeedMessage {
  contactId?: number | string;
  content?: string;
  timestamp?: string;
}

export interface WorkModeOrder {
  id?: number | string;
  [key: string]: unknown;
}

export interface WorkModeTaskAcquisition {
  content?: string;
  order?: WorkModeOrder;
}

export const wechatApi = {
  getTasks(params: StringMap = {}): Promise<ApiResponse<WechatTask[]>> {
    return api.get<ApiResponse<WechatTask[]>>(erp('/api/wechat/tasks'), params);
  },

  confirmTask(id: number | string): Promise<ApiResponse<WechatTask>> {
    return api.post<ApiResponse<WechatTask>>(erp(`/api/wechat/task/${id}/confirm`));
  },

  ignoreTask(id: number | string): Promise<ApiResponse<WechatTask>> {
    return api.post<ApiResponse<WechatTask>>(erp(`/api/wechat/task/${id}/ignore`));
  },

  getContacts(params: StringMap = {}): Promise<ApiResponse<WechatContact[]>> {
    return api.get<ApiResponse<WechatContact[]>>(erp('/api/wechat/contacts'), params);
  },

  addContact(data: WechatContactInput): Promise<ApiResponse<WechatContact>> {
    return api.post<ApiResponse<WechatContact>>(erp('/api/wechat/contacts'), data);
  },

  getContact(id: number | string): Promise<ApiResponse<WechatContact>> {
    return api.get<ApiResponse<WechatContact>>(erp(`/api/wechat/contacts/${id}`));
  },

  updateContact(id: number | string, data: WechatContactInput): Promise<ApiResponse<WechatContact>> {
    return api.put<ApiResponse<WechatContact>>(erp(`/api/wechat/contacts/${id}`), data);
  },

  deleteContact(id: number | string): Promise<ApiResponse<void>> {
    return api.delete<ApiResponse<void>>(erp(`/api/wechat/contacts/${id}`));
  },

  scanMessages(): Promise<ApiResponse<StringMap>> {
    return api.post<ApiResponse<StringMap>>(erp('/api/wechat/scan'));
  },

  getContactContext(id: number | string): Promise<ApiResponse<WechatMessageContext>> {
    return api.get<ApiResponse<WechatMessageContext>>(erp(`/api/wechat/contacts/${id}/context`));
  },

  // Legacy-compatible contacts endpoints used by current console pages.
  getStarredContacts(params: StringMap = {}): Promise<ApiResponse<WechatContact[]>> {
    return api.get<ApiResponse<WechatContact[]>>(erp('/api/wechat_contacts'), params);
  },

  async ensureContactCache(): Promise<ApiResponse<WechatContactCacheResult>> {
    const normalizeNoSource404 = (error: unknown): string => {
      if (!(error instanceof ApiError) || error.status !== 404) return '';
      const message = String((error.data as Record<string, unknown> | null)?.message || error.message || '');
      if (!message) return '';
      if (/未找到可导入的联系人源|contact\.db|Name2Id/i.test(message)) {
        return message;
      }
      return '';
    };

    const tryPostFallback = async (): Promise<ApiResponse<WechatContactCacheResult>> => {
      try {
        return await api.post<ApiResponse<WechatContactCacheResult>>(erp('/api/wechat_contacts/ensure_contact_cache'), {});
      } catch (postError) {
        const noSourceMessage = normalizeNoSource404(postError);
        if (noSourceMessage) {
          return { success: true, message: noSourceMessage, data: { skipped: true } };
        }
        if (postError instanceof ApiError && (postError.status === 404 || postError.status === 405)) {
          return api.post<ApiResponse<WechatContactCacheResult>>(erp('/api/wechat_contacts/refresh_contact_cache'), {});
        }
        throw postError;
      }
    };

    try {
      return await api.get<ApiResponse<WechatContactCacheResult>>(erp('/api/wechat_contacts/ensure_contact_cache'));
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

  searchContacts(query: string): Promise<ApiResponse<WechatContact[]>> {
    return api.get<ApiResponse<WechatContact[]>>(erp('/api/wechat_contacts/search'), { q: query || '' });
  },

  addStarredContact(data: WechatContactInput): Promise<ApiResponse<WechatContact>> {
    return api.post<ApiResponse<WechatContact>>(erp('/api/wechat_contacts'), data);
  },

  updateStarredContact(id: number | string, data: WechatContactInput): Promise<ApiResponse<WechatContact>> {
    return api.put<ApiResponse<WechatContact>>(erp(`/api/wechat_contacts/${id}`), data);
  },

  deleteStarredContact(id: number | string): Promise<ApiResponse<void>> {
    return api.delete<ApiResponse<void>>(erp(`/api/wechat_contacts/${id}`));
  },

  unstarAllContacts(): Promise<ApiResponse<StringMap>> {
    return api.post<ApiResponse<StringMap>>(erp('/api/wechat_contacts/unstar_all'), {});
  },

  getStarredContactContext(id: number | string): Promise<ApiResponse<WechatMessageContext>> {
    return api.get<ApiResponse<WechatMessageContext>>(erp(`/api/wechat_contacts/${id}/context`));
  },

  refreshContactMessages(id: number | string): Promise<ApiResponse<StringMap>> {
    return api.post<ApiResponse<StringMap>>(erp(`/api/wechat_contacts/${id}/refresh_messages`), {});
  },

  refreshMessagesCache(): Promise<ApiResponse<StringMap>> {
    return api.post<ApiResponse<StringMap>>(erp('/api/wechat_contacts/refresh_messages_cache'), {});
  },

  refreshContactCache(): Promise<ApiResponse<WechatContactCacheResult>> {
    return api.post<ApiResponse<WechatContactCacheResult>>(erp('/api/wechat_contacts/refresh_contact_cache'), {});
  },

  openChat(contactName: string): Promise<ApiResponse<StringMap>> {
    return api.post<ApiResponse<StringMap>>(erp('/api/wechat_contacts/open_chat'), { contact_name: contactName });
  },

  sendMessage(contactName: string, message: string): Promise<ApiResponse<StringMap>> {
    return api.post<ApiResponse<StringMap>>(erp('/api/wechat_contacts/send_message'), {
      contact_name: contactName,
      message
    });
  }
};

export default wechatApi;
