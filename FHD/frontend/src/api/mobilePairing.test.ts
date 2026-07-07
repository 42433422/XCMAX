import { describe, expect, it, vi } from 'vitest';
import { buildPairingQrText, applyDevProxyReachablePort, type PairingPayload } from './mobilePairing';

describe('mobilePairing', () => {
  it('builds v2 QR text with host, port, nonce, and short code', () => {
    const payload: PairingPayload = {
      host: '192.168.1.20',
      port: 5100,
      nonce: 'nonce-abc',
      shortCode: '123456',
      exp: 1_800_000_000,
    };

    expect(JSON.parse(buildPairingQrText(payload))).toEqual({
      v: 2,
      t: '123456',
      host: '192.168.1.20',
      port: 5100,
      nonce: 'nonce-abc',
    });
  });

  it('rewrites loopback API port to vite proxy for LAN phones', () => {
    const payload: PairingPayload = {
      host: '192.168.10.2',
      port: 17500,
      nonce: 'nonce-abc',
      shortCode: '123456',
      exp: 1_800_000_000,
    };
    vi.stubGlobal('window', {
      location: { hostname: '127.0.0.1', port: '5011' },
    } as Window & typeof globalThis);
    const reachable = applyDevProxyReachablePort(payload);
    expect(reachable.port).toBe(5011);
    expect(reachable.host).toBe('192.168.10.2');
    expect(JSON.parse(buildPairingQrText(reachable))).toEqual({
      v: 2,
      t: '123456',
      host: '192.168.10.2',
      port: 5011,
      nonce: 'nonce-abc',
    });
    vi.unstubAllGlobals();
  });
});
