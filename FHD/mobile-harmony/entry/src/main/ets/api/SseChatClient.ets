// SSE 流式对话客户端(对标 Android SseChatClient.kt)。
//
// 用 @ohos.net.http 的 requestInStream + on('dataReceive') 逐块接收
// text/event-stream,解析 `data: {json}\n\n` 帧,按 type 分发 token/done/error。
// 端点:POST /api/ai/chat/stream(app/.../conversation/compat_routes.py)。

import http from '@ohos.net.http';
import util from '@ohos.util';
import { ApiEndpoints } from './ApiEndpoints';

export interface SseCallbacks {
  onToken: (text: string) => void;
  onDone: (reply: string) => void;
  onError: (message: string) => void;
}

interface SseRequestBody {
  message: string;
}

interface SseResultData {
  reply?: string;
  content?: string;
  message?: string;
}

interface SseResult {
  response?: string;
  reply?: string;
  message?: string;
  data?: SseResultData;
}

interface SseEvent {
  type?: string;
  text?: string;
  message?: string;
  result?: SseResult;
}

export class SseChatClient {
  private baseUrl: string;
  private accessToken: string;

  constructor(baseUrl: string, accessToken: string = '') {
    this.baseUrl = SseChatClient.normalizeBaseUrl(baseUrl);
    this.accessToken = accessToken;
  }

  /** 发起流式请求;token 逐字回调,结束时 onDone,出错 onError。 */
  stream(message: string, callbacks: SseCallbacks): Promise<void> {
    const httpRequest = http.createHttp();
    const decoder: util.TextDecoder = util.TextDecoder.create('utf-8');
    let buffer: string = '';

    httpRequest.on('dataReceive', (data: ArrayBuffer) => {
      const chunk: string = decoder.decodeToString(new Uint8Array(data), { stream: true });
      buffer = this.drainFrames(buffer + chunk, callbacks);
    });

    return new Promise<void>((resolve: () => void, reject: (err: Error) => void) => {
      httpRequest.on('dataEnd', () => {
        httpRequest.off('dataReceive');
        httpRequest.off('dataEnd');
        httpRequest.destroy();
        resolve();
      });

      const header: Record<string, string> = {
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream'
      };
      if (this.accessToken.trim().length > 0) {
        header.Authorization = `Bearer ${this.accessToken.trim()}`;
      }
      const body: SseRequestBody = { message: message };
      httpRequest.requestInStream(this.resolveUrl(ApiEndpoints.AI_CHAT_STREAM), {
        method: http.RequestMethod.POST,
        header: header,
        extraData: JSON.stringify(body),
        connectTimeout: 8000,
        readTimeout: 60000
      }).then((code: number) => {
        if (Number(code) >= 400) {
          httpRequest.off('dataReceive');
          httpRequest.off('dataEnd');
          httpRequest.destroy();
          reject(new Error(`HTTP ${code}`));
        }
      }).catch((err: Object) => {
        httpRequest.off('dataReceive');
        httpRequest.off('dataEnd');
        httpRequest.destroy();
        reject(new Error((err as Error).message || '流式请求失败'));
      });
    });
  }

  private drainFrames(buffer: string, cb: SseCallbacks): string {
    let working: string = buffer;
    let idx: number = working.indexOf('\n\n');
    while (idx >= 0) {
      const frame: string = working.substring(0, idx);
      working = working.substring(idx + 2);
      this.handleFrame(frame, cb);
      idx = working.indexOf('\n\n');
    }
    return working;
  }

  private handleFrame(frame: string, cb: SseCallbacks): void {
    const lines: string[] = frame.split('\n');
    for (const line of lines) {
      const trimmed: string = line.trim();
      if (!trimmed.startsWith('data:')) {
        continue;
      }
      const jsonStr: string = trimmed.substring(5).trim();
      if (jsonStr.length === 0 || jsonStr === '[DONE]') {
        continue;
      }
      let ev: SseEvent;
      try {
        ev = JSON.parse(jsonStr) as SseEvent;
      } catch (_e) {
        continue;
      }
      const type: string = ev.type || '';
      if (type === 'token') {
        cb.onToken(ev.text || '');
      } else if (type === 'done') {
        cb.onDone(SseChatClient.extractReply(ev.result));
      } else if (type === 'error') {
        cb.onError(ev.message || '流式对话失败');
      }
    }
  }

  private static extractReply(result?: SseResult): string {
    if (!result) {
      return '';
    }
    if (result.reply !== undefined && result.reply.length > 0) {
      return result.reply;
    }
    if (result.response !== undefined && result.response.length > 0) {
      return result.response;
    }
    if (result.data && result.data.reply !== undefined && result.data.reply.length > 0) {
      return result.data.reply;
    }
    if (result.message !== undefined && result.message.length > 0) {
      return result.message;
    }
    return '';
  }

  private resolveUrl(path: string): string {
    const cleaned: string = path.startsWith('/') ? path.substring(1) : path;
    return `${this.baseUrl}${cleaned}`;
  }

  private static normalizeBaseUrl(value: string): string {
    let url: string = (value || '').trim();
    if (url.length === 0) {
      url = 'http://127.0.0.1:5000/';
    }
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      url = `http://${url}`;
    }
    return url.endsWith('/') ? url : `${url}/`;
  }
}
