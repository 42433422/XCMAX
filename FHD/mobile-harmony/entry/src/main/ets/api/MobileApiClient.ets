import http from '@ohos.net.http';
import { ApiEndpoints } from './ApiEndpoints';
import {
  ApprovalDetail,
  ApprovalItem,
  ChatMessage,
  ChatResponseData,
  CsInfo,
  MobileEnvelope,
  MobileFixedContactsData,
  MobileHomeData,
  MobileLoginData,
  MobileMeData,
  MobileModsData,
  PairingExchangeData,
  RelayConfirmCodeBody,
  RelayConfirmCodeData,
  RelayDesktop,
  RelayDesktopsData,
  RelayTask,
  RelayTaskContext,
  RelayTaskCreateBody,
  RelayTaskData,
  SuperEmployeeContext,
  SuperEmployeeInvokeData,
  SuperEmployeeMessageBody,
  SuperEmployeeMessageRow,
  SuperEmployeeMessagesData
} from '../models/MobileModels';

type HeaderMap = Record<string, string>;

interface LoginRequestBody {
  username: string;
  password: string;
  account_kind: string;
}

interface PairingRequestBody {
  code: string;
}

interface ChatRequestBody {
  message: string;
  session_id: string;
}

interface ApprovalActionBody {
  opinion: string;
}

export class MobileApiClient {
  private baseUrl: string;
  private accessToken: string;

  constructor(baseUrl: string, accessToken: string = '') {
    this.baseUrl = MobileApiClient.normalizeBaseUrl(baseUrl);
    this.accessToken = accessToken;
  }

  setBaseUrl(baseUrl: string): void {
    this.baseUrl = MobileApiClient.normalizeBaseUrl(baseUrl);
  }

  setAccessToken(accessToken: string): void {
    this.accessToken = accessToken;
  }

  getBaseUrl(): string {
    return this.baseUrl;
  }

  async login(username: string, password: string, accountKind: string = 'admin'): Promise<MobileLoginData> {
    const body: LoginRequestBody = {
      username: username.trim(),
      password: password,
      account_kind: accountKind.trim().length > 0 ? accountKind.trim() : 'admin'
    };
    const envelope = await this.request<MobileLoginData>(
      ApiEndpoints.AUTH_LOGIN,
      http.RequestMethod.POST,
      body
    );
    return envelope.data || {};
  }

  async me(): Promise<MobileMeData> {
    const envelope = await this.request<MobileMeData>(ApiEndpoints.ME, http.RequestMethod.GET);
    return envelope.data || {};
  }

  async home(): Promise<MobileHomeData> {
    const envelope = await this.request<MobileHomeData>(ApiEndpoints.HOME, http.RequestMethod.GET);
    return envelope.data || {};
  }

  async mods(): Promise<MobileModsData> {
    const envelope = await this.request<MobileModsData>(ApiEndpoints.MODS, http.RequestMethod.GET);
    return envelope.data || {};
  }

  async pairingExchange(code: string): Promise<PairingExchangeData> {
    const body: PairingRequestBody = {
      code: code.trim()
    };
    const envelope = await this.request<PairingExchangeData>(
      ApiEndpoints.PAIRING_EXCHANGE,
      http.RequestMethod.POST,
      body
    );
    return envelope.data || {};
  }

  async chat(message: string, sessionId: string): Promise<ChatResponseData> {
    const body: ChatRequestBody = {
      message: message,
      session_id: sessionId
    };
    const response = await this.rawRequest<ChatResponseData>(
      'api/ai/chat',
      http.RequestMethod.POST,
      body
    );
    return response;
  }

  // ── 超级员工（Codex/Claude）派工 ──
  // tool: 'claude' 走 Claude 端点，其余走 Codex。mode: 'auto'|'chat'|'code'。
  private superEmployeePath(tool: string): string {
    return tool === 'claude'
      ? ApiEndpoints.ADMIN_CLAUDE_SUPER_EMPLOYEE_MESSAGES
      : ApiEndpoints.ADMIN_CODEX_SUPER_EMPLOYEE_MESSAGES;
  }

  async superEmployeeInvoke(tool: string, message: string, mode: string): Promise<SuperEmployeeInvokeData> {
    const context: SuperEmployeeContext = {
      source: 'mobile_chat',
      client_surface: 'mobile'
    };
    if (mode === 'chat') {
      context.mode = 'chat';
    } else if (mode === 'code') {
      context.mode = 'code';
      context.mode_explicit = true;
    }
    const body: SuperEmployeeMessageBody = {
      message: message,
      body: message,
      context: context
    };
    const envelope = await this.request<SuperEmployeeInvokeData>(
      this.superEmployeePath(tool),
      http.RequestMethod.POST,
      body
    );
    return envelope.data || {};
  }

  async superEmployeeMessages(tool: string): Promise<SuperEmployeeMessageRow[]> {
    const envelope = await this.request<SuperEmployeeMessagesData>(
      `${this.superEmployeePath(tool)}?limit=80`,
      http.RequestMethod.GET
    );
    return envelope.data?.messages || [];
  }

  // ── relay 离线通路：绑定桌面执行端 + 经云中继派任务 ──
  // 6 位设备码绑定一台已配对桌面，返回 relay_id 供后续派任务。
  async relayConfirmCode(code: string): Promise<RelayConfirmCodeData> {
    const body: RelayConfirmCodeBody = { code: code.trim() };
    const envelope = await this.request<RelayConfirmCodeData>(
      ApiEndpoints.RELAY_MOBILE_CONFIRM_CODE,
      http.RequestMethod.POST,
      body
    );
    return envelope.data || {};
  }

  // 列出本账号已绑定的桌面执行端（用于登录后自动恢复 relay 绑定）。
  async relayDesktops(): Promise<RelayDesktop[]> {
    const envelope = await this.request<RelayDesktopsData>(
      ApiEndpoints.RELAY_MOBILE_DESKTOPS,
      http.RequestMethod.GET
    );
    return envelope.data?.items || [];
  }

  async relayCreateTask(relayId: string, kind: string, message: string, mode: string): Promise<RelayTask> {
    const context: RelayTaskContext = {
      source: 'mobile_chat',
      client_surface: 'mobile'
    };
    if (mode === 'chat') {
      context.mode = 'chat';
    } else if (mode === 'code') {
      context.mode = 'code';
      context.mode_explicit = true;
    }
    const body: RelayTaskCreateBody = {
      relay_id: relayId,
      kind: kind,
      payload: { message: message, context: context }
    };
    const envelope = await this.request<RelayTaskData>(
      ApiEndpoints.RELAY_TASKS,
      http.RequestMethod.POST,
      body
    );
    return envelope.data?.task || {};
  }

  async relayTaskStatus(taskId: string): Promise<RelayTask> {
    const path = ApiEndpoints.RELAY_TASKS_DETAIL.replace('{taskId}', taskId);
    const envelope = await this.request<RelayTaskData>(path, http.RequestMethod.GET);
    return envelope.data?.task || {};
  }

  // ── 审批流 ──
  async approvals(): Promise<ApprovalItem[]> {
    const envelope = await this.request<ApprovalItem[]>(ApiEndpoints.APPROVAL_REQUESTS, http.RequestMethod.GET);
    return envelope.data || [];
  }

  async approvalDetail(id: number): Promise<ApprovalDetail> {
    const path = ApiEndpoints.APPROVAL_DETAIL.replace('{id}', id.toString());
    const envelope = await this.request<ApprovalDetail>(path, http.RequestMethod.GET);
    return envelope.data || ({} as ApprovalDetail);
  }

  async approve(id: number, opinion: string): Promise<void> {
    const path = ApiEndpoints.APPROVAL_APPROVE.replace('{id}', id.toString());
    const body: ApprovalActionBody = { opinion: opinion };
    await this.request<Object>(path, http.RequestMethod.POST, body);
  }

  async reject(id: number, reason: string): Promise<void> {
    const path = ApiEndpoints.APPROVAL_REJECT.replace('{id}', id.toString());
    const body: ApprovalActionBody = { opinion: reason };
    await this.request<Object>(path, http.RequestMethod.POST, body);
  }

  // ── 客服 ──
  async csInfo(): Promise<CsInfo> {
    const envelope = await this.request<CsInfo>(ApiEndpoints.CS_INFO, http.RequestMethod.GET);
    return envelope.data || ({ title: '专属客服', subtitle: '在线', online: true } as CsInfo);
  }

  async csMessages(): Promise<ChatMessage[]> {
    const envelope = await this.request<ChatMessage[]>(ApiEndpoints.CS_MESSAGES, http.RequestMethod.GET);
    return envelope.data || [];
  }

  // 联系人固定区(按端 SSOT 派生)
  async contactsFixed(): Promise<MobileFixedContactsData> {
    const envelope = await this.request<MobileFixedContactsData>(
      ApiEndpoints.CONTACTS_FIXED, http.RequestMethod.GET);
    return envelope.data || ({ side: '', top: [], bottom: [] } as MobileFixedContactsData);
  }

  async csSend(message: string): Promise<ChatResponseData> {
    const body: ChatRequestBody = { message: message, session_id: 'cs' };
    const response = await this.rawRequest<ChatResponseData>('api/cs/chat', http.RequestMethod.POST, body);
    return response;
  }

  private async request<T>(path: string, method: http.RequestMethod, body?: object): Promise<MobileEnvelope<T>> {
    const response = await this.rawRequest<MobileEnvelope<T>>(path, method, body);
    if (response.success === false) {
      throw new Error(response.message || '请求失败');
    }
    return response;
  }

  private async rawRequest<T>(path: string, method: http.RequestMethod, body?: object): Promise<T> {
    const request = http.createHttp();
    const header: HeaderMap = {
      'Content-Type': 'application/json',
      'Accept': 'application/json'
    };
    if (this.accessToken.trim().length > 0) {
      header.Authorization = `Bearer ${this.accessToken.trim()}`;
    }
    try {
      const response = await request.request(this.resolveUrl(path), {
        method: method,
        header: header,
        extraData: body ? JSON.stringify(body) : undefined,
        expectDataType: http.HttpDataType.STRING,
        connectTimeout: 8000,
        readTimeout: 30000
      });
      const raw = typeof response.result === 'string' ? response.result : JSON.stringify(response.result);
      if (Number(response.responseCode) >= 400) {
        const message = MobileApiClient.errorMessage(raw, `HTTP ${response.responseCode}`);
        throw new Error(message);
      }
      return JSON.parse(raw) as T;
    } finally {
      request.destroy();
    }
  }

  private resolveUrl(path: string): string {
    const cleaned = path.startsWith('/') ? path.substring(1) : path;
    return `${this.baseUrl}${cleaned}`;
  }

  private static normalizeBaseUrl(value: string): string {
    let url = (value || '').trim();
    if (url.length === 0) {
      url = 'http://127.0.0.1:5000/';
    }
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      url = `http://${url}`;
    }
    return url.endsWith('/') ? url : `${url}/`;
  }

  private static errorMessage(raw: string, fallback: string): string {
    try {
      const parsed = JSON.parse(raw) as MobileEnvelope<object>;
      return parsed.message || fallback;
    } catch (_err) {
      return fallback;
    }
  }
}
