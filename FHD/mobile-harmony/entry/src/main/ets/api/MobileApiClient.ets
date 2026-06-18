import http from '@ohos.net.http';
import {
  ChatResponseData,
  MobileEnvelope,
  MobileHomeData,
  MobileLoginData,
  MobileMeData,
  MobileModsData,
  PairingExchangeData
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

  async login(username: string, password: string): Promise<MobileLoginData> {
    const body: LoginRequestBody = {
      username: username.trim(),
      password: password,
      account_kind: 'enterprise'
    };
    const envelope = await this.request<MobileLoginData>(
      'api/mobile/v1/auth/login',
      http.RequestMethod.POST,
      body
    );
    return envelope.data || {};
  }

  async me(): Promise<MobileMeData> {
    const envelope = await this.request<MobileMeData>('api/mobile/v1/me', http.RequestMethod.GET);
    return envelope.data || {};
  }

  async home(): Promise<MobileHomeData> {
    const envelope = await this.request<MobileHomeData>('api/mobile/v1/home', http.RequestMethod.GET);
    return envelope.data || {};
  }

  async mods(): Promise<MobileModsData> {
    const envelope = await this.request<MobileModsData>('api/mobile/v1/mods', http.RequestMethod.GET);
    return envelope.data || {};
  }

  async pairingExchange(code: string): Promise<PairingExchangeData> {
    const body: PairingRequestBody = {
      code: code.trim()
    };
    const envelope = await this.request<PairingExchangeData>(
      'api/mobile/v1/pairing/exchange',
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
