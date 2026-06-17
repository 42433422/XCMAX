import { describe, expect, it } from 'vitest';
import { buildPairingQrText, type PairingPayload } from './mobilePairing';

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
});
