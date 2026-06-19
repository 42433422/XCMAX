import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { swManager, initServiceWorker, unregisterStaleServiceWorkers } from './serviceWorker';

// 辅助：设置 navigator.serviceWorker
function setupServiceWorkerSupport(controller?: object) {
  const mockRegistration = {
    addEventListener: vi.fn(),
    update: vi.fn().mockResolvedValue(undefined),
    unregister: vi.fn().mockResolvedValue(true),
  };
  Object.defineProperty(navigator, 'serviceWorker', {
    configurable: true,
    value: {
      register: vi.fn().mockResolvedValue(mockRegistration),
      getRegistrations: vi.fn().mockResolvedValue([mockRegistration]),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      controller: controller || { postMessage: vi.fn() },
    },
  });
  return { mockRegistration };
}

describe('serviceWorker coverage', () => {
  afterEach(() => {
    swManager.destroy();
    vi.restoreAllMocks();
  });

  describe('unregisterStaleServiceWorkers', () => {
    it('支持时注销所有注册', async () => {
      const { mockRegistration } = setupServiceWorkerSupport();
      await unregisterStaleServiceWorkers();
      expect(mockRegistration.unregister).toHaveBeenCalled();
    });

    it('getRegistrations 抛错时捕获并 warn', async () => {
      setupServiceWorkerSupport();
      vi.spyOn(navigator.serviceWorker, 'getRegistrations').mockRejectedValue(new Error('fail'));
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
      await unregisterStaleServiceWorkers();
      expect(warnSpy).toHaveBeenCalled();
    });

    it('不支持时直接返回', async () => {
      Object.defineProperty(navigator, 'serviceWorker', {
        configurable: true,
        value: undefined,
      });
      await expect(unregisterStaleServiceWorkers()).resolves.toBeUndefined();
    });
  });

  describe('ServiceWorkerManager 基础', () => {
    it('status 返回副本（修改不影响内部状态）', () => {
      const status1 = swManager.status;
      status1.registered = true;
      const status2 = swManager.status;
      expect(status2.registered).not.toBe(status1.registered);
    });

    it('onChange 返回取消订阅函数', () => {
      const listener = vi.fn();
      const off = swManager.onChange(listener);
      expect(typeof off).toBe('function');
      off();
    });

    it('isOffline 返回当前离线状态', () => {
      (swManager as unknown as { _status: { offline: boolean } })._status.offline = true;
      expect(swManager.isOffline()).toBe(true);
      (swManager as unknown as { _status: { offline: boolean } })._status.offline = false;
      expect(swManager.isOffline()).toBe(false);
    });

    it('checkForUpdate 无 registration 时返回 false', async () => {
      (swManager as unknown as { _registration: unknown })._registration = null;
      expect(await swManager.checkForUpdate()).toBe(false);
    });

    it('clearCache 不支持时返回 false', async () => {
      (swManager as unknown as { _status: { supported: boolean } })._status.supported = false;
      expect(await swManager.clearCache()).toBe(false);
    });

    it('getCacheStatus 不支持时返回 null', async () => {
      (swManager as unknown as { _status: { supported: boolean } })._status.supported = false;
      expect(await swManager.getCacheStatus()).toBeNull();
    });

    it('activateUpdate 无 controller 时直接返回', async () => {
      (swManager as unknown as { _status: { controller: boolean } })._status.controller = false;
      Object.defineProperty(navigator, 'serviceWorker', {
        configurable: true,
        value: { controller: undefined },
      });
      await expect(swManager.activateUpdate()).resolves.toBeUndefined();
    });
  });

  describe('ServiceWorkerManager - checkForUpdate 有 registration', () => {
    it('update 成功时返回 true', async () => {
      const updateSpy = vi.fn().mockResolvedValue(undefined);
      (swManager as unknown as { _registration: unknown })._registration = { update: updateSpy };
      const result = await swManager.checkForUpdate();
      expect(result).toBe(true);
      expect(updateSpy).toHaveBeenCalled();
    });

    it('update 抛错时返回 false 并 warn', async () => {
      const updateSpy = vi.fn().mockRejectedValue(new Error('update fail'));
      (swManager as unknown as { _registration: unknown })._registration = { update: updateSpy };
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
      const result = await swManager.checkForUpdate();
      expect(result).toBe(false);
      expect(warnSpy).toHaveBeenCalled();
    });
  });

  describe('ServiceWorkerManager - activateUpdate 有 controller', () => {
    it('发送 SKIP_WAITING 并等待 controllerchange', async () => {
      const postMessageSpy = vi.fn();
      (swManager as unknown as { _status: { controller: boolean } })._status.controller = true;
      Object.defineProperty(navigator, 'serviceWorker', {
        configurable: true,
        value: {
          controller: { postMessage: postMessageSpy },
          addEventListener: vi.fn((event: string, cb: (ev: Event) => void) => {
            if (event === 'controllerchange') {
              setTimeout(() => cb(new Event('controllerchange')), 0);
            }
          }),
        },
      });
      const reloadSpy = vi.fn();
      Object.defineProperty(window, 'location', {
        configurable: true,
        value: { reload: reloadSpy },
      });
      await swManager.activateUpdate();
      expect(postMessageSpy).toHaveBeenCalledWith({ type: 'SKIP_WAITING' });
      expect(reloadSpy).toHaveBeenCalled();
    });
  });

  describe('ServiceWorkerManager - clearCache 有 controller', () => {
    beforeEach(() => {
      (swManager as unknown as { _status: { supported: boolean; controller: boolean } })._status.supported = true;
      (swManager as unknown as { _status: { controller: boolean } })._status.controller = true;
    });

    it('收到 CACHE_CLEARED 响应返回 true', async () => {
      const postMessageSpy = vi.fn();
      Object.defineProperty(navigator, 'serviceWorker', {
        configurable: true,
        value: { controller: { postMessage: postMessageSpy } },
      });
      const originalMessageChannel = globalThis.MessageChannel;
      let port1OnMessage: ((ev: MessageEvent) => void) | null = null;
      globalThis.MessageChannel = class {
        port1 = {
          set onmessage(cb: (ev: MessageEvent) => void) {
            port1OnMessage = cb;
          },
          get onmessage() {
            return port1OnMessage as never;
          },
        };
        port2 = {};
      } as never;
      const promise = swManager.clearCache();
      setTimeout(() => {
        if (port1OnMessage) {
          port1OnMessage(new MessageEvent('message', { data: { type: 'CACHE_CLEARED' } }));
        }
      }, 0);
      const result = await promise;
      expect(result).toBe(true);
      expect(postMessageSpy).toHaveBeenCalledWith({ type: 'CLEAR_CACHE' }, expect.anything());
      globalThis.MessageChannel = originalMessageChannel;
    });

    it('收到非 CACHE_CLEARED 响应返回 false', async () => {
      Object.defineProperty(navigator, 'serviceWorker', {
        configurable: true,
        value: { controller: { postMessage: vi.fn() } },
      });
      const originalMessageChannel = globalThis.MessageChannel;
      let port1OnMessage: ((ev: MessageEvent) => void) | null = null;
      globalThis.MessageChannel = class {
        port1 = {
          set onmessage(cb: (ev: MessageEvent) => void) {
            port1OnMessage = cb;
          },
          get onmessage() {
            return port1OnMessage as never;
          },
        };
        port2 = {};
      } as never;
      const promise = swManager.clearCache();
      setTimeout(() => {
        if (port1OnMessage) {
          port1OnMessage(new MessageEvent('message', { data: { type: 'OTHER' } }));
        }
      }, 0);
      const result = await promise;
      expect(result).toBe(false);
      globalThis.MessageChannel = originalMessageChannel;
    });

    it('5 秒超时返回 false', async () => {
      vi.useFakeTimers();
      Object.defineProperty(navigator, 'serviceWorker', {
        configurable: true,
        value: { controller: { postMessage: vi.fn() } },
      });
      const originalMessageChannel = globalThis.MessageChannel;
      globalThis.MessageChannel = class {
        port1 = { onmessage: null as never };
        port2 = {};
      } as never;
      const promise = swManager.clearCache();
      vi.advanceTimersByTime(5000);
      const result = await promise;
      expect(result).toBe(false);
      globalThis.MessageChannel = originalMessageChannel;
      vi.useRealTimers();
    });
  });

  describe('ServiceWorkerManager - getCacheStatus 有 controller', () => {
    beforeEach(() => {
      (swManager as unknown as { _status: { supported: boolean; controller: boolean } })._status.supported = true;
      (swManager as unknown as { _status: { controller: boolean } })._status.controller = true;
    });

    it('收到 STATUS 响应返回数据', async () => {
      Object.defineProperty(navigator, 'serviceWorker', {
        configurable: true,
        value: { controller: { postMessage: vi.fn() } },
      });
      const originalMessageChannel = globalThis.MessageChannel;
      let port1OnMessage: ((ev: MessageEvent) => void) | null = null;
      globalThis.MessageChannel = class {
        port1 = {
          set onmessage(cb: (ev: MessageEvent) => void) {
            port1OnMessage = cb;
          },
          get onmessage() {
            return port1OnMessage as never;
          },
        };
        port2 = {};
      } as never;
      const promise = swManager.getCacheStatus();
      setTimeout(() => {
        if (port1OnMessage) {
          port1OnMessage(new MessageEvent('message', { data: { type: 'STATUS', size: 100 } }));
        }
      }, 0);
      const result = await promise;
      expect(result).toEqual({ type: 'STATUS', size: 100 });
      globalThis.MessageChannel = originalMessageChannel;
    });

    it('收到非 STATUS 响应返回 null', async () => {
      Object.defineProperty(navigator, 'serviceWorker', {
        configurable: true,
        value: { controller: { postMessage: vi.fn() } },
      });
      const originalMessageChannel = globalThis.MessageChannel;
      let port1OnMessage: ((ev: MessageEvent) => void) | null = null;
      globalThis.MessageChannel = class {
        port1 = {
          set onmessage(cb: (ev: MessageEvent) => void) {
            port1OnMessage = cb;
          },
          get onmessage() {
            return port1OnMessage as never;
          },
        };
        port2 = {};
      } as never;
      const promise = swManager.getCacheStatus();
      setTimeout(() => {
        if (port1OnMessage) {
          port1OnMessage(new MessageEvent('message', { data: { type: 'OTHER' } }));
        }
      }, 0);
      const result = await promise;
      expect(result).toBeNull();
      globalThis.MessageChannel = originalMessageChannel;
    });

    it('3 秒超时返回 null', async () => {
      vi.useFakeTimers();
      Object.defineProperty(navigator, 'serviceWorker', {
        configurable: true,
        value: { controller: { postMessage: vi.fn() } },
      });
      const originalMessageChannel = globalThis.MessageChannel;
      globalThis.MessageChannel = class {
        port1 = { onmessage: null as never };
        port2 = {};
      } as never;
      const promise = swManager.getCacheStatus();
      vi.advanceTimersByTime(3000);
      const result = await promise;
      expect(result).toBeNull();
      globalThis.MessageChannel = originalMessageChannel;
      vi.useRealTimers();
    });
  });

  describe('ServiceWorkerManager - onChange', () => {
    it('监听器在 _notifyListeners 调用时被触发', () => {
      const listener = vi.fn();
      swManager.onChange(listener);
      (swManager as unknown as { _notifyListeners: () => void })._notifyListeners();
      expect(listener).toHaveBeenCalled();
    });

    it('监听器抛错时被捕获并 error', () => {
      const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
      const listener = vi.fn(() => {
        throw new Error('listener error');
      });
      swManager.onChange(listener);
      (swManager as unknown as { _notifyListeners: () => void })._notifyListeners();
      expect(errorSpy).toHaveBeenCalled();
    });

    it('取消订阅后监听器不再被触发', () => {
      const listener = vi.fn();
      const off = swManager.onChange(listener);
      off();
      (swManager as unknown as { _notifyListeners: () => void })._notifyListeners();
      expect(listener).not.toHaveBeenCalled();
    });
  });

  describe('initServiceWorker', () => {
    it('返回 status 对象', async () => {
      const status = await initServiceWorker();
      expect(status).toBeDefined();
      expect(typeof status.registered).toBe('boolean');
      expect(typeof status.supported).toBe('boolean');
    });

    it('注册失败时 warn 警告', async () => {
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
      await initServiceWorker();
      // DEV 环境下 register 返回 false，会 warn
      expect(warnSpy).toHaveBeenCalled();
    });
  });

  describe('destroy', () => {
    it('调用 destroy 后清空监听器', () => {
      const listener = vi.fn();
      swManager.onChange(listener);
      swManager.destroy();
      (swManager as unknown as { _notifyListeners: () => void })._notifyListeners();
      expect(listener).not.toHaveBeenCalled();
    });
  });
});
