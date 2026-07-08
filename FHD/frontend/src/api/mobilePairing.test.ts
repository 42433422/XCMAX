import { describe, expect, it } from 'vitest';
import { buildPairingQrText, normalizePairingPayload, type PairingPayload } from './mobilePairing';

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

  it('normalizePairingPayload prefers relay pairing_code for QR and display', () => {
    const payload: PairingPayload = {
      host: '192.168.1.20',
      port: 17500,
      nonce: 'nonce-abc',
      shortCode: '111111',
      exp: 1_800_000_000,
      relay: { pairing_code: '222222' },
      qr_json: { kind: 'xcagi_pairing', t: '111111', code: '111111' },
    };
    const normalized = normalizePairingPayload(payload);
    expect(normalized.shortCode).toBe('222222');
    expect(JSON.parse(buildPairingQrText(normalized)).t).toBe('222222');
    expect(normalized.qr_json?.code).toBe('222222');
  });
});
