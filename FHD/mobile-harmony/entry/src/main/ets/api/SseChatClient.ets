import http from '@ohos.net.http';
import buffer from '@ohos.buffer';

// 鸿蒙端 SSE 流式对话客户端，对齐 Android core/network/SseChatClient.kt：
// - POST api/ai/chat/stream，Accept: text/event-stream；
// - 解析 data: {type:token|done|error} 事件，token 增量回调、done 收尾、error 判定可重试；
// - 3 次重试：连接失败 / 5xx / 后端 LLM 上游瞬时错误（SSL 握手超时等）可重试，已开始输出则不重试；
// - 按 \n 字节分帧再解码，避免中文 UTF-8 字符被分块边界截断。

export interface SseRecentMessage {
  role: string;
  content: string;
}

export interface SseCallbacks {
  onToken: (text: string) => void;
  onDone: (finalText: string) => void;
  onError: (message: string) => void;
}

interface SseContext {
  recent_messages?: SseRecentMessage[];
  industry?: string;
}

interface SseChatBody {
  message: string;
  source: string;
  mode: string;
  user_id?: string;
  context?: SseContext;
}

interface SseDoneResult {
  response?: string;
}

interface SseEvent {
  type?: string;
  text?: string;
  message?: string;
  result?: SseDoneResult;
}

interface SseAttemptResult {
  terminal: boolean;
  error: string;
}

const MAX_ATTEMPTS = 3;
const NEWLINE = 0x0A;

export class SseChatClient {
  async streamChat(
    baseUrl: string,
    message: string,
    bearer: string,
    userId: number,
    recentMessages: SseRecentMessage[],
    industry: string,
    cb: SseCallbacks
  ): Promise<void> {
    const url = SseChatClient.join(baseUrl, 'api/ai/chat/stream');
    const body: SseChatBody = { message: message, source: 'pro', mode: 'professional' };
    if (userId > 0) {
      body.user_id = userId.toString();
    }
    const ctx: SseContext = {};
    let hasCtx = false;
    if (recentMessages.length > 0) {
      ctx.recent_messages = recentMessages;
      hasCtx = true;
    }
    if (industry.trim().length > 0) {
      ctx.industry = industry.trim();
      hasCtx = true;
    }
    if (hasCtx) {
      body.context = ctx;
    }
    const bodyJson = JSON.stringify(body);

    let lastError = '连接失败';
    for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
      const result = await this.attemptStream(url, bodyJson, bearer, userId, cb);
      if (result.terminal) {
        return;
      }
      lastError = result.error;
      if (attempt < MAX_ATTEMPTS) {
        await SseChatClient.delay(800 * attempt);
      }
    }
    cb.onError(lastError);
  }

  private attemptStream(
    url: string,
    bodyJson: string,
    bearer: string,
    userId: number,
    cb: SseCallbacks
  ): Promise<SseAttemptResult> {
    return new Promise<SseAttemptResult>((resolve: (value: SseAttemptResult) => void) => {
      const httpRequest = http.createHttp();
      let settled = false;
      let started = false;
      let accum = '';
      let byteBuf: number[] = [];

      const finish = (res: SseAttemptResult): void => {
        if (settled) {
          return;
        }
        settled = true;
        try {
          httpRequest.off('dataReceive');
          httpRequest.off('dataEnd');
        } catch (e) {
        }
        httpRequest.destroy();
        resolve(res);
      };

      httpRequest.on('dataReceive', (chunk: ArrayBuffer) => {
        const bytes = new Uint8Array(chunk);
        for (let i = 0; i < bytes.length; i++) {
          byteBuf.push(bytes[i]);
        }
        let nl = byteBuf.indexOf(NEWLINE);
        while (nl >= 0 && !settled) {
          const lineBytes = byteBuf.slice(0, nl);
          byteBuf = byteBuf.slice(nl + 1);
          const line = (lineBytes.length > 0 ? buffer.from(lineBytes).toString('utf-8') : '').trim();
          if (line.startsWith('data:')) {
            const payload = line.substring(5).trim();
            if (payload.length > 0 && payload !== '[DONE]') {
              let evt: SseEvent | null = null;
              try {
                evt = JSON.parse(payload) as SseEvent;
              } catch (e) {
                evt = null;
              }
              if (evt !== null) {
                const type = evt.type ?? '';
                if (type === 'token') {
                  const t = evt.text ?? '';
                  if (t.length > 0) {
                    started = true;
                    accum += t;
                    cb.onToken(t);
                  }
                } else if (type === 'done') {
                  const r = evt.result;
                  const resp = r !== undefined && r !== null ? (r.response ?? '') : '';
                  cb.onDone(resp.length > 0 ? resp : accum);
                  finish({ terminal: true, error: '' });
                } else if (type === 'error') {
                  const msg = evt.message ?? 'stream error';
                  if (!started && SseChatClient.isRetryable(msg)) {
                    finish({ terminal: false, error: msg });
                  } else {
                    cb.onError(msg);
                    finish({ terminal: true, error: msg });
                  }
                }
              }
            }
          }
          nl = byteBuf.indexOf(NEWLINE);
        }
      });

      httpRequest.on('dataEnd', () => {
        if (!settled) {
          cb.onDone(accum.length > 0 ? accum : '（无回复）');
          finish({ terminal: true, error: '' });
        }
      });

      const header: Record<string, string> = {
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
        'X-XCAGI-Client': 'harmony'
      };
      const trimmedBearer = bearer.trim();
      if (trimmedBearer.length > 0) {
        header['Authorization'] = trimmedBearer.startsWith('Bearer ') ? trimmedBearer : `Bearer ${trimmedBearer}`;
      }
      if (userId > 0) {
        header['X-User-ID'] = userId.toString();
      }
      const options: http.HttpRequestOptions = {
        method: http.RequestMethod.POST,
        header: header,
        extraData: bodyJson,
        expectDataType: http.HttpDataType.ARRAY_BUFFER,
        connectTimeout: 8000,
        readTimeout: 120000
      };

      httpRequest.requestInStream(url, options).then((statusCode: number) => {
        if (statusCode >= 400) {
          if (statusCode >= 500 && !started) {
            finish({ terminal: false, error: `HTTP ${statusCode}` });
          } else {
            if (started) {
              cb.onDone(accum);
            } else {
              cb.onError(`HTTP ${statusCode}`);
            }
            finish({ terminal: true, error: `HTTP ${statusCode}` });
          }
        }
      }).catch((err: Object) => {
        const msg = SseChatClient.errText(err);
        if (started) {
          cb.onDone(accum.length > 0 ? accum : '（连接中断）');
          finish({ terminal: true, error: msg });
        } else {
          finish({ terminal: false, error: msg });
        }
      });
    });
  }

  private static isRetryable(msg: string): boolean {
    const lower = msg.toLowerCase();
    return lower.includes('_ssl.c') || lower.includes('handshake') || lower.includes('timeout') ||
      lower.includes('timed out') || lower.includes('upstream') || lower.includes('502') ||
      lower.includes('504') || lower.includes('上游');
  }

  private static errText(err: Object): string {
    const e = err as Error;
    const m = e !== undefined && e !== null ? e.message : '';
    return m !== undefined && m !== null && m.length > 0 ? m : '连接失败';
  }

  private static join(baseUrl: string, path: string): string {
    let base = (baseUrl || '').trim();
    if (base.length === 0) {
      base = 'http://127.0.0.1:5000/';
    }
    if (!base.endsWith('/')) {
      base = `${base}/`;
    }
    const cleaned = path.startsWith('/') ? path.substring(1) : path;
    return `${base}${cleaned}`;
  }

  private static delay(ms: number): Promise<void> {
    return new Promise<void>((resolve: () => void) => {
      setTimeout(() => {
        resolve();
      }, ms);
    });
  }
}
