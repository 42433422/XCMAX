import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  isApiFetchTimeoutError,
  getApiBase,
  apiUrl,
  getClientModsUiOffHeader,
  getActiveExtensionModHeaders,
  apiFetch,
  pushClientModsOffState,
  syncClientModsStateToBackend,
  readClientModsOffState,
  DEFAULT_MOD_API_TIMEOUT_MS,
  MOD_PROBE_API_TIMEOUT_MS,
} from './apiBase';

// Mock 依赖模块
vi.mock('./xcagiStorageKeys', () => ({
  readActiveExtensionModIdFromStorage: vi.fn(() => ''),
}));

vi.mock('./csrfCookie', () => ({
  readCsrfTokenFromCookie: vi.fn(() => null),
  shouldAttachCsrfHeader: vi.fn(() => false),
}));

import { readActiveExtensionModIdFromStorage } from './xcagiStorageKeys';

describe('apiBase', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    // 重置 window.__XCMAX_API_BASE__
    (window as unknown as { __XCMAX_API_BASE__?: unknown }).__XCMAX_API_BASE__ = undefined;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('常量', () => {
    it('DEFAULT_MOD_API_TIMEOUT_MS 为 90000', () => {
      expect(DEFAULT_MOD_API_TIMEOUT_MS).toBe(90_000);
    });

    it('MOD_PROBE_API_TIMEOUT_MS 为 8000', () => {
      expect(MOD_PROBE_API_TIMEOUT_MS).toBe(8_000);
    });
  });

  describe('isApiFetchTimeoutError', () => {
    it('识别 DOMException AbortError 含 apiFetch timeout', () => {
      const err = new DOMException('apiFetch timeout after 1000ms', 'AbortError');
      expect(isApiFetchTimeoutError(err)).toBe(true);
    });

    it('识别 Error AbortError 含 apiFetch timeout', () => {
      const err = new Error('apiFetch timeout');
      err.name = 'AbortError';
      expect(isApiFetchTimeoutError(err)).toBe(true);
    });

    it('普通 AbortError 返回 false', () => {
      const err = new DOMException('user aborted', 'AbortError');
      expect(isApiFetchTimeoutError(err)).toBe(false);
    });

    it('普通 Error 返回 false', () => {
      expect(isApiFetchTimeoutError(new Error('network'))).toBe(false);
    });

    it('非 Error 类型返回 false', () => {
      expect(isApiFetchTimeoutError(null)).toBe(false);
      expect(isApiFetchTimeoutError(undefined)).toBe(false);
      expect(isApiFetchTimeoutError('string')).toBe(false);
      expect(isApiFetchTimeoutError(123)).toBe(false);
    });
  });

  describe('getApiBase', () => {
    it('window 未定义时返回空字符串（SSR 场景）', () => {
      // jsdom 中 window 已定义，此测试验证默认情况
      expect(typeof getApiBase()).toBe('string');
    });

    it('注入 loopback 地址返回空字符串', () => {
      (window as unknown as { __XCMAX_API_BASE__?: unknown }).__XCMAX_API_BASE__ = 'http://127.0.0.1:5000';
      expect(getApiBase()).toBe('');
    });

    it('注入 localhost 地址返回空字符串', () => {
      (window as unknown as { __XCMAX_API_BASE__?: unknown }).__XCMAX_API_BASE__ = 'http://localhost:5000';
      expect(getApiBase()).toBe('');
    });

    it('注入正常地址返回去尾斜杠的地址', () => {
      (window as unknown as { __XCMAX_API_BASE__?: unknown }).__XCMAX_API_BASE__ = 'https://api.example.com/';
      expect(getApiBase()).toBe('https://api.example.com');
    });

    it('注入空白字符串返回空', () => {
      (window as unknown as { __XCMAX_API_BASE__?: unknown }).__XCMAX_API_BASE__ = '   ';
      expect(getApiBase()).toBe('');
    });

    it('注入非字符串返回空', () => {
      (window as unknown as { __XCMAX_API_BASE__?: unknown }).__XCMAX_API_BASE__ = 123;
      expect(getApiBase()).toBe('');
    });

    it('注入带尾斜杠的正常地址会被裁剪', () => {
      (window as unknown as { __XCMAX_API_BASE__?: unknown }).__XCMAX_API_BASE__ = 'https://api.example.com/fhd-api/';
      expect(getApiBase()).toBe('https://api.example.com/fhd-api');
    });
  });

  describe('apiUrl', () => {
    it('路径以 / 开头时直接拼接', () => {
      (window as unknown as { __XCMAX_API_BASE__?: unknown }).__XCMAX_API_BASE__ = 'https://api.example.com';
      expect(apiUrl('/api/users')).toBe('https://api.example.com/api/users');
    });

    it('路径不以 / 开头时补 /', () => {
      (window as unknown as { __XCMAX_API_BASE__?: unknown }).__XCMAX_API_BASE__ = 'https://api.example.com';
      expect(apiUrl('api/users')).toBe('https://api.example.com/api/users');
    });

    it('无 base 时返回相对路径', () => {
      (window as unknown as { __XCMAX_API_BASE__?: unknown }).__XCMAX_API_BASE__ = undefined;
      expect(apiUrl('/api/users')).toBe('/api/users');
    });

    it('无 base 时路径不以 / 开头补 /', () => {
      (window as unknown as { __XCMAX_API_BASE__?: unknown }).__XCMAX_API_BASE__ = undefined;
      expect(apiUrl('api/users')).toBe('/api/users');
    });
  });

  describe('getClientModsUiOffHeader', () => {
    it('localStorage 为 1 时返回 header', () => {
      localStorage.setItem('xcagi_client_mods_ui_off', '1');
      expect(getClientModsUiOffHeader()).toEqual({ 'X-Client-Mods-Off': '1' });
    });

    it('localStorage 为 0 时返回空对象', () => {
      localStorage.setItem('xcagi_client_mods_ui_off', '0');
      expect(getClientModsUiOffHeader()).toEqual({});
    });

    it('localStorage 无值时返回空对象', () => {
      expect(getClientModsUiOffHeader()).toEqual({});
    });

    it('localStorage 抛错时返回空对象', () => {
      const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('access denied');
      });
      expect(getClientModsUiOffHeader()).toEqual({});
      spy.mockRestore();
    });
  });

  describe('getActiveExtensionModHeaders', () => {
    it('跳过 /api/auth/ 前缀路径', () => {
      expect(getActiveExtensionModHeaders('/api/auth/login')).toEqual({});
    });

    it('跳过 /api/platform-shell/ 前缀路径', () => {
      expect(getActiveExtensionModHeaders('/api/platform-shell/xxx')).toEqual({});
    });

    it('跳过 /api/debug/ 前缀路径', () => {
      expect(getActiveExtensionModHeaders('/api/debug/info')).toEqual({});
    });

    it('空 url 默认附加 header', () => {
      vi.mocked(readActiveExtensionModIdFromStorage).mockReturnValue('mod-123');
      expect(getActiveExtensionModHeaders('')).toEqual({ 'X-XCAGI-Active-Mod-Id': 'mod-123' });
    });

    it('无 mod id 时返回空对象', () => {
      vi.mocked(readActiveExtensionModIdFromStorage).mockReturnValue('');
      expect(getActiveExtensionModHeaders('/api/users')).toEqual({});
    });

    it('有 mod id 且非跳过路径时返回 header', () => {
      vi.mocked(readActiveExtensionModIdFromStorage).mockReturnValue('mod-456');
      expect(getActiveExtensionModHeaders('/api/users')).toEqual({ 'X-XCAGI-Active-Mod-Id': 'mod-456' });
    });

    it('完整 URL 解析 pathname 后判断', () => {
      vi.mocked(readActiveExtensionModIdFromStorage).mockReturnValue('mod-789');
      expect(getActiveExtensionModHeaders('https://example.com/api/auth/login')).toEqual({});
      expect(getActiveExtensionModHeaders('https://example.com/api/users')).toEqual({
        'X-XCAGI-Active-Mod-Id': 'mod-789',
      });
    });

    it('readActiveExtensionModIdFromStorage 抛错时返回空对象', () => {
      vi.mocked(readActiveExtensionModIdFromStorage).mockImplementation(() => {
        throw new Error('storage error');
      });
      expect(getActiveExtensionModHeaders('/api/users')).toEqual({});
    });

    it('URL 解析失败时默认附加 header', () => {
      vi.mocked(readActiveExtensionModIdFromStorage).mockReturnValue('mod-abc');
      // 传入无法解析的 URL 字符串
      expect(getActiveExtensionModHeaders(':::invalid:::')).toEqual({
        'X-XCAGI-Active-Mod-Id': 'mod-abc',
      });
    });
  });

  describe('readClientModsOffState', () => {
    it('localStorage 为 1 时返回 true', () => {
      localStorage.setItem('xcagi_client_mods_ui_off', '1');
      expect(readClientModsOffState()).toBe(true);
    });

    it('localStorage 为其他值时返回 false', () => {
      localStorage.setItem('xcagi_client_mods_ui_off', '0');
      expect(readClientModsOffState()).toBe(false);
    });

    it('localStorage 无值时返回 false', () => {
      expect(readClientModsOffState()).toBe(false);
    });
  });

  describe('apiFetch', () => {
    it('调用 fetch 并返回 Response', async () => {
      const mockResponse = new Response('{}', { status: 200 });
      const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValue(mockResponse);

      const res = await apiFetch('/api/test');
      expect(res).toBe(mockResponse);
      expect(fetchSpy).toHaveBeenCalled();
    });

    it('http 开头的 url 直接使用', async () => {
      const mockResponse = new Response('{}', { status: 200 });
      const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValue(mockResponse);

      await apiFetch('https://example.com/api/test');
      const callArgs = fetchSpy.mock.calls[0];
      expect(String(callArgs[0])).toContain('https://example.com/api/test');
    });

    it('传入 Headers 对象时正确合并', async () => {
      const mockResponse = new Response('{}', { status: 200 });
      const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValue(mockResponse);

      const headers = new Headers({ 'X-Custom': 'value' });
      await apiFetch('/api/test', { headers });
      const callInit = fetchSpy.mock.calls[0][1] as RequestInit;
      const headersObj = callInit.headers as Record<string, string>;
      // Headers 对象通过 entries() 转换，键名可能被小写
      const hasCustom = Object.keys(headersObj).some(
        (k) => k.toLowerCase() === 'x-custom' && headersObj[k] === 'value'
      );
      expect(hasCustom).toBe(true);
    });

    it('传入普通对象 headers 时合并', async () => {
      const mockResponse = new Response('{}', { status: 200 });
      const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValue(mockResponse);

      await apiFetch('/api/test', { headers: { 'X-Obj': 'val' } });
      const callInit = fetchSpy.mock.calls[0][1] as RequestInit;
      expect((callInit.headers as Record<string, string>)['X-Obj']).toBe('val');
    });

    it('credentials 始终为 include', async () => {
      const mockResponse = new Response('{}', { status: 200 });
      const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValue(mockResponse);

      await apiFetch('/api/test');
      const callInit = fetchSpy.mock.calls[0][1] as RequestInit;
      expect(callInit.credentials).toBe('include');
    });

    it('默认 method 为 undefined（fetch 默认 GET）', async () => {
      const mockResponse = new Response('{}', { status: 200 });
      const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValue(mockResponse);

      await apiFetch('/api/test');
      const callInit = fetchSpy.mock.calls[0][1] as RequestInit;
      // apiFetch 不显式设置 method，由 fetch 默认 GET
      expect(callInit.method).toBeUndefined();
    });

    it('fetch 失败时抛错', async () => {
      vi.spyOn(window, 'fetch').mockRejectedValue(new Error('network error'));
      await expect(apiFetch('/api/test')).rejects.toThrow('network error');
    });

    it('设置 timeoutMs 时创建 AbortController', async () => {
      const mockResponse = new Response('{}', { status: 200 });
      const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValue(mockResponse);

      await apiFetch('/api/test', { timeoutMs: 5000 });
      const callInit = fetchSpy.mock.calls[0][1] as RequestInit;
      expect(callInit.signal).toBeDefined();
    });

    it('无 timeoutMs 时不创建 signal', async () => {
      const mockResponse = new Response('{}', { status: 200 });
      const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValue(mockResponse);

      await apiFetch('/api/test');
      const callInit = fetchSpy.mock.calls[0][1] as RequestInit;
      // 无 timeoutMs 且无 userSignal 时 signal 为 undefined
      expect(callInit.signal).toBeUndefined();
    });

    it('传入 userSignal 时使用', async () => {
      const mockResponse = new Response('{}', { status: 200 });
      const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValue(mockResponse);
      const controller = new AbortController();

      await apiFetch('/api/test', { signal: controller.signal });
      const callInit = fetchSpy.mock.calls[0][1] as RequestInit;
      expect(callInit.signal).toBe(controller.signal);
    });

    it('传入 userSignal 和 timeoutMs 时合并信号', async () => {
      const mockResponse = new Response('{}', { status: 200 });
      const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValue(mockResponse);
      const controller = new AbortController();

      await apiFetch('/api/test', { signal: controller.signal, timeoutMs: 5000 });
      const callInit = fetchSpy.mock.calls[0][1] as RequestInit;
      // 合并后的 signal 不等于 userSignal
      expect(callInit.signal).not.toBe(controller.signal);
      expect(callInit.signal).toBeDefined();
    });
  });

  describe('pushClientModsOffState', () => {
    it('res.ok 时正常完成', async () => {
      const mockResponse = new Response('{}', { status: 200 });
      vi.spyOn(window, 'fetch').mockResolvedValue(mockResponse);

      await expect(pushClientModsOffState(true)).resolves.toBeUndefined();
    });

    it('res.ok 为 false 时抛错', async () => {
      const mockResponse = new Response('{}', { status: 500 });
      vi.spyOn(window, 'fetch').mockResolvedValue(mockResponse);

      await expect(pushClientModsOffState(false)).rejects.toThrow(/同步原版模式失败/);
    });

    it('fetch 抛错时传播', async () => {
      vi.spyOn(window, 'fetch').mockRejectedValue(new Error('network'));
      await expect(pushClientModsOffState(true)).rejects.toThrow('network');
    });
  });

  describe('syncClientModsStateToBackend', () => {
    it('res.ok 时正常完成', async () => {
      const mockResponse = new Response('{}', { status: 200 });
      vi.spyOn(window, 'fetch').mockResolvedValue(mockResponse);

      await expect(syncClientModsStateToBackend()).resolves.toBeUndefined();
    });

    it('res.ok 为 false 时正常完成（仅 warn）', async () => {
      const mockResponse = new Response('{}', { status: 500 });
      vi.spyOn(window, 'fetch').mockResolvedValue(mockResponse);
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined);

      await expect(syncClientModsStateToBackend()).resolves.toBeUndefined();
      expect(warnSpy).toHaveBeenCalled();
    });

    it('fetch 抛超时错误时正常完成（仅 debug）', async () => {
      const err = new DOMException('apiFetch timeout after 1000ms', 'AbortError');
      vi.spyOn(window, 'fetch').mockRejectedValue(err);
      const debugSpy = vi.spyOn(console, 'debug').mockImplementation(() => undefined);

      await expect(syncClientModsStateToBackend()).resolves.toBeUndefined();
      // DEV 模式下会调用 console.debug
      expect(debugSpy).toHaveBeenCalled();
    });

    it('fetch 抛非超时错误时正常完成（仅 warn）', async () => {
      vi.spyOn(window, 'fetch').mockRejectedValue(new Error('network'));
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined);

      await expect(syncClientModsStateToBackend()).resolves.toBeUndefined();
      expect(warnSpy).toHaveBeenCalled();
    });

    it('localStorage 为 1 时发送 client_mods_off: true', async () => {
      localStorage.setItem('xcagi_client_mods_ui_off', '1');
      const mockResponse = new Response('{}', { status: 200 });
      const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValue(mockResponse);

      await syncClientModsStateToBackend();
      const callInit = fetchSpy.mock.calls[0][1] as RequestInit;
      expect(String(callInit.body)).toContain('"client_mods_off":true');
    });

    it('localStorage 无值时发送 client_mods_off: false', async () => {
      const mockResponse = new Response('{}', { status: 200 });
      const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValue(mockResponse);

      await syncClientModsStateToBackend();
      const callInit = fetchSpy.mock.calls[0][1] as RequestInit;
      expect(String(callInit.body)).toContain('"client_mods_off":false');
    });
  });
});
