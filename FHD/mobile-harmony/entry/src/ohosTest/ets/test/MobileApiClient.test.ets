import { describe, it, expect } from '@ohos/hypium';
import { MobileApiClient } from '../../../../main/ets/api/MobileApiClient';

export default function mobileApiClientTest() {
  describe('MobileApiClient', () => {
    // ── normalizeBaseUrl（静态方法）──

    describe('normalizeBaseUrl', () => {
      it('emptyString_returnsDefaultLocalhost', 0, () => {
        const result = MobileApiClient['normalizeBaseUrl']('');
        expect(result).assertEqual('http://127.0.0.1:5000/');
      });

      it('undefinedString_returnsDefaultLocalhost', 0, () => {
        const result = MobileApiClient['normalizeBaseUrl']('');
        expect(result).assertEqual('http://127.0.0.1:5000/');
      });

      it('withHttpPrefix_addsTrailingSlash', 0, () => {
        const result = MobileApiClient['normalizeBaseUrl']('http://example.com');
        expect(result).assertEqual('http://example.com/');
      });

      it('withHttpsPrefix_addsTrailingSlash', 0, () => {
        const result = MobileApiClient['normalizeBaseUrl']('https://example.com');
        expect(result).assertEqual('https://example.com/');
      });

      it('withTrailingSlash_unchanged', 0, () => {
        const result = MobileApiClient['normalizeBaseUrl']('http://example.com/');
        expect(result).assertEqual('http://example.com/');
      });

      it('withoutProtocol_addsHttpPrefix', 0, () => {
        const result = MobileApiClient['normalizeBaseUrl']('example.com');
        expect(result).assertEqual('http://example.com/');
      });

      it('withPort_preservesPort', 0, () => {
        const result = MobileApiClient['normalizeBaseUrl']('http://192.168.1.1:8080');
        expect(result).assertEqual('http://192.168.1.1:8080/');
      });

      it('withWhitespace_trimsFirst', 0, () => {
        const result = MobileApiClient['normalizeBaseUrl']('  http://example.com  ');
        expect(result).assertEqual('http://example.com/');
      });
    });

    // ── errorMessage（静态方法）──

    describe('errorMessage', () => {
      it('validJsonWithMessage_returnsMessage', 0, () => {
        const raw = JSON.stringify({ success: false, message: 'Token expired' });
        const result = MobileApiClient['errorMessage'](raw, 'fallback');
        expect(result).assertEqual('Token expired');
      });

      it('validJsonWithoutMessage_returnsFallback', 0, () => {
        const raw = JSON.stringify({ success: false });
        const result = MobileApiClient['errorMessage'](raw, 'fallback');
        expect(result).assertEqual('fallback');
      });

      it('invalidJson_returnsFallback', 0, () => {
        const raw = 'not json at all';
        const result = MobileApiClient['errorMessage'](raw, 'fallback');
        expect(result).assertEqual('fallback');
      });

      it('emptyString_returnsFallback', 0, () => {
        const result = MobileApiClient['errorMessage']('', 'fallback');
        expect(result).assertEqual('fallback');
      });

      it('nullMessage_returnsFallback', 0, () => {
        const raw = JSON.stringify({ success: false, message: null });
        const result = MobileApiClient['errorMessage'](raw, 'fallback');
        expect(result).assertEqual('fallback');
      });

      it('emptyMessage_returnsFallback', 0, () => {
        const raw = JSON.stringify({ success: false, message: '' });
        const result = MobileApiClient['errorMessage'](raw, 'fallback');
        expect(result).assertEqual('fallback');
      });
    });
  });
}
