export interface PerformanceMetric {
  name: string;
  durationMs: number;
  status?: string;
  attributes?: Record<string, string>;
}

export class MobilePerformanceMetricNames {
  static readonly APP_COLD_START: string = 'mobile.app.cold_start';
  static readonly AUTH_LOGIN: string = 'mobile.auth.login';
  static readonly API_LATENCY: string = 'mobile.api.latency';
  static readonly SSE_FIRST_TOKEN: string = 'mobile.sse.first_token';
  static readonly WEBSOCKET_RECONNECT: string = 'mobile.websocket.reconnect';
  static readonly SCREEN_RENDER: string = 'mobile.screen.render';
  static readonly CRASH_NONFATAL: string = 'mobile.crash.nonfatal';
}

export class PerformanceMonitor {
  private static instance: PerformanceMonitor | null = null;

  static getInstance(): PerformanceMonitor {
    if (PerformanceMonitor.instance === null) {
      PerformanceMonitor.instance = new PerformanceMonitor();
    }
    return PerformanceMonitor.instance;
  }

  startTrace(): number {
    return Date.now();
  }

  recordDuration(name: string, startedAt: number, status: string = 'ok', attributes?: Record<string, string>): void {
    const durationMs = Math.max(0, Date.now() - startedAt);
    this.record({ name, durationMs, status, attributes });
  }

  record(metric: PerformanceMetric): void {
    const payload: PerformanceMetric = {
      name: metric.name,
      durationMs: Math.max(0, Math.round(metric.durationMs)),
      status: metric.status || 'ok',
      attributes: metric.attributes || {}
    };
    console.info('mobile_perf ' + JSON.stringify(payload));
  }
}
