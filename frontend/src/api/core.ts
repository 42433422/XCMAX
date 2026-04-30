import { notifyDbReadTokenRequiredAfter403, notifyDbWriteTokenRequiredAfter403 } from '@/fhd/dbTokenHeaders';
import { getApiBase } from '@/utils/apiBase';

/**
 * 后端 LanLicenseGuard 返回 401 + error=license_* 时派发；
 * App.vue 侧监听并弹出 GlobalLanGateModal（避免每个业务页各自处理未授权跳转）。
 */
export const XCAGI_PROMPT_LAN_GATE_EVENT = 'xcagi:prompt-lan-gate';

const LAN_GATE_ERROR_CODES = new Set([
  'license_required',
  'license_invalid',
  'license_expired',
  'license_revoked',
  'license_misconfigured',
]);

function maybeNotifyLanGate(status: number, errorData: any): void {
  if (status !== 401 && status !== 503) return;
  if (typeof window === 'undefined') return;
  const code = String(errorData?.error || '').trim();
  if (!LAN_GATE_ERROR_CODES.has(code)) return;
  window.dispatchEvent(
    new CustomEvent(XCAGI_PROMPT_LAN_GATE_EVENT, {
      detail: {
        status,
        code,
        message: errorData?.message || '',
      },
    })
  );
}

function buildApiUrl(url: string): string {
  const normalizedUrl = String(url || '');
  if (/^https?:\/\//i.test(normalizedUrl)) {
    return normalizedUrl;
  }
  if (!API_BASE) {
    return normalizedUrl;
  }
  return normalizedUrl.startsWith('/') ? `${API_BASE}${normalizedUrl}` : `${API_BASE}/${normalizedUrl}`;
}

/** 与 api.post/get 同源；用于 fetch 健康检查等，避免已配置 API 基址时仍请求到错误源。 */
export function buildFullApiUrl(url: string): string {
  return buildApiUrl(url);
}

const API_BASE = getApiBase();

const defaultHeaders: Record<string, string> = {
  'Content-Type': 'application/json'
};

export class ApiError extends Error {
  status: number;
  data: any;

  constructor(message: string, status: number, data: any) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

export interface RequestOptions extends RequestInit {
  skipDefaultJsonHeader?: boolean;
  responseType?: 'json' | 'blob';
}

export interface ApiResponse<T = any> {
  success: boolean;
  data?: T;
  message?: string;
  total?: number;
}

async function request(url: string, options: RequestOptions = {}): Promise<any> {
  const fullUrl = buildApiUrl(url);
  const { skipDefaultJsonHeader = false, ...requestOptions } = options;
  const config: RequestOptions = {
    credentials: 'include',
    ...requestOptions
  };
  const baseHeaders = skipDefaultJsonHeader ? {} : defaultHeaders;
  config.headers = {
    ...baseHeaders,
    ...(requestOptions.headers || {})
  };

  try {
    const response = await fetch(fullUrl, config);
    const contentType = response.headers.get('content-type') || '';

    if (!response.ok) {
      let errorData = null;
      let errorMessage = `请求失败：${response.status}`;
      
      if (contentType.includes('application/json')) {
        try {
          errorData = await response.json();
          errorMessage = errorData.message || errorMessage;
        } catch (_) {}
      }

      const method = String(config.method || 'GET').toUpperCase();
      notifyDbReadTokenRequiredAfter403(response.status, fullUrl, method);
      notifyDbWriteTokenRequiredAfter403(response.status, fullUrl, method);
      maybeNotifyLanGate(response.status, errorData);

      throw new ApiError(errorMessage, response.status, errorData);
    }

    if (options.responseType === 'blob') {
      return response;
    }

    if (contentType.includes('application/json')) {
      return await response.json();
    }

    return response;
  } catch (error: any) {
      if (error instanceof ApiError) {
        throw error;
      }
      throw new ApiError((error as any).message || '网络错误', 0, null);
    }
}

export const api = {
  get<T = any>(url: string, params: Record<string, any> = {}, options: RequestOptions = {}): Promise<T> {
    const searchParams = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== null && value !== undefined) {
        searchParams.append(key, String(value));
      }
    });
    const queryString = searchParams.toString();
    const fullUrl = queryString ? `${url}?${queryString}` : url;
    return request(fullUrl, {
      method: 'GET',
      ...options
    });
  },

  post<T = any>(url: string, data: any = {}, options: RequestOptions = {}): Promise<T> {
    const isFormData = typeof FormData !== 'undefined' && data instanceof FormData;
    const headers = { ...(options.headers || {}) };
    return request(url, {
      method: 'POST',
      body: isFormData ? data : JSON.stringify(data),
      headers,
      skipDefaultJsonHeader: isFormData,
      ...options
    });
  },

  put<T = any>(url: string, data: any = {}, options: RequestOptions = {}): Promise<T> {
    const isFormData = typeof FormData !== 'undefined' && data instanceof FormData;
    const headers = { ...(options.headers || {}) };
    return request(url, {
      method: 'PUT',
      body: isFormData ? data : JSON.stringify(data),
      headers,
      skipDefaultJsonHeader: isFormData,
      ...options
    });
  },

  patch<T = any>(url: string, data: any = {}, options: RequestOptions = {}): Promise<T> {
    const isFormData = typeof FormData !== 'undefined' && data instanceof FormData;
    const headers = { ...(options.headers || {}) };
    return request(url, {
      method: 'PATCH',
      body: isFormData ? data : JSON.stringify(data),
      headers,
      skipDefaultJsonHeader: isFormData,
      ...options
    });
  },

  delete<T = any>(url: string, data: any = {}, options: RequestOptions = {}): Promise<T> {
    const config: RequestOptions = {
      method: 'DELETE',
      ...options
    };
    if (Object.keys(data).length > 0) {
      config.body = JSON.stringify(data);
    }
    return request(url, config);
  },

  download(url: string, params: Record<string, any> = {}, options: RequestOptions = {}): Promise<Response> {
    const searchParams = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== null && value !== undefined) {
        searchParams.append(key, String(value));
      }
    });
    const queryString = searchParams.toString();
    const fullUrl = queryString ? `${url}?${queryString}` : url;
    return request(fullUrl, {
      method: 'GET',
      responseType: 'blob',
      ...options
    });
  }
};

export { API_BASE };
export default api;
