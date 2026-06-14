import { beforeEach, describe, expect, it } from 'vitest';
import {
  legacyActiveExtensionModStorageKey,
  readActiveExtensionModIdFromStorage,
  readAiSessionIdFromStorage,
  scopedActiveExtensionModStorageKey,
  writeActiveExtensionModIdToStorage,
  writeAiSessionIdToStorage,
  XCAGI_ACTIVE_EXTENSION_MOD_ID_KEY,
} from './xcagiStorageKeys';

beforeEach(() => {
  localStorage.clear();
});

describe('xcagiStorageKeys', () => {
  it('round-trips active extension mod id', () => {
    writeActiveExtensionModIdToStorage('mod-a');
    expect(readActiveExtensionModIdFromStorage()).toBe('mod-a');
    writeActiveExtensionModIdToStorage('');
    expect(readActiveExtensionModIdFromStorage()).toBe('');
  });

  it('round-trips ai session id', () => {
    writeAiSessionIdToStorage('sess-9');
    expect(readAiSessionIdFromStorage()).toBe('sess-9');
    writeAiSessionIdToStorage(null);
    expect(readAiSessionIdFromStorage()).toBe('');
  });

  it('exposes legacy and scoped key helpers', () => {
    expect(legacyActiveExtensionModStorageKey()).toBe(XCAGI_ACTIVE_EXTENSION_MOD_ID_KEY);
    expect(scopedActiveExtensionModStorageKey('tenant-1')).toContain(
      XCAGI_ACTIVE_EXTENSION_MOD_ID_KEY,
    );
  });
});
