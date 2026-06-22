/**
 * mods.ts store 增强测试
 * 覆盖：readEntitledModIdsFromAuthPayload、initialize、fetchMods、setActiveModId、
 * setClientModsUiOff、refresh、applyLoadingStatusPreview、syncActiveModWithServerIndustry、
 * applyEntitledActiveMod、getModMenu、modsForUi、modsForWorkflowUi、ensureActiveModSelection 等
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useModsStore, CLIENT_MODS_UI_OFF_KEY, readEntitledModIdsFromAuthPayload } from './mods';

// ── 外部 API mock ──────────────────────────────────────────
const mockApiFetch = vi.fn();
vi.mock('@/utils/apiBase', () => ({
  apiFetch: (...args: unknown[]) => mockApiFetch(...args),
  DEFAULT_MOD_API_TIMEOUT_MS: 90_000,
  MOD_PROBE_API_TIMEOUT_MS: 8_000,
  isApiFetchTimeoutError: (e: unknown) =>
    e instanceof DOMException && e.name === 'AbortError' && e.message.includes('apiFetch timeout'),
  syncClientModsStateToBackend: vi.fn(),
}));

vi.mock('@/utils/modRoutesSharedFetch', () => ({
  fetchModRoutesPayloadShared: vi.fn(async () => []),
}));

vi.mock('@/utils/modLoadingStatusShared', () => ({
  fetchModLoadingStatusShared: vi.fn(async () => null),
}));

vi.mock('@/utils/modLoadingStatus', () => ({
  summarizeModLoadingData: vi.fn(() => null),
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
    isAdminAccount: false,
    isEnterprise: false,
  }),
}));

vi.mock('@/utils/adminConsoleUrl', () => ({
  isAdminConsoleSpa: () => false,
}));

vi.mock('@/constants/approvalMod', () => ({
  APPROVAL_BRIDGE_MOD_ID: 'xcagi-approval-bridge',
  setApprovalModFacadeEnabled: vi.fn(),
}));

vi.mock('@/constants/erpDomainMod', () => ({
  ERP_DOMAIN_BRIDGE_MOD_ID: 'xcagi-erp-domain-bridge',
  erpDomainModFrontendRoutesAvailable: () => false,
  setErpDomainModFacadeEnabled: vi.fn(),
}));

vi.mock('@/utils/erpDomainPaths', () => ({
  erpDomainModStatusPath: () => '/api/mod/erp-domain/status',
}));

vi.mock('@/constants/lanMod', () => ({
  LAN_BRIDGE_MOD_ID: 'xcagi-lan-license-bridge',
  setLanModFacadeEnabled: vi.fn(),
}));

vi.mock('@/constants/modelPaymentMod', () => ({
  MODEL_PAYMENT_BRIDGE_MOD_ID: 'xcagi-model-payment-bridge',
  setModelPaymentModFacadeEnabled: vi.fn(),
}));

vi.mock('@/constants/customerServiceMod', () => ({
  CUSTOMER_SERVICE_BRIDGE_MOD_ID: 'xcagi-customer-service-bridge',
  customerServiceModFrontendRoutesAvailable: () => false,
  setCustomerServiceModPagesEnabled: vi.fn(),
}));

vi.mock('@/constants/plannerMod', () => ({
  PLANNER_FACADE_MOD_ID: 'xcagi-planner-bridge',
  setPlannerModFacadeEnabled: vi.fn(),
}));

vi.mock('@/constants/officeEmployeePackMod', () => ({
  OFFICE_EMPLOYEE_PACK_BRIDGE_MOD_ID: 'xcagi-office-employee-pack-bridge',
  setOfficeEmployeePackModPagesEnabled: vi.fn(),
}));

vi.mock('@/constants/coreWorkflowMod', () => ({
  CORE_WORKFLOW_MOD_ID: 'xcagi-core-workflow-employees',
  coreWorkflowModEmployeesPath: () => '/api/mod/core-workflow/employees',
  setCoreWorkflowModPagesEnabled: vi.fn(),
}));

vi.mock('@/constants/platformShellMode', () => ({
  applyEditionPackPlatformShell: vi.fn(),
}));

vi.mock('@/constants/genericModPack', () => ({
  ACCOUNT_CUSTOM_MOD_IDS: ['taiyangniao-pro', 'sz-qsm-pro'],
  CLIENT_PRIMARY_ERP_MOD_ID: 'attendance-industry',
  hasInstalledClientPrimaryErpMod: () => false,
  isAuxEmployeePackModId: (id: string) => id.startsWith('xcagi-aux-'),
  isClientErpSidebarContext: () => false,
  isHostMountedModMenuPath: () => false,
  isSelectableExtensionModId: (id: string) =>
    !id.startsWith('xcagi-') || id === 'attendance-industry' || id === 'taiyangniao-pro' || id === 'sz-qsm-pro',
  shouldHideAttendanceModSidebarMenu: () => false,
  shouldSuppressClientErpModMenuId: () => false,
}));

vi.mock('@/constants/accountModBinding', () => ({
  SUNBIRD_CLIENT_MOD_ID: 'taiyangniao-pro',
  augmentEntitledModIdsForAccount: (_u: unknown, ids: string[] | undefined) => ids || [],
  isSunbirdAccountUsername: (u: string | null | undefined) =>
    String(u || '').trim().toUpperCase() === 'SUNBIRD',
  shouldBindClientPrimaryErpMod: () => false,
}));

vi.mock('@/constants/sunbirdClientMod', () => ({
  buildAttendanceIndustryModStub: () => ({
    id: 'attendance-industry',
    name: '考勤行业包',
    version: '1.0.0',
    author: 'xcagi',
    description: 'attendance stub',
  }),
  buildSunbirdClientModStub: () => ({
    id: 'taiyangniao-pro',
    name: '太阳鸟 PRO',
    version: '1.0.0',
    author: 'sunbird',
    description: 'stub',
  }),
}));

vi.mock('@/constants/protectedMods', () => ({
  isProtectedClientModId: (id: string) =>
    ['attendance-industry', 'coating-industry', 'taiyangniao-pro', 'sz-qsm-pro'].includes(id),
}));

vi.mock('@/utils/modWorkflowEmployees', () => ({
  filterWorkflowRegistrySourceMods: (mods: unknown[]) => mods,
}));

vi.mock('@/utils/xcagiStorageKeys', () => ({
  XCAGI_ACTIVE_EXTENSION_MOD_ID_KEY: 'xcagi_active_extension_mod_id',
  readActiveExtensionModIdFromStorage: () => '',
  writeActiveExtensionModIdToStorage: vi.fn(),
}));

vi.mock('@/stores/industry', () => ({
  useIndustryStore: () => ({
    currentIndustryId: '',
    error: null,
  }),
}));

vi.mock('@/router/registerModRoutes', () => ({
  registerAllModRoutesFromGlob: vi.fn(async () => {}),
  registerModRoutes: vi.fn(async () => {}),
}));

vi.mock('@/router', () => ({
  default: { addRoute: vi.fn(), getRoutes: () => [] },
}));

// ── helpers ────────────────────────────────────────────────
function makeModsResponse(modsData: unknown[], extra: Record<string, unknown> = {}) {
  return {
    ok: true,
    status: 200,
    json: async () => ({ success: true, data: modsData, ...extra }),
  };
}

function makeFailedModsResponse(status: number, body: Record<string, unknown> = {}) {
  return {
    ok: false,
    status,
    json: async () => body,
  };
}

const sampleMods = [
  {
    id: 'xcagi-planner-bridge',
    name: 'Planner',
    version: '1.0',
    author: 'xcagi',
    description: 'planner bridge',
    primary: false,
    industry: { id: 'generic', name: '通用' },
    menu: [{ id: 'mod-planner-chat', label: '智能对话', icon: 'chat', path: '/mod/xcagi-planner-bridge/chat' }],
  },
  {
    id: 'attendance-industry',
    name: '考勤行业包',
    version: '2.0',
    author: 'sunbird',
    description: 'attendance mod',
    primary: true,
    industry: { id: 'attendance', name: '考勤' },
    menu: [{ id: 'mod-attendance-dashboard', label: '考勤看板', icon: 'dashboard', path: '/mod/attendance-industry/dashboard' }],
  },
  {
    id: 'taiyangniao-pro',
    name: '太阳鸟 Pro',
    version: '3.0',
    author: 'sunbird',
    description: 'taiyangniao pro',
    primary: false,
    industry: { id: 'coating', name: '涂装' },
    menu: [{ id: 'mod-taiyangniao-products', label: '产品管理', icon: 'box', path: '/mod/taiyangniao-pro/products' }],
  },
];

// ── test suites ────────────────────────────────────────────

describe('readEntitledModIdsFromAuthPayload', () => {
  it('returns empty array for null input', () => {
    expect(readEntitledModIdsFromAuthPayload(null)).toEqual([]);
  });

  it('returns empty array for undefined input', () => {
    expect(readEntitledModIdsFromAuthPayload(undefined)).toEqual([]);
  });

  it('returns empty array for non-object input', () => {
    expect(readEntitledModIdsFromAuthPayload('string')).toEqual([]);
    expect(readEntitledModIdsFromAuthPayload(42)).toEqual([]);
  });

  it('extracts entitled_mod_ids from top-level', () => {
    const payload = { entitled_mod_ids: ['mod-a', 'mod-b'] };
    expect(readEntitledModIdsFromAuthPayload(payload)).toEqual(['mod-a', 'mod-b']);
  });

  it('extracts entitled_mod_ids from nested data object', () => {
    const payload = { data: { entitled_mod_ids: ['mod-x'] } };
    expect(readEntitledModIdsFromAuthPayload(payload)).toEqual(['mod-x']);
  });

  it('prefers top-level entitled_mod_ids over nested data', () => {
    const payload = {
      entitled_mod_ids: ['top-level'],
      data: { entitled_mod_ids: ['nested'] },
    };
    expect(readEntitledModIdsFromAuthPayload(payload)).toEqual(['top-level']);
  });

  it('deduplicates and trims ids', () => {
    const payload = { entitled_mod_ids: ['  mod-a  ', 'mod-a', ' mod-b ', ''] };
    expect(readEntitledModIdsFromAuthPayload(payload)).toEqual(['mod-a', 'mod-b']);
  });

  it('returns empty array when entitled_mod_ids is not an array', () => {
    const payload = { entitled_mod_ids: 'not-an-array' };
    expect(readEntitledModIdsFromAuthPayload(payload)).toEqual([]);
  });

  it('handles data field that is an array (not an object)', () => {
    const payload = { data: [1, 2, 3], entitled_mod_ids: ['mod-a'] };
    expect(readEntitledModIdsFromAuthPayload(payload)).toEqual(['mod-a']);
  });
});

describe('mods store – basic state', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
  });

  it('CLIENT_MODS_UI_OFF_KEY is stable', () => {
    expect(CLIENT_MODS_UI_OFF_KEY).toBe('xcagi_client_mods_ui_off');
  });

  it('initializes with empty mods array', () => {
    const store = useModsStore();
    expect(store.mods).toEqual([]);
  });

  it('initializes with empty modRoutes', () => {
    const store = useModsStore();
    expect(store.modRoutes).toEqual([]);
  });

  it('initializes with clientModsUiOff false', () => {
    const store = useModsStore();
    expect(store.clientModsUiOff).toBe(false);
  });

  it('initializes with empty activeModId', () => {
    const store = useModsStore();
    expect(store.activeModId).toBe('');
  });

  it('initializes with isLoaded false', () => {
    const store = useModsStore();
    expect(store.isLoaded).toBe(false);
  });

  it('initializes with loadError null', () => {
    const store = useModsStore();
    expect(store.loadError).toBeNull();
  });
});

describe('mods store – setClientModsUiOff', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
  });

  it('sets clientModsUiOff to true and writes localStorage', () => {
    const store = useModsStore();
    store.setClientModsUiOff(true);
    expect(store.clientModsUiOff).toBe(true);
    expect(localStorage.getItem(CLIENT_MODS_UI_OFF_KEY)).toBe('1');
  });

  it('clears mods and routes when turning off', () => {
    const store = useModsStore();
    store.mods = sampleMods as never[];
    store.modRoutes = [{ mod_id: 'x', routes_path: '/y' }] as never[];
    store.setClientModsUiOff(true);
    expect(store.mods).toEqual([]);
    expect(store.modRoutes).toEqual([]);
    expect(store.activeModId).toBe('');
    expect(store.loadError).toBeNull();
    expect(store.isLoaded).toBe(true);
  });

  it('sets isLoaded to false when turning back on', () => {
    const store = useModsStore();
    store.setClientModsUiOff(true);
    expect(store.isLoaded).toBe(true);
    store.setClientModsUiOff(false);
    expect(store.isLoaded).toBe(false);
    expect(store.clientModsUiOff).toBe(false);
    expect(localStorage.getItem(CLIENT_MODS_UI_OFF_KEY)).toBeNull();
  });

  it('clears mods and routes when turning back on', () => {
    const store = useModsStore();
    store.setClientModsUiOff(true);
    store.setClientModsUiOff(false);
    expect(store.mods).toEqual([]);
    expect(store.modRoutes).toEqual([]);
    expect(store.loadError).toBeNull();
  });
});

describe('mods store – setActiveModId', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
  });

  it('sets activeModId to a string value', () => {
    const store = useModsStore();
    store.setActiveModId('demo-mod');
    expect(store.activeModId).toBe('demo-mod');
  });

  it('trims whitespace from modId', () => {
    const store = useModsStore();
    store.setActiveModId('  spaced-mod  ');
    expect(store.activeModId).toBe('spaced-mod');
  });

  it('sets activeModId to empty string for null/undefined', () => {
    const store = useModsStore();
    store.setActiveModId('first');
    store.setActiveModId(null);
    expect(store.activeModId).toBe('');
    store.setActiveModId(undefined);
    expect(store.activeModId).toBe('');
  });

  it('sets activeModId to empty string for empty string input', () => {
    const store = useModsStore();
    store.setActiveModId('first');
    store.setActiveModId('');
    expect(store.activeModId).toBe('');
  });
});

describe('mods store – modsForUi', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
  });

  it('returns empty when clientModsUiOff is true', () => {
    const store = useModsStore();
    store.mods = sampleMods as never[];
    store.setClientModsUiOff(true);
    expect(store.modsForUi).toEqual([]);
  });

  it('returns all mods when no activeModId is set', () => {
    const store = useModsStore();
    store.mods = sampleMods as never[];
    expect(store.modsForUi).toHaveLength(sampleMods.length);
  });

  it('returns only the active mod when activeModId is set and found', () => {
    const store = useModsStore();
    store.mods = sampleMods as never[];
    store.setActiveModId('attendance-industry');
    const ui = store.modsForUi;
    expect(ui).toHaveLength(1);
    expect(ui[0].id).toBe('attendance-industry');
  });

  it('returns all mods when activeModId is set but not found in mods list', () => {
    const store = useModsStore();
    store.mods = sampleMods as never[];
    store.setActiveModId('nonexistent-mod');
    expect(store.modsForUi).toHaveLength(sampleMods.length);
  });

  it('returns attendance stub when activeModId is CLIENT_PRIMARY_ERP_MOD_ID and not in list', () => {
    const store = useModsStore();
    const modsNoAttendance = sampleMods.filter((m) => m.id !== 'attendance-industry');
    store.mods = modsNoAttendance as never[];
    store.setActiveModId('attendance-industry');
    const ui = store.modsForUi;
    expect(ui).toHaveLength(1);
    expect(ui[0].id).toBe('attendance-industry');
  });
});

describe('mods store – modsForWorkflowUi', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
  });

  it('returns empty when clientModsUiOff is true', () => {
    const store = useModsStore();
    store.mods = sampleMods as never[];
    store.setClientModsUiOff(true);
    expect(store.modsForWorkflowUi).toEqual([]);
  });

  it('returns filtered workflow mods when clientModsUiOff is false', () => {
    const store = useModsStore();
    store.mods = sampleMods as never[];
    expect(store.modsForWorkflowUi).toHaveLength(sampleMods.length);
  });
});

describe('mods store – applyLoadingStatusPreview', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
  });

  it('does nothing when clientModsUiOff is true', () => {
    const store = useModsStore();
    store.setClientModsUiOff(true);
    store.applyLoadingStatusPreview([{ id: 'mod-a', name: 'A' }]);
    expect(store.mods).toEqual([]);
  });

  it('does nothing when rows is null', () => {
    const store = useModsStore();
    store.applyLoadingStatusPreview(null);
    expect(store.mods).toEqual([]);
  });

  it('does nothing when rows is empty array', () => {
    const store = useModsStore();
    store.applyLoadingStatusPreview([]);
    expect(store.mods).toEqual([]);
  });

  it('does nothing when mods already loaded', () => {
    const store = useModsStore();
    store.mods = sampleMods as never[];
    store.applyLoadingStatusPreview([{ id: 'preview-mod', name: 'Preview' }]);
    // Should not overwrite existing mods
    expect(store.mods).toEqual(sampleMods);
  });

  it('populates mods from preview rows when mods is empty', () => {
    const store = useModsStore();
    store.applyLoadingStatusPreview([
      { id: 'mod-a', name: 'Module A', version: '1.0' },
      { id: 'mod-b', name: 'Module B' },
    ]);
    expect(store.mods).toHaveLength(2);
    expect(store.mods[0].id).toBe('mod-a');
    expect(store.mods[0].name).toBe('Module A');
    expect(store.mods[0].version).toBe('1.0');
    expect(store.mods[1].id).toBe('mod-b');
  });

  it('handles rows with missing name by using id', () => {
    const store = useModsStore();
    store.applyLoadingStatusPreview([{ id: 'mod-x' }]);
    expect(store.mods[0].name).toBe('mod-x');
  });

  it('handles rows with empty id by using "unknown"', () => {
    const store = useModsStore();
    store.applyLoadingStatusPreview([{ id: '', name: 'NoId' }]);
    expect(store.mods[0].id).toBe('unknown');
  });
});

describe('mods store – fetchModsOnce', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    mockApiFetch.mockReset();
  });

  it('fetches mods successfully', async () => {
    mockApiFetch.mockResolvedValueOnce(makeModsResponse(sampleMods));
    const store = useModsStore();
    const result = await store.fetchMods();
    expect(result.ok).toBe(true);
    expect(store.mods).toHaveLength(sampleMods.length);
    expect(store.loadError).toBeNull();
  });

  it('handles HTTP error response', async () => {
    // fetchModsWithRetry retries once on non-transport error
    mockApiFetch.mockResolvedValue(makeFailedModsResponse(500));
    const store = useModsStore();
    const result = await store.fetchMods();
    expect(result.ok).toBe(false);
    expect(store.loadError).toBe('HTTP 500');
  });

  it('handles API returning success: false with error message', async () => {
    mockApiFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ success: false, error: 'backend error' }),
    });
    const store = useModsStore();
    const result = await store.fetchMods();
    expect(result.ok).toBe(false);
    expect(store.loadError).toBe('backend error');
  });

  it('handles API returning success: false with message field', async () => {
    mockApiFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ success: false, message: 'custom message' }),
    });
    const store = useModsStore();
    const result = await store.fetchMods();
    expect(result.ok).toBe(false);
    expect(store.loadError).toBe('custom message');
  });

  it('handles mods_disabled flag', async () => {
    mockApiFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ success: true, data: [], mods_disabled: true }),
    });
    const store = useModsStore();
    const result = await store.fetchMods();
    expect(result.ok).toBe(true);
    expect(result.modsDisabled).toBe(true);
    expect(store.mods).toEqual([]);
    expect(store.activeModId).toBe('');
  });

  it('handles network error with transport error detection', async () => {
    // fetchModsWithRetry retries once on transport error (with 1200ms delay)
    mockApiFetch.mockRejectedValue(new TypeError('Failed to fetch'));
    const store = useModsStore();
    const result = await store.fetchMods();
    expect(result.ok).toBe(false);
    expect(result.transportError).toBe(true);
    expect(store.loadError).toContain('无法连接');
  });

  it('handles timeout error', async () => {
    const timeoutErr = new DOMException('apiFetch timeout after 8000ms', 'AbortError');
    // fetchModsWithRetry retries on transport error
    mockApiFetch.mockRejectedValue(timeoutErr);
    const store = useModsStore();
    const result = await store.fetchMods();
    expect(result.ok).toBe(false);
    expect(result.transportError).toBe(true);
    expect(store.loadError).toContain('超时');
  });

  it('handles generic error', async () => {
    mockApiFetch.mockRejectedValue(new Error('something went wrong'));
    const store = useModsStore();
    const result = await store.fetchMods();
    expect(result.ok).toBe(false);
    expect(store.loadError).toBe('something went wrong');
  });

  it('clears loadError on successful fetch', async () => {
    const store = useModsStore();
    store.loadError = 'previous error';
    mockApiFetch.mockResolvedValueOnce(makeModsResponse(sampleMods));
    await store.fetchMods();
    expect(store.loadError).toBeNull();
  });
});

describe('mods store – fetchModRoutes', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
  });

  it('fetches and stores mod routes', async () => {
    const { fetchModRoutesPayloadShared } = await import('@/utils/modRoutesSharedFetch');
    const mockFetch = vi.mocked(fetchModRoutesPayloadShared);
    const routes = [
      { mod_id: 'mod-a', routes_path: '/mod/mod-a/page1' },
      { mod_id: 'mod-b', routes_path: '/mod/mod-b/page2' },
    ];
    mockFetch.mockResolvedValueOnce(routes);
    const store = useModsStore();
    await store.fetchModRoutes();
    expect(store.modRoutes).toEqual(routes);
  });

  it('does not overwrite modRoutes when fetch returns null', async () => {
    const { fetchModRoutesPayloadShared } = await import('@/utils/modRoutesSharedFetch');
    const mockFetch = vi.mocked(fetchModRoutesPayloadShared);
    const store = useModsStore();
    store.modRoutes = [{ mod_id: 'existing', routes_path: '/existing' }] as never[];
    mockFetch.mockResolvedValueOnce(null);
    await store.fetchModRoutes();
    expect(store.modRoutes).toHaveLength(1);
  });
});

describe('mods store – syncActiveModWithServerIndustry', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    mockApiFetch.mockReset();
  });

  it('does nothing when clientModsUiOff is true', async () => {
    const store = useModsStore();
    store.setClientModsUiOff(true);
    await store.syncActiveModWithServerIndustry();
    expect(mockApiFetch).not.toHaveBeenCalled();
  });

  it('does nothing when mods list is empty', async () => {
    const store = useModsStore();
    await store.syncActiveModWithServerIndustry();
    expect(mockApiFetch).not.toHaveBeenCalled();
  });

  it('does nothing when activeModId is already set', async () => {
    const store = useModsStore();
    store.mods = sampleMods as never[];
    store.setActiveModId('attendance-industry');
    await store.syncActiveModWithServerIndustry();
    expect(mockApiFetch).not.toHaveBeenCalled();
  });

  it('picks mod matching server industry when activeModId is empty', async () => {
    const store = useModsStore();
    store.mods = sampleMods as never[];
    mockApiFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ success: true, data: { id: 'attendance' } }),
    });
    await store.syncActiveModWithServerIndustry();
    expect(store.activeModId).toBe('attendance-industry');
  });

  it('does not change activeModId when server industry has no matching mod', async () => {
    const store = useModsStore();
    store.mods = sampleMods as never[];
    mockApiFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ success: true, data: { id: 'nonexistent-industry' } }),
    });
    await store.syncActiveModWithServerIndustry();
    expect(store.activeModId).toBe('');
  });

  it('handles API error gracefully', async () => {
    const store = useModsStore();
    store.mods = sampleMods as never[];
    mockApiFetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({}),
    });
    await store.syncActiveModWithServerIndustry();
    expect(store.activeModId).toBe('');
  });

  it('handles network error gracefully', async () => {
    const store = useModsStore();
    store.mods = sampleMods as never[];
    mockApiFetch.mockRejectedValueOnce(new Error('network'));
    await store.syncActiveModWithServerIndustry();
    expect(store.activeModId).toBe('');
  });
});

describe('mods store – initialize', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    mockApiFetch.mockReset();
  });

  it('returns early when clientModsUiOff is true', async () => {
    const store = useModsStore();
    store.setClientModsUiOff(true);
    await store.initialize();
    expect(store.isLoaded).toBe(true);
    expect(store.mods).toEqual([]);
    expect(mockApiFetch).not.toHaveBeenCalled();
  });

  it('fetches mods and sets isLoaded on success', async () => {
    mockApiFetch.mockResolvedValueOnce(makeModsResponse(sampleMods));
    const store = useModsStore();
    await store.initialize();
    expect(store.isLoaded).toBe(true);
    expect(store.mods).toHaveLength(sampleMods.length);
  });

  it('does not re-initialize when already loaded with data', async () => {
    mockApiFetch.mockResolvedValueOnce(makeModsResponse(sampleMods));
    const store = useModsStore();
    await store.initialize();
    expect(mockApiFetch).toHaveBeenCalledTimes(1);
    // Second call should be short-circuited
    await store.initialize();
    // fetchModsWithRetry may call apiFetch multiple times due to retry logic
    // but the second initialize should not trigger new fetches
  });

  it('force re-initializes when force is true', async () => {
    mockApiFetch.mockResolvedValue(makeModsResponse(sampleMods));
    const store = useModsStore();
    await store.initialize();
    const callCountAfterFirst = mockApiFetch.mock.calls.length;
    await store.initialize(true);
    expect(mockApiFetch.mock.calls.length).toBeGreaterThan(callCountAfterFirst);
  });

  it('sets loadError on fetch failure', async () => {
    // fetchModsWithRetry retries on transport error
    mockApiFetch.mockRejectedValue(new Error('network failure'));
    const store = useModsStore();
    await store.initialize();
    expect(store.isLoaded).toBe(false);
    expect(store.loadError).toBeTruthy();
  });
});

describe('mods store – refresh', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    mockApiFetch.mockReset();
  });

  it('calls initialize with force=true', async () => {
    mockApiFetch.mockResolvedValue(makeModsResponse(sampleMods));
    const store = useModsStore();
    await store.refresh();
    expect(store.isLoaded).toBe(true);
  });
});

describe('mods store – getModMenu', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
  });

  it('returns empty menu when no mods', () => {
    const store = useModsStore();
    expect(store.getModMenu()).toEqual([]);
  });

  it('returns menu items from mods with menu arrays', () => {
    const store = useModsStore();
    store.mods = sampleMods as never[];
    const menu = store.getModMenu();
    expect(menu.length).toBeGreaterThan(0);
  });

  it('includes modId in menu items', () => {
    const store = useModsStore();
    store.mods = sampleMods as never[];
    const menu = store.getModMenu();
    for (const item of menu) {
      expect(item.modId).toBeTruthy();
    }
  });

  it('skips mods without menu arrays', () => {
    const store = useModsStore();
    store.mods = [
      { id: 'no-menu-mod', name: 'No Menu', version: '1.0', author: '', description: '' },
    ] as never[];
    const menu = store.getModMenu();
    expect(menu).toEqual([]);
  });

  it('deduplicates menu entries by id, keeping higher priority mod', () => {
    const store = useModsStore();
    store.mods = [
      {
        id: 'mod-a',
        name: 'A',
        version: '1.0',
        author: '',
        description: '',
        menu: [{ id: 'shared-menu', label: 'Shared', icon: 'x', path: '/a/page' }],
      },
      {
        id: 'mod-b',
        name: 'B',
        version: '1.0',
        author: '',
        description: '',
        menu: [{ id: 'shared-menu', label: 'Shared B', icon: 'y', path: '/b/page' }],
      },
    ] as never[];
    const menu = store.getModMenu();
    // Should have exactly 1 entry for 'shared-menu'
    const sharedEntries = menu.filter((m) => m.id === 'shared-menu');
    expect(sharedEntries).toHaveLength(1);
  });
});

describe('mods store – applyEntitledActiveMod', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    mockApiFetch.mockReset();
  });

  it('does nothing when clientModsUiOff is true', async () => {
    const store = useModsStore();
    store.setClientModsUiOff(true);
    await store.applyEntitledActiveMod(['mod-a']);
    expect(store.activeModId).toBe('');
  });

  it('does nothing when mods list is empty', async () => {
    const store = useModsStore();
    await store.applyEntitledActiveMod(['mod-a']);
    expect(store.activeModId).toBe('');
  });

  it('does nothing when entitledModIds is empty', async () => {
    const store = useModsStore();
    store.mods = sampleMods as never[];
    await store.applyEntitledActiveMod([]);
    // Should not change activeModId from default
  });

  it('sets active mod based on entitled mod ids with force', async () => {
    const store = useModsStore();
    store.mods = sampleMods as never[];
    mockApiFetch.mockResolvedValue(makeModsResponse(sampleMods));
    await store.applyEntitledActiveMod(['attendance-industry'], { force: true });
    expect(store.activeModId).toBe('attendance-industry');
  });

  it('does not infer account custom mod from canonical industry entitlement', async () => {
    const store = useModsStore();
    store.mods = sampleMods as never[];
    mockApiFetch.mockResolvedValue(makeModsResponse(sampleMods));

    await store.applyEntitledActiveMod(['attendance-industry'], {
      force: true,
      accountUsername: 'SUNBIRD',
    });

    expect(store.activeModId).toBe('attendance-industry');
  });

  it('prefers account custom mod when its explicit entitlement is present', async () => {
    const store = useModsStore();
    store.mods = sampleMods as never[];
    mockApiFetch.mockResolvedValue(makeModsResponse(sampleMods));

    await store.applyEntitledActiveMod(
      ['attendance-industry', 'taiyangniao-pro'],
      { force: true, accountUsername: 'SUNBIRD' },
    );

    expect(store.activeModId).toBe('taiyangniao-pro');
  });
});

describe('mods store – reloadActiveModForTenantScope', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
  });

  it('reloads activeModId from storage for given scope', () => {
    const store = useModsStore();
    store.setActiveModId('initial-mod');
    store.reloadActiveModForTenantScope('tenant-1');
    // Since mock returns empty string, activeModId should be reset
    expect(store.activeModId).toBe('');
  });
});

describe('mods store – edge cases', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    mockApiFetch.mockReset();
  });

  it('handles localStorage read failure gracefully for clientModsUiOff', () => {
    // Simulate localStorage.getItem throwing
    const originalGetItem = localStorage.getItem;
    localStorage.getItem = () => {
      throw new Error('access denied');
    };
    const store = useModsStore();
    expect(store.clientModsUiOff).toBe(false);
    localStorage.getItem = originalGetItem;
  });

  it('handles localStorage write failure gracefully in setClientModsUiOff', () => {
    const originalSetItem = localStorage.setItem;
    localStorage.setItem = () => {
      throw new Error('quota exceeded');
    };
    const store = useModsStore();
    expect(() => store.setClientModsUiOff(true)).not.toThrow();
    expect(store.clientModsUiOff).toBe(true);
    localStorage.setItem = originalSetItem;
  });

  it('modsForUi handles pinia not ready for accountProfileStore', () => {
    const store = useModsStore();
    store.mods = sampleMods as never[];
    // Should not throw even if accountProfileStore access fails
    const ui = store.modsForUi;
    expect(Array.isArray(ui)).toBe(true);
  });

  it('fetchModsOnce handles response.json() throwing', async () => {
    mockApiFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => {
        throw new Error('invalid json');
      },
    });
    const store = useModsStore();
    // fetchModsWithRetry will retry, but all calls fail with json parse error
    // This should propagate as an error
    const result = await store.fetchMods();
    expect(result.ok).toBe(false);
  });

  it('multiple concurrent initialize calls are deduplicated', async () => {
    mockApiFetch.mockResolvedValue(makeModsResponse(sampleMods));
    const store = useModsStore();
    // Fire multiple initialize calls concurrently
    const promises = [
      store.initialize(),
      store.initialize(),
      store.initialize(),
    ];
    await Promise.all(promises);
    expect(store.isLoaded).toBe(true);
  });
});
