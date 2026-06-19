import { apiFetch } from '@/utils/apiBase';

export interface PairingPayload {
  host: string;
  port: number;
  nonce: string;
  shortCode: string; // 6 位设备码，v3 优先为服务器中继码
  exp: number;
  relay_id?: string;
  relay_base_url?: string;
  qr_json?: Record<string, unknown>;
  relay?: Record<string, unknown>;
}

export interface HostDiscoverHint {
  api_port?: number;
  instance_name?: string;
}

async function readJson<T>(response: Response): Promise<T> {
  const data = (await response.json()) as { success?: boolean; data?: T; message?: string };
  if (!response.ok || data.success === false) {
    throw new Error(data.message || response.statusText || '请求失败');
  }
  return (data.data ?? data) as T;
}

export async function fetchHostDiscoverHint(): Promise<HostDiscoverHint> {
  const response = await apiFetch('/api/mobile/v1/host/discover-hint');
  return readJson<HostDiscoverHint>(response);
}

export async function issueMobilePairing(host: string, port: number): Promise<PairingPayload> {
  const response = await apiFetch('/api/mobile/v1/pairing/issue', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ host, port }),
  });
  return readJson<PairingPayload>(response);
}

export async function loadDesktopPairingPayload(): Promise<PairingPayload | null> {
  const desktop = window.xcagiDesktop;
  if (!desktop?.getPairingQrPayload) return null;
  const raw = await desktop.getPairingQrPayload();
  if (!raw) return null;
  const parsed = JSON.parse(String(raw)) as Partial<PairingPayload>;
  const qrJson = typeof parsed.qr_json === 'object' && parsed.qr_json ? parsed.qr_json as Record<string, unknown> : undefined;
  if (!parsed.nonce && !qrJson) return null;
  return {
    host: String(parsed.host || '127.0.0.1'),
    port: Number(parsed.port || 5000),
    nonce: String(parsed.nonce || ''),
    shortCode: String(parsed.shortCode || ''),
    exp: Number(parsed.exp || Math.floor(Date.now() / 1000) + 300),
    relay_id: typeof parsed.relay_id === 'string' ? parsed.relay_id : undefined,
    relay_base_url: typeof parsed.relay_base_url === 'string' ? parsed.relay_base_url : undefined,
    qr_json: qrJson,
    relay: typeof parsed.relay === 'object' && parsed.relay ? parsed.relay as Record<string, unknown> : undefined,
  };
}

export function resolvePairingHost(): string {
  if (typeof window === 'undefined') return '127.0.0.1';
  const host = (window.location.hostname || '').trim();
  if (host && host !== 'localhost' && host !== '127.0.0.1') return host;
  return '127.0.0.1';
}

/** QR 内嵌短码，同时保留 host/port 作为首次绑定的局域网直连兜底。 */
export function buildPairingQrText(payload: PairingPayload): string {
  if (payload.qr_json && Object.keys(payload.qr_json).length > 0) {
    return JSON.stringify(payload.qr_json);
  }
  return JSON.stringify({
    v: 2,
    t: payload.shortCode || payload.nonce,
    host: payload.host,
    port: payload.port,
    nonce: payload.nonce,
  });
}

export function resolvePairingPortHint(fallback = 5000): number {
  if (typeof window !== 'undefined') {
    const pagePort = Number(window.location.port || 0);
    if (pagePort === 5100 || pagePort === 5000) return pagePort;
  }
  const envPort = Number(import.meta.env.VITE_FHD_PORT || import.meta.env.VITE_API_PORT || 0);
  if (envPort > 0) return envPort;
  return fallback;
}
