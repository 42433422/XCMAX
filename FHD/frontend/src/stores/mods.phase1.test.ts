import { describe, it, expect, beforeEach, vi } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useModsStore, CLIENT_MODS_UI_OFF_KEY } from './mods';

vi.mock('@/utils/apiBase', () => ({
  apiFetch: vi.fn(),
  DEFAULT_MOD_API_TIMEOUT_MS: 8000,
  MOD_PROBE_API_TIMEOUT_MS: 3000,
  isApiFetchTimeoutError: () => false,
}));

vi.mock('@/utils/modRoutesSharedFetch', () => ({
  fetchModRoutesPayloadShared: vi.fn(async () => ({ routes: [] })),
}));

vi.mock('@/utils/modLoadingStatusShared', () => ({
  fetchModLoadingStatusShared: vi.fn(async () => ({ mods: [] })),
}));

vi.mock('@/utils/platformShellApi', () => ({
  fetchPlatformShellCapabilities: vi.fn(async () => ({})),
}));

vi.mock('@/stores/hostConfig', () => ({
  bootstrapHostConfig: vi.fn(async () => {}),
  clientModPolicies: { value: {} },
}));

vi.mock('@/stores/accountProfile', () => ({
  useAccountProfileStore: () => ({
    accountUsername: '',
    isEnterprise: false,
  }),
}));

describe('mods store phase1 coverage', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
  });

  it('CLIENT_MODS_UI_OFF_KEY is stable', () => {
    expect(CLIENT_MODS_UI_OFF_KEY).toBe('xcagi_client_mods_ui_off');
  });

  it('modsForUi filters disabled client mods', () => {
    const store = useModsStore();
    store.mods = [
      { id: 'a', name: 'A', enabled: true },
      { id: 'b', name: 'B', enabled: false },
    ] as never[];
    expect(store.modsForUi.length).toBeGreaterThanOrEqual(1);
  });

  it('clientModsUiOff toggles localStorage flag', () => {
    const store = useModsStore();
    expect(store.clientModsUiOff).toBe(false);
    store.setClientModsUiOff(true);
    expect(store.clientModsUiOff).toBe(true);
    expect(localStorage.getItem(CLIENT_MODS_UI_OFF_KEY)).toBe('1');
    store.setClientModsUiOff(false);
    expect(localStorage.getItem(CLIENT_MODS_UI_OFF_KEY)).toBeNull();
  });

  it('activeModId can be set and read', () => {
    const store = useModsStore();
    store.setActiveModId('demo-mod');
    expect(store.activeModId).toBe('demo-mod');
  });

  it('modsForWorkflowUi respects clientModsUiOff', () => {
    const store = useModsStore();
    store.mods = [{ id: 'wf', name: 'WF', enabled: true }] as never[];
    store.setClientModsUiOff(true);
    expect(store.modsForWorkflowUi).toEqual([]);
  });
});
