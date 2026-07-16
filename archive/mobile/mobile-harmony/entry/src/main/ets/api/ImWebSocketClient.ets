// IM 实时 WebSocket 客户端(对标 Android core/im/ImWebSocketClient.kt)。
//
// 连接 /ws/im?session_id=<sid>(以会话 ID 鉴权,避免客户端自报 user_id)。
// 含指数退避重连(5s→10s→...→5min 封顶)与 30s 心跳 ping。
// 接收服务端 {"type":"message","message":{...}} 实时推送。

import webSocket from '@ohos.net.webSocket';

export type ImConnStatus = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed';

export interface ImInbound {
  type?: string;
  conversation_id?: number;
  message?: ImInboundMessage;
}

export interface ImInboundMessage {
  id?: number;
  conversation_id?: number;
  sender_id?: number;
  content?: string;
  body?: string;
  created_at?: string;
}

const HEARTBEAT_MS: number = 30000;
const BACKOFF_START_MS: number = 5000;
const BACKOFF_MAX_MS: number = 300000;

export class ImWebSocketClient {
  private wsUrl: string;
  private ws: webSocket.WebSocket | null = null;
  private onMessage: (msg: ImInbound) => void = () => {};
  private onStatus: (status: ImConnStatus) => void = () => {};
  private backoffMs: number = BACKOFF_START_MS;
  private heartbeatTimer: number = -1;
  private reconnectTimer: number = -1;
  private active: boolean = false;

  constructor(baseUrl: string, sessionId: string) {
    this.wsUrl = ImWebSocketClient.toWsUrl(baseUrl, sessionId);
  }

  connect(onMessage: (msg: ImInbound) => void, onStatus: (status: ImConnStatus) => void): void {
    this.onMessage = onMessage;
    this.onStatus = onStatus;
    this.active = true;
    this.open();
  }

  private open(): void {
    if (!this.active) {
      return;
    }
    this.onStatus('connecting');
    const ws: webSocket.WebSocket = webSocket.createWebSocket();
    this.ws = ws;

    ws.on('open', () => {
      this.backoffMs = BACKOFF_START_MS;
      this.onStatus('open');
      this.startHeartbeat();
    });
    ws.on('message', (_err: Object, data: string | ArrayBuffer) => {
      if (typeof data !== 'string') {
        return;
      }
      const text: string = data.trim();
      if (text.length === 0 || text === '{"type":"pong"}') {
        return;
      }
      try {
        const parsed: ImInbound = JSON.parse(text) as ImInbound;
        if ((parsed.type || '') === 'message') {
          this.onMessage(parsed);
        }
      } catch (_e) {
        // 非 JSON 帧:忽略
      }
    });
    ws.on('close', () => {
      this.stopHeartbeat();
      this.scheduleReconnect();
    });
    ws.on('error', () => {
      this.stopHeartbeat();
      this.scheduleReconnect();
    });

    ws.connect(this.wsUrl, (err: Object, _ok: boolean) => {
      if (err) {
        this.scheduleReconnect();
      }
    });
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (this.ws !== null) {
        this.ws.send('ping', (_e: Object, _ok: boolean) => {});
      }
    }, HEARTBEAT_MS);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer !== -1) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = -1;
    }
  }

  private scheduleReconnect(): void {
    if (!this.active) {
      this.onStatus('closed');
      return;
    }
    if (this.reconnectTimer !== -1) {
      return;
    }
    this.onStatus('reconnecting');
    const delay: number = this.backoffMs;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = -1;
      this.backoffMs = Math.min(this.backoffMs * 2, BACKOFF_MAX_MS);
      this.open();
    }, delay);
  }

  disconnect(): void {
    this.active = false;
    this.stopHeartbeat();
    if (this.reconnectTimer !== -1) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = -1;
    }
    if (this.ws !== null) {
      this.ws.close((_e: Object, _ok: boolean) => {});
      this.ws = null;
    }
    this.onStatus('closed');
  }

  private static toWsUrl(baseUrl: string, sessionId: string): string {
    let url: string = (baseUrl || '').trim();
    if (url.startsWith('https://')) {
      url = 'wss://' + url.substring('https://'.length);
    } else if (url.startsWith('http://')) {
      url = 'ws://' + url.substring('http://'.length);
    } else if (url.length > 0) {
      url = 'ws://' + url;
    } else {
      url = 'ws://127.0.0.1:5000/';
    }
    if (!url.endsWith('/')) {
      url = url + '/';
    }
    return `${url}ws/im?session_id=${encodeURIComponent(sessionId)}`;
  }
}
