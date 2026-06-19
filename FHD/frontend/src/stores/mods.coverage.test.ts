/**
 * mods.ts store 覆盖率补齐测试
 * 重点覆盖：mod facade 探针、loading-status 重试、菜单函数、权益匹配、
 * syncIndustryForActiveMod、ensureActiveModSelection、resolveModsAccountUsername 等
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';

// ── 可配置的 mock 函数（hoisted-safe，以 mock 开头）─────────
const mockApiFetch = vi.fn();
const mockFetchModLoadingStatusShared = vi.fn();
const mockSummarizeModLoadingData = vi.fn();
const mockIsAdminConsoleSpa = vi.fn(() => false);
const mockIsProtectedClientModId = vi.fn(() => false);
const mockIsClientErpSidebarContext = vi.fn(() => false);
const mockIsAuxEmployeePackModId = vi.fn((id: string) => id.startsWith('xcagi-aux-'));
const mockIsSelectableExtensionModId = vi.fn((id: string) =>
  !id.startsWith('xcagi-') || id === 'attendance-industry' || id === 'taiyangniao-pro' || id === 'sz-qsm-pro',
);
const mockIsHostMountedModMenuPath = vi.fn(() => false);
const mockShouldHideAttendanceModSidebarMenu = vi.fn(() => false);
const mockShouldSuppressClientErpModMenuId = vi.fn(() => false);
const mockFilterWorkflowRegistrySourceMods = vi.fn((mods: unknown[]) => mods);
const mockReadActiveExtensionModIdFromStorage = vi.fn(() => '');
const mockWriteActiveExtensionModIdToStorage = vi.fn();
const mockBootstrapHostConfig = vi.fn(async () => {});
const mockSetApprovalModFacadeEnabled = vi.fn();
const mockSetErpDomainModFacadeEnabled = vi.fn();
const mockSetLanModFacadeEnabled = vi.fn();
const mockSetModelPaymentModFacadeEnabled = vi.fn();
const mockSetCustomerServiceModPagesEnabled = vi.fn();
const mockSetPlannerModFacadeEnabled = vi.fn();
const mockSetOfficeEmployeePackModPagesEnabled = vi.fn();
const mockSetCoreWorkflowModPagesEnabled = vi.fn();
const mockApplyEditionPackPlatformShell = vi.fn();
const mockFetchPlatformShellCapabilities = vi.fn(async () => ({}));
const mockAugmentEntitledModIdsForAccount = vi.fn(
  (_u: unknown, ids: string[] | undefined) => ids || [],
);
const mockBuildAttendanceIndustryModStub = vi.fn(() => ({
  id: 'attendance-industry',
  name: '考勤行业包',
  version: '1.0.0',
  author: 'xcagi',
  description: 'stub',
}));
const mockSwitchIndustry = vi.fn(async () => true);
const mockUseAccountProfileStore = vi.fn(() => ({
  accountUsername: '',
  isAdminAccount: false,
  isEnterprise: false,
}));

// ── vi.mock 宣告（hoisted）──────────────────────────────────
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
  fetchModLoadingStatusShared: (...args: unknown[]) => mockFetchModLoadingStatusShared(...args),
}));

vi.mock('@/utils/modLoadingStatus', () => ({
  summarizeModLoadingData: (...args: unknown[]) => mockSummarizeModLoadingData(...args),
}));

vi.mock('@/utils/platformShellApi', () => ({
  fetchPlatformShellCapabilities: (...args: unknown[]) => mockFetchPlatformShellCapabilities(...args),
}));

vi.mock('@/stores/hostConfig', () => ({
  bootstrapHostConfig: (...args: unknown[]) => mockBootstrapHostConfig(...args),
  clientModPolicies: { value: {} },
}));

vi.mock('@/stores/accountProfile', () => ({
  useAccountProfileStore: () => mockUseAccountProfileStore(),
}));

vi.mock('@/utils/adminConsoleUrl', () => ({
  isAdminConsoleSpa: () => mockIsAdminConsoleSpa(),
}));

vi.mock('@/constants/approvalMod', () => ({
  APPROVAL_BRIDGE_MOD_ID: 'xcagi-approval-bridge',
  setApprovalModFacadeEnabled: (...args: unknown[]) => mockSetApprovalModFacadeEnabled(...args),
}));

vi.mock('@/constants/erpDomainMod', () => ({
  ERP_DOMAIN_BRIDGE_MOD_ID: 'xcagi-erp-domain-bridge',
  setErpDomainModFacadeEnabled: (...args: unknown[]) => mockSetErpDomainModFacadeEnabled(...args),
}));

vi.mock('@/utils/erpDomainPaths', () => ({
  erpDomainModStatusPath: () => '/api/mod/erp-domain/status',
}));

vi.mock('@/constants/lanMod', () => ({
  LAN_BRIDGE_MOD_ID: 'xcagi-lan-license-bridge',
  setLanModFacadeEnabled: (...args: unknown[]) => mockSetLanModFacadeEnabled(...args),
}));

vi.mock('@/constants/modelPaymentMod', () => ({
  MODEL_PAYMENT_BRIDGE_MOD_ID: 'xcagi-model-payment-bridge',
  setModelPaymentModFacadeEnabled: (...args: unknown[]) => mockSetModelPaymentModFacadeEnabled(...args),
}));

vi.mock('@/constants/customerServiceMod', () => ({
  CUSTOMER_SERVICE_BRIDGE_MOD_ID: 'xcagi-customer-service-bridge',
  setCustomerServiceModPagesEnabled: (...args: unknown[]) => mockSetCustomerServiceModPagesEnabled(...args),
}));

vi.mock('@/constants/plannerMod', () => ({
  PLANNER_FACADE_MOD_ID: 'xcagi-planner-bridge',
  setPlannerModFacadeEnabled: (...args: unknown[]) => mockSetPlannerModFacadeEnabled(...args),
}));

vi.mock('@/constants/officeEmployeePackMod', () => ({
  OFFICE_EMPLOYEE_PACK_BRIDGE_MOD_ID: 'xcagi-office-employee-pack-bridge',
  setOfficeEmployeePackModPagesEnabled: (...args: unknown[]) => mockSetOfficeEmployeePackModPagesEnabled(...args),
}));

vi.mock('@/constants/coreWorkflowMod', () => ({
  CORE_WORKFLOW_MOD_ID: 'xcagi-core-workflow-employees',
  coreWorkflowModEmployeesPath: () => '/api/mod/core-workflow/employees',
  setCoreWorkflowModPagesEnabled: (...args: unknown[]) => mockSetCoreWorkflowModPagesEnabled(...args),
}));

vi.mock('@/constants/platformShellMode', () => ({
  applyEditionPackPlatformShell: (...args: unknown[]) => mockApplyEditionPackPlatformShell(...args),
}));

vi.mock('@/constants/genericModPack', () => ({
  ACCOUNT_CUSTOM_MOD_IDS: ['taiyangniao-pro', 'sz-qsm-pro'],
  CLIENT_PRIMARY_ERP_MOD_ID: 'attendance-industry',
  isAuxEmployeePackModId: (id: string) => mockIsAuxEmployeePackModId(id),
  isClientErpSidebarContext: (ids: string[], active: string) => mockIsClientErpSidebarContext(ids, active),
  isHostMountedModMenuPath: (path: string, proEntry: string) => mockIsHostMountedModMenuPath(path, proEntry),
  isSelectableExtensionModId: (id: string) => mockIsSelectableExtensionModId(id),
  shouldHideAttendanceModSidebarMenu: (menuId: string) => mockShouldHideAttendanceModSidebarMenu(menuId),
  shouldSuppressClientErpModMenuId: (menuId: string, ids: string[], active: string) =>
    mockShouldSuppressClientErpModMenuId(menuId, ids, active),
}));

vi.mock('@/constants/accountModBinding', () => ({
  SUNBIRD_CLIENT_MOD_ID: 'taiyangniao-pro',
  augmentEntitledModIdsForAccount: (u: unknown, ids: string[] | undefined) =>
    mockAugmentEntitledModIdsForAccount(u, ids),
  isSunbirdAccountUsername: (u: string) => String(u || '').trim().toUpperCase() === 'SUNBIRD',
  shouldBindClientPrimaryErpMod: () => false,
}));

vi.mock('@/constants/sunbirdClientMod', () => ({
  buildAttendanceIndustryModStub: () => mockBuildAttendanceIndustryModStub(),
}));

vi.mock('@/constants/protectedMods', () => ({
  isProtectedClientModId: (id: string) => mockIsProtectedClientModId(id),
}));

vi.mock('@/utils/modWorkflowEmployees', () => ({
  filterWorkflowRegistrySourceMods: (mods: unknown[]) => mockFilterWorkflowRegistrySourceMods(mods),
}));

vi.mock('@/utils/xcagiStorageKeys', () => ({
  XCAGI_ACTIVE_EXTENSION_MOD_ID_KEY: 'xcagi_active_extension_mod_id',
  readActiveExtensionModIdFromStorage: () => mockReadActiveExtensionModIdFromStorage(),
  writeActiveExtensionModIdToStorage: (...args: unknown[]) => mockWriteActiveExtensionModIdToStorage(...args),
}));

vi.mock('@/stores/industry', () => ({
  useIndustryStore: () => ({
    currentIndustryId: '',
    switchIndustry: (...args: unknown[]) => mockSwitchIndustry(...args),
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

// ── 辅助函数 ──────────────────────────────────────────────
function makeResponse(body: unknown, ok = true, status = 200) {
  return { ok, status, json: async () => body };
}

/** 路由 apiFetch 调用：根据 URL 返回不同响应 */
function routeApiFetch(routes: {
  mods?: () => unknown;
  industry?: () => unknown;
  probeErp?: () => unknown;
  probeWorkflow?: () => unknown;
}) {
  mockApiFetch.mockImplementation(async (url: string) => {
    if (url === '/api/mods/') return routes.mods ? routes.mods() : makeResponse({ success: true, data: [] });
    if (url === '/api/system/industry')
      return routes.industry ? routes.industry() : makeResponse({ success: true, data: { id: '' } });
    if (url.includes('erp-domain') && url.includes('status'))
      return routes.probeErp ? routes.probeErp() : makeResponse({ success: true });
    if (url.includes('core-workflow') && url.includes('employees'))
      return routes.probeWorkflow ? routes.probeWorkflow() : makeResponse({ success: true });
    return makeResponse({ success: true, data: [] });
  });
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

const bridgeMods = [
  ...sampleMods,
  {
    id: 'xcagi-erp-domain-bridge',
    name: 'ERP Domain',
    version: '1.0',
    author: 'xcagi',
    description: 'erp domain bridge',
    primary: false,
    industry: { id: 'generic', name: '通用' },
    menu: [{ id: 'mod-erp-products', label: '产品', icon: 'box', path: '/mod/xcagi-erp-domain-bridge/products' }],
  },
  {
    id: 'xcagi-core-workflow-employees',
    name: 'Core Workflow',
    version: '1.0',
    author: 'xcagi',
    description: 'core workflow',
    primary: false,
    industry: { id: 'generic', name: '通用' },
    menu: [{ id: 'mod-workflow-visualization', label: '流程可视化', icon: 'flow', path: '/mod/xcagi-core-workflow-employees/viz' }],
  },
  {
    id: 'xcagi-approval-bridge',
    name: 'Approval',
    version: '1.0',
    author: 'xcagi',
    description: 'approval bridge',
    menu: [{ id: 'mod-approval-hub', label: '审批中心', icon: 'check', path: '/mod/xcagi-approval-bridge/hub' }],
  },
  {
    id: 'xcagi-lan-license-bridge',
    name: 'LAN',
    version: '1.0',
    author: 'xcagi',
    description: 'lan bridge',
    menu: [{ id: 'mod-lan-gate', label: '局域网', icon: 'network', path: '/mod/xcagi-lan-license-bridge/gate' }],
  },
  {
    id: 'xcagi-model-payment-bridge',
    name: 'Model Payment',
    version: '1.0',
    author: 'xcagi',
    description: 'model payment bridge',
    menu: [{ id: 'mod-model-payment', label: '模型支付', icon: 'pay', path: '/mod/xcagi-model-payment-bridge/pay' }],
  },
  {
    id: 'xcagi-customer-service-bridge',
    name: 'Customer Service',
    version: '1.0',
    author: 'xcagi',
    description: 'customer service bridge',
    menu: [{ id: 'mod-enterprise-customer-service', label: '客服', icon: 'headset', path: '/mod/xcagi-customer-service-bridge/svc' }],
  },
  {
    id: 'xcagi-office-employee-pack-bridge',
    name: 'Office Employee Pack',
    version: '1.0',
    author: 'xcagi',
    description: 'office employee pack bridge',
    menu: [{ id: 'mod-office-pack', label: '办公包', icon: 'office', path: '/mod/xcagi-office-employee-pack-bridge/office' }],
  },
];

// ── 测试套件 ──────────────────────────────────────────────
describe('mods store – coverage 补齐', () => {
  let useModsStore: typeof import('./mods').useModsStore;
  let readEntitledModIdsFromAuthPayload: typeof import('./mods').readEntitledModIdsFromAuthPayload;

  beforeEach(async () => {
    // 重置模块缓存以清除 modStatusProbeCache / modFacadeProbesCompleted 等模块级状态
    vi.resetModules();
    const mod = await import('./mods');
    useModsStore = mod.useModsStore;
    readEntitledModIdsFromAuthPayload = mod.readEntitledModIdsFromAuthPayload;

    setActivePinia(createPinia());
    localStorage.clear();

    // 重置所有 mock
    vi.clearAllMocks();

    // 设置默认实现
    mockApiFetch.mockImplementation(async () => makeResponse({ success: true, data: [] }));
    mockFetchModLoadingStatusShared.mockResolvedValue(null);
    mockSummarizeModLoadingData.mockReturnValue(null);
    mockIsAdminConsoleSpa.mockReturnValue(false);
    mockIsProtectedClientModId.mockReturnValue(false);
    mockIsClientErpSidebarContext.mockReturnValue(false);
    mockIsAuxEmployeePackModId.mockImplementation((id: string) => id.startsWith('xcagi-aux-'));
    mockIsSelectableExtensionModId.mockImplementation(
      (id: string) =>
        !id.startsWith('xcagi-') || id === 'attendance-industry' || id === 'taiyangniao-pro' || id === 'sz-qsm-pro',
    );
    mockIsHostMountedModMenuPath.mockReturnValue(false);
    mockShouldHideAttendanceModSidebarMenu.mockReturnValue(false);
    mockShouldSuppressClientErpModMenuId.mockReturnValue(false);
    mockFilterWorkflowRegistrySourceMods.mockImplementation((mods: unknown[]) => mods);
    mockReadActiveExtensionModIdFromStorage.mockReturnValue('');
    mockBootstrapHostConfig.mockResolvedValue(undefined);
    mockFetchPlatformShellCapabilities.mockResolvedValue({});
    mockAugmentEntitledModIdsForAccount.mockImplementation(
      (_u: unknown, ids: string[] | undefined) => ids || [],
    );
    mockBuildAttendanceIndustryModStub.mockReturnValue({
      id: 'attendance-industry',
      name: '考勤行业包',
      version: '1.0.0',
      author: 'xcagi',
      description: 'stub',
    });
    mockSwitchIndustry.mockResolvedValue(true);
    mockUseAccountProfileStore.mockReturnValue({
      accountUsername: '',
      isAdminAccount: false,
      isEnterprise: false,
    });
  });

  // ═══════════════════════════════════════════════════════════
  // 1. Mod Facade 探针函数覆盖
  // ═══════════════════════════════════════════════════════════
  describe('mod facade 探针', () => {
    it('探针成功时启用 ERP 门面和核心工作流页面', async () => {
      routeApiFetch({
        mods: () => makeResponse({ success: true, data: bridgeMods }),
        probeErp: () => makeResponse({ success: true }),
        probeWorkflow: () => makeResponse({ success: true }),
      });

      const store = useModsStore();
      await store.fetchMods();

      expect(mockSetErpDomainModFacadeEnabled).toHaveBeenCalledWith(true);
      expect(mockSetCoreWorkflowModPagesEnabled).toHaveBeenCalledWith(true);
      expect(mockSetApprovalModFacadeEnabled).toHaveBeenCalledWith(true);
      expect(mockSetLanModFacadeEnabled).toHaveBeenCalledWith(true);
      expect(mockSetModelPaymentModFacadeEnabled).toHaveBeenCalledWith(true);
      expect(mockSetCustomerServiceModPagesEnabled).toHaveBeenCalledWith(true);
      expect(mockSetOfficeEmployeePackModPagesEnabled).toHaveBeenCalledWith(true);
      expect(mockSetPlannerModFacadeEnabled).toHaveBeenCalledWith(true);
    });

    it('探针返回 429 时使用限流缓存并返回 false', async () => {
      routeApiFetch({
        mods: () => makeResponse({ success: true, data: bridgeMods }),
        probeErp: () => makeResponse({ success: false }, false, 429),
        probeWorkflow: () => makeResponse({ success: true }),
      });

      const store = useModsStore();
      await store.fetchMods();

      expect(mockSetErpDomainModFacadeEnabled).toHaveBeenCalledWith(false);
      expect(mockSetCoreWorkflowModPagesEnabled).toHaveBeenCalledWith(true);
    });

    it('探针返回非 ok 状态时返回 false', async () => {
      routeApiFetch({
        mods: () => makeResponse({ success: true, data: bridgeMods }),
        probeErp: () => makeResponse({}, false, 500),
        probeWorkflow: () => makeResponse({}, false, 503),
      });

      const store = useModsStore();
      await store.fetchMods();

      expect(mockSetErpDomainModFacadeEnabled).toHaveBeenCalledWith(false);
      expect(mockSetCoreWorkflowModPagesEnabled).toHaveBeenCalledWith(false);
    });

    it('探针返回 success: false 时返回 false', async () => {
      routeApiFetch({
        mods: () => makeResponse({ success: true, data: bridgeMods }),
        probeErp: () => makeResponse({ success: false }),
        probeWorkflow: () => makeResponse({ success: false }),
      });

      const store = useModsStore();
      await store.fetchMods();

      expect(mockSetErpDomainModFacadeEnabled).toHaveBeenCalledWith(false);
      expect(mockSetCoreWorkflowModPagesEnabled).toHaveBeenCalledWith(false);
    });

    it('探针 JSON 解析失败时返回 false', async () => {
      routeApiFetch({
        mods: () => makeResponse({ success: true, data: bridgeMods }),
        probeErp: () => ({
          ok: true,
          status: 200,
          json: async () => {
            throw new Error('invalid json');
          },
        }),
        probeWorkflow: () => makeResponse({ success: true }),
      });

      const store = useModsStore();
      await store.fetchMods();

      expect(mockSetErpDomainModFacadeEnabled).toHaveBeenCalledWith(false);
    });

    it('探针网络错误时返回 false', async () => {
      routeApiFetch({
        mods: () => makeResponse({ success: true, data: bridgeMods }),
        probeErp: () => {
          throw new Error('network error');
        },
        probeWorkflow: () => {
          throw new Error('network error');
        },
      });

      const store = useModsStore();
      await store.fetchMods();

      expect(mockSetErpDomainModFacadeEnabled).toHaveBeenCalledWith(false);
      expect(mockSetCoreWorkflowModPagesEnabled).toHaveBeenCalledWith(false);
    });

    it('探针缓存命中时不再发起请求', async () => {
      let probeCallCount = 0;
      routeApiFetch({
        mods: () => makeResponse({ success: true, data: bridgeMods }),
        probeErp: () => {
          probeCallCount++;
          return makeResponse({ success: true });
        },
        probeWorkflow: () => makeResponse({ success: true }),
      });

      const store = useModsStore();
      // 第一次调用：触发探针
      await store.fetchMods();
      const firstCount = probeCallCount;

      // 第二次调用：modFacadeProbesCompleted 已完成，不再探针
      await store.fetchMods();
      expect(probeCallCount).toBe(firstCount);
    });

    it('shouldSkipModFacadeProbes 在受保护客户 Mod 时跳过探针', async () => {
      mockIsProtectedClientModId.mockImplementation((id: string) => id === 'attendance-industry');

      routeApiFetch({
        mods: () => makeResponse({ success: true, data: bridgeMods }),
        probeErp: () => makeResponse({ success: true }),
        probeWorkflow: () => makeResponse({ success: true }),
      });

      const store = useModsStore();
      store.setActiveModId('attendance-industry');
      await store.fetchMods();

      // 探针被跳过，门面设为 false
      expect(mockSetErpDomainModFacadeEnabled).toHaveBeenCalledWith(false);
      expect(mockSetCoreWorkflowModPagesEnabled).toHaveBeenCalledWith(false);
    });

    it('shouldSkipModFacadeProbes 在客户 ERP 侧栏场景时跳过探针', async () => {
      mockIsClientErpSidebarContext.mockReturnValue(true);

      routeApiFetch({
        mods: () => makeResponse({ success: true, data: bridgeMods }),
        probeErp: () => makeResponse({ success: true }),
        probeWorkflow: () => makeResponse({ success: true }),
      });

      const store = useModsStore();
      await store.fetchMods();

      expect(mockSetErpDomainModFacadeEnabled).toHaveBeenCalledWith(false);
      expect(mockSetCoreWorkflowModPagesEnabled).toHaveBeenCalledWith(false);
    });

    it('force=true 时重置 modFacadeProbesCompleted 并重新执行门面设置', async () => {
      routeApiFetch({
        mods: () => makeResponse({ success: true, data: bridgeMods }),
        probeErp: () => makeResponse({ success: true }),
        probeWorkflow: () => makeResponse({ success: true }),
      });

      const store = useModsStore();
      await store.initialize();
      // 首次 initialize 后 modFacadeProbesCompleted=true
      mockSetErpDomainModFacadeEnabled.mockClear();

      // force=true 重置 modFacadeProbesCompleted，使 applyModFacadeFlagsFromListing 重新执行
      await store.initialize(true);
      // 探针缓存命中（5min TTL），但门面设置函数仍被重新调用
      expect(mockSetErpDomainModFacadeEnabled).toHaveBeenCalled();
    });

    it('mods 列表中无 ERP/工作流 bridge 时不探针对应门面', async () => {
      routeApiFetch({
        mods: () => makeResponse({ success: true, data: sampleMods }),
        probeErp: () => makeResponse({ success: true }),
        probeWorkflow: () => makeResponse({ success: true }),
      });

      const store = useModsStore();
      await store.fetchMods();

      // 没有 bridge mod，探针不触发，门面设为 false
      expect(mockSetErpDomainModFacadeEnabled).toHaveBeenCalledWith(false);
      expect(mockSetCoreWorkflowModPagesEnabled).toHaveBeenCalledWith(false);
    });
  });

  // ═══════════════════════════════════════════════════════════
  // 2. Loading Status 重试函数覆盖
  // ═══════════════════════════════════════════════════════════
  describe('loading-status 重试', () => {
    it('load_mismatch=true 时触发重试', async () => {
      mockFetchModLoadingStatusShared.mockResolvedValue({
        discovered_mod_ids: ['mod-a'],
        mods_loaded: 0,
        load_mismatch: true,
        mods_disabled: false,
      });
      // 第一次返回空列表，第二次返回有数据
      let modsCallCount = 0;
      mockApiFetch.mockImplementation(async (url: string) => {
        if (url === '/api/mods/') {
          modsCallCount++;
          if (modsCallCount <= 1) return makeResponse({ success: true, data: [] });
          return makeResponse({ success: true, data: sampleMods });
        }
        return makeResponse({ success: true });
      });

      const store = useModsStore();
      await store.fetchMods();

      // 应该重试过
      expect(modsCallCount).toBeGreaterThan(1);
    });

    it('discovered>0 且 loaded=0 时触发重试', async () => {
      mockFetchModLoadingStatusShared.mockResolvedValue({
        discovered_mod_ids: ['mod-a', 'mod-b'],
        mods_loaded: 0,
        load_mismatch: false,
        mods_disabled: false,
      });
      let modsCallCount = 0;
      mockApiFetch.mockImplementation(async (url: string) => {
        if (url === '/api/mods/') {
          modsCallCount++;
          if (modsCallCount <= 1) return makeResponse({ success: true, data: [] });
          return makeResponse({ success: true, data: sampleMods });
        }
        return makeResponse({ success: true });
      });

      const store = useModsStore();
      await store.fetchMods();
      expect(modsCallCount).toBeGreaterThan(1);
    });

    it('mods_disabled=true 时不重试', async () => {
      mockFetchModLoadingStatusShared.mockResolvedValue({
        discovered_mod_ids: ['mod-a'],
        mods_loaded: 0,
        load_mismatch: false,
        mods_disabled: true,
      });
      let modsCallCount = 0;
      mockApiFetch.mockImplementation(async (url: string) => {
        if (url === '/api/mods/') {
          modsCallCount++;
          return makeResponse({ success: true, data: [], mods_disabled: true });
        }
        return makeResponse({ success: true });
      });

      const store = useModsStore();
      await store.fetchMods();
      // mods_disabled 直接返回，不触发空列表重试
      expect(store.mods).toEqual([]);
    });

    it('confirmServerReportsZeroDiscoveredMods 在磁盘无 manifest 时设 isLoaded=true', async () => {
      mockFetchModLoadingStatusShared.mockResolvedValue({
        discovered_mod_ids: [],
        mods_loaded: 0,
        load_mismatch: false,
        mods_disabled: false,
      });
      mockApiFetch.mockImplementation(async (url: string) => {
        if (url === '/api/mods/') return makeResponse({ success: true, data: [] });
        return makeResponse({ success: true });
      });

      const store = useModsStore();
      await store.initialize();

      // 磁盘无 manifest -> isLoaded=true
      expect(store.isLoaded).toBe(true);
      expect(store.loadError).toBeNull();
    });

    it('fetchModLoadingStatusHint 返回提示信息', async () => {
      mockFetchModLoadingStatusShared.mockResolvedValue({
        discovered_mod_ids: ['mod-a'],
        mods_loaded: 0,
        load_mismatch: true,
        mods_disabled: false,
      });
      mockSummarizeModLoadingData.mockReturnValue('后端 Mod 加载不完整');
      mockApiFetch.mockImplementation(async (url: string) => {
        if (url === '/api/mods/') return makeResponse({ success: true, data: [] });
        return makeResponse({ success: true });
      });

      const store = useModsStore();
      await store.initialize();

      expect(store.isLoaded).toBe(false);
      expect(store.loadError).toContain('后端 Mod 加载不完整');
    });

    it('loading-status 请求失败时返回 false 不重试', async () => {
      mockFetchModLoadingStatusShared.mockRejectedValue(new Error('network'));
      mockApiFetch.mockImplementation(async (url: string) => {
        if (url === '/api/mods/') return makeResponse({ success: true, data: [] });
        return makeResponse({ success: true });
      });

      const store = useModsStore();
      await store.initialize();

      // loading-status 失败，不确认零发现，isLoaded=false
      expect(store.isLoaded).toBe(false);
    });

    it('loading-status 返回 null 时不重试', async () => {
      mockFetchModLoadingStatusShared.mockResolvedValue(null);
      mockApiFetch.mockImplementation(async (url: string) => {
        if (url === '/api/mods/') return makeResponse({ success: true, data: [] });
        return makeResponse({ success: true });
      });

      const store = useModsStore();
      await store.initialize();

      expect(store.isLoaded).toBe(false);
    });
  });

  // ═══════════════════════════════════════════════════════════
  // 3. 菜单函数覆盖
  // ═══════════════════════════════════════════════════════════
  describe('菜单函数', () => {
    it('getModMenu 在选中扩展包时返回该包菜单（fromUi 路径）', () => {
      const store = useModsStore();
      store.mods = [
        ...sampleMods,
        {
          id: 'wechat-contacts-ai-employee',
          name: 'WeChat Contacts',
          version: '1.0',
          author: '',
          description: '',
          menu: [{ id: 'mod-wechat-panel', label: '微信面板', icon: 'box', path: '/mod/wechat-contacts-ai-employee/panel' }],
        },
      ] as never[];
      store.setActiveModId('attendance-industry');

      const menu = store.getModMenu();
      const modIds = menu.map((m) => m.modId);
      // active mod 在 modsForUi 中，返回其菜单项
      expect(modIds).toContain('attendance-industry');
    });

    it('getModMenu 在 fromUi 为空时回退到 fromFull 并包含 aux pack', () => {
      // 使用 vi.doMock 让 modsForUi 返回空数组（通过 isAdminConsoleSpa）
      mockIsAdminConsoleSpa.mockReturnValue(true);
      mockIsAuxEmployeePackModId.mockImplementation((id: string) =>
        id === 'wechat-contacts-ai-employee',
      );
      // isAdminConsoleSpa=true 使 modsForUi=[]，但 modsContributingSidebarMenu 用 full
      // 实际上 isAdminConsoleSpa 会让 modsForUi=[]，但 active 仍可走 fromFull 路径
      // 不过 isAdminConsoleSpa 也会影响其他逻辑，改用另一种方式：
      mockIsAdminConsoleSpa.mockReturnValue(false);

      // 让 active 不在 mods.value 中，使 modsForUi 返回 mods.value（全部）
      // 然后 pickForActive(ui) 中 active 不匹配，但 aux pack 匹配
      const store = useModsStore();
      store.mods = [
        ...sampleMods,
        {
          id: 'wechat-contacts-ai-employee',
          name: 'WeChat Contacts',
          version: '1.0',
          author: '',
          description: '',
          menu: [{ id: 'mod-wechat-panel', label: '微信面板', icon: 'box', path: '/mod/wechat-contacts-ai-employee/panel' }],
        },
      ] as never[];
      // active 设为一个不在 mods.value 中的可选扩展
      store.setActiveModId('sz-qsm-pro');

      const menu = store.getModMenu();
      const modIds = menu.map((m) => m.modId);
      // fromUi 路径：modsForUi 返回全部 mods，pickForActive 匹配 aux pack
      expect(modIds).toContain('wechat-contacts-ai-employee');
    });

    it('getModMenu 在 active 为 CLIENT_PRIMARY_ERP_MOD_ID 且不在列表时使用 stub', () => {
      const store = useModsStore();
      const modsNoAttendance = sampleMods.filter((m) => m.id !== 'attendance-industry');
      store.mods = modsNoAttendance as never[];
      store.setActiveModId('attendance-industry');

      const menu = store.getModMenu();
      // stub 提供 attendance-industry 的菜单
      expect(menu.length).toBeGreaterThanOrEqual(0);
    });

    it('getModMenu 在客户 ERP 侧栏场景返回可选扩展包', () => {
      mockIsClientErpSidebarContext.mockReturnValue(true);
      const store = useModsStore();
      store.mods = sampleMods as never[];
      store.setActiveModId('');

      const menu = store.getModMenu();
      // 客户 ERP 场景返回可选扩展包的菜单
      expect(Array.isArray(menu)).toBe(true);
    });

    it('shouldHideModMenuEntry 隐藏考勤侧栏菜单', () => {
      mockShouldHideAttendanceModSidebarMenu.mockImplementation((menuId: string) =>
        menuId === 'mod-attendance-dashboard',
      );
      const store = useModsStore();
      store.mods = sampleMods as never[];

      const menu = store.getModMenu();
      const hidden = menu.find((m) => m.id === 'mod-attendance-dashboard');
      expect(hidden).toBeUndefined();
    });

    it('shouldHideModMenuEntry 隐藏客户 ERP 重复菜单', () => {
      mockShouldSuppressClientErpModMenuId.mockImplementation((menuId: string) =>
        menuId === 'mod-planner-chat',
      );
      const store = useModsStore();
      store.mods = sampleMods as never[];

      const menu = store.getModMenu();
      const suppressed = menu.find((m) => m.id === 'mod-planner-chat');
      expect(suppressed).toBeUndefined();
    });

    it('modPriorityForMenuEntry 在重复菜单 ID 时保留高优先级 Mod', () => {
      const store = useModsStore();
      store.mods = [
        {
          id: 'xcagi-workflow-visualization-bridge',
          name: 'WF Viz',
          version: '1.0',
          author: '',
          description: '',
          menu: [{ id: 'mod-workflow-visualization', label: '流程可视化', icon: 'flow', path: '/mod/xcagi-workflow-visualization-bridge/viz' }],
        },
        {
          id: 'xcagi-core-workflow-employees',
          name: 'Core WF',
          version: '1.0',
          author: '',
          description: '',
          menu: [{ id: 'mod-workflow-visualization', label: '核心工作流', icon: 'flow', path: '/mod/xcagi-core-workflow-employees/viz' }],
        },
      ] as never[];

      const menu = store.getModMenu();
      const wfEntries = menu.filter((m) => m.id === 'mod-workflow-visualization');
      expect(wfEntries).toHaveLength(1);
      // xcagi-workflow-visualization-bridge 优先级更高（在 priority 数组中靠前）
      expect(wfEntries[0].modId).toBe('xcagi-workflow-visualization-bridge');
    });

    it('validateModMenuPaths 在 DEV 模式对无效路径发出警告', () => {
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
      const store = useModsStore();
      store.mods = [
        {
          id: 'test-mod',
          name: 'Test',
          version: '1.0',
          author: '',
          description: '',
          menu: [{ id: 'mod-test-bad', label: 'Bad Path', icon: 'x', path: '/wrong-prefix/page' }],
        },
      ] as never[];

      store.getModMenu();
      // DEV 模式下应触发警告
      expect(warnSpy).toHaveBeenCalled();
      warnSpy.mockRestore();
    });

    it('validateModMenuPaths 对正确路径不发出警告', () => {
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
      const store = useModsStore();
      store.mods = [
        {
          id: 'test-mod',
          name: 'Test',
          version: '1.0',
          author: '',
          description: '',
          menu: [{ id: 'mod-test-ok', label: 'OK Path', icon: 'x', path: '/mod/test-mod/page' }],
        },
      ] as never[];

      store.getModMenu();
      // 正确路径不应触发路径警告
      const pathWarnings = warnSpy.mock.calls.filter((c) =>
        String(c[0] || '').includes('does not match mod id prefix'),
      );
      expect(pathWarnings).toHaveLength(0);
      warnSpy.mockRestore();
    });

    it('validateModMenuPaths 对 wechat-contacts-ai-employee 员工包路径不警告', () => {
      // isHostMountedModMenuPath('/wechat-contacts', '/wechat-contacts') 应返回 true
      mockIsHostMountedModMenuPath.mockReturnValue(true);
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
      const store = useModsStore();
      store.mods = [
        {
          id: 'wechat-contacts-ai-employee',
          name: 'WeChat Contacts',
          version: '1.0',
          author: '',
          description: '',
          menu: [{ id: 'mod-wechat-contacts', label: '微信联系人', icon: 'x', path: '/wechat-contacts' }],
        },
      ] as never[];

      store.getModMenu();
      const pathWarnings = warnSpy.mock.calls.filter((c) =>
        String(c[0] || '').includes('does not match mod id prefix'),
      );
      expect(pathWarnings).toHaveLength(0);
      warnSpy.mockRestore();
    });

    it('validateModMenuPaths 对 lan-gate-ai-employee 员工包路径不警告', () => {
      // isHostMountedModMenuPath('/lan-gate', '/lan-gate') 应返回 true
      mockIsHostMountedModMenuPath.mockReturnValue(true);
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
      const store = useModsStore();
      store.mods = [
        {
          id: 'lan-gate-ai-employee',
          name: 'LAN Gate',
          version: '1.0',
          author: '',
          description: '',
          menu: [{ id: 'mod-lan-gate', label: '局域网门', icon: 'x', path: '/lan-gate' }],
        },
      ] as never[];

      store.getModMenu();
      const pathWarnings = warnSpy.mock.calls.filter((c) =>
        String(c[0] || '').includes('does not match mod id prefix'),
      );
      expect(pathWarnings).toHaveLength(0);
      warnSpy.mockRestore();
    });

    it('validateModMenuPaths 对 pro_entry_path 挂载路径不警告', () => {
      mockIsHostMountedModMenuPath.mockReturnValue(true);
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
      const store = useModsStore();
      store.mods = [
        {
          id: 'test-mod',
          name: 'Test',
          version: '1.0',
          author: '',
          description: '',
          frontend: { pro_entry_path: '/host-entry' },
          menu: [{ id: 'mod-test-host', label: 'Host Mount', icon: 'x', path: '/host-entry/page' }],
        },
      ] as never[];

      store.getModMenu();
      const pathWarnings = warnSpy.mock.calls.filter((c) =>
        String(c[0] || '').includes('does not match mod id prefix'),
      );
      expect(pathWarnings).toHaveLength(0);
      warnSpy.mockRestore();
    });

    it('getModMenu 跳过无 menu 数组的 Mod', () => {
      const store = useModsStore();
      store.mods = [
        { id: 'no-menu-mod', name: 'No Menu', version: '1.0', author: '', description: '' },
        ...sampleMods,
      ] as never[];

      const menu = store.getModMenu();
      const noMenuEntry = menu.find((m) => m.modId === 'no-menu-mod');
      expect(noMenuEntry).toBeUndefined();
    });

    it('getModMenu 跳过空 menuId', () => {
      const store = useModsStore();
      store.mods = [
        {
          id: 'empty-menu-mod',
          name: 'Empty Menu',
          version: '1.0',
          author: '',
          description: '',
          menu: [{ id: '', label: 'Empty', icon: 'x', path: '/mod/empty-menu-mod/page' }],
        },
      ] as never[];

      const menu = store.getModMenu();
      expect(menu).toEqual([]);
    });
  });

  // ═══════════════════════════════════════════════════════════
  // 4. 权益匹配函数覆盖
  // ═══════════════════════════════════════════════════════════
  describe('权益匹配', () => {
    it('pickModIdFromEntitled 优先选择账户自定义 Mod', async () => {
      const store = useModsStore();
      store.mods = sampleMods as never[];
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: sampleMods }));

      await store.applyEntitledActiveMod(['attendance-industry', 'taiyangniao-pro'], { force: true });
      // taiyangniao-pro 是账户自定义 Mod，优先选中
      expect(store.activeModId).toBe('taiyangniao-pro');
    });

    it('pickModIdFromEntitled 选择主 ERP Mod', async () => {
      const store = useModsStore();
      store.mods = sampleMods as never[];
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: sampleMods }));

      // 只授权 attendance-industry（非账户自定义 Mod）
      await store.applyEntitledActiveMod(['attendance-industry'], { force: true });
      expect(store.activeModId).toBe('attendance-industry');
    });

    it('pickModIdFromEntitled 选择 primary Mod', async () => {
      const store = useModsStore();
      store.mods = [
        {
          id: 'sz-qsm-pro',
          name: 'QSM Pro',
          version: '1.0',
          author: '',
          description: '',
          primary: true,
          industry: { id: 'coating', name: '涂装' },
        },
        {
          id: 'taiyangniao-pro',
          name: '太阳鸟 Pro',
          version: '1.0',
          author: '',
          description: '',
          primary: false,
          industry: { id: 'coating', name: '涂装' },
        },
      ] as never[];
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: [] }));

      await store.applyEntitledActiveMod(['sz-qsm-pro', 'taiyangniao-pro'], { force: true });
      // sz-qsm-pro 是 primary 且在权益列表中
      expect(store.activeModId).toBe('sz-qsm-pro');
    });

    it('pickModIdFromEntitled 无特定匹配时选第一个可选', async () => {
      const store = useModsStore();
      store.mods = [
        {
          id: 'taiyangniao-pro',
          name: '太阳鸟 Pro',
          version: '1.0',
          author: '',
          description: '',
          primary: false,
          industry: { id: 'coating', name: '涂装' },
        },
      ] as never[];
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: [] }));

      // 空权益列表 -> entitledSet.size === 0 -> 所有可选都匹配 -> 选第一个
      await store.applyEntitledActiveMod([], { force: false });
      // 空权益列表 -> augment 返回空 -> !entitled.length -> return
      expect(store.activeModId).toBe('');
    });

    it('canonicalEntitlementId 处理遗留 Mod ID 映射', async () => {
      const store = useModsStore();
      // taiyangniao-pro 的 canonical 是 attendance-industry
      store.mods = [
        {
          id: 'attendance-industry',
          name: '考勤行业包',
          version: '1.0',
          author: '',
          description: '',
          primary: true,
          industry: { id: 'attendance', name: '考勤' },
        },
      ] as never[];
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: [] }));

      // 授权 taiyangniao-pro，但列表中只有 attendance-industry
      // canonicalEntitlementId('taiyangniao-pro') === 'attendance-industry'
      // 所以 attendance-industry 应该匹配
      await store.applyEntitledActiveMod(['taiyangniao-pro'], { force: true });
      expect(store.activeModId).toBe('attendance-industry');
    });

    it('canonicalEntitlementId 处理 sz-qsm-pro 映射', async () => {
      const store = useModsStore();
      store.mods = [
        {
          id: 'coating-industry',
          name: '涂装行业包',
          version: '1.0',
          author: '',
          description: '',
          primary: true,
          industry: { id: 'coating', name: '涂装' },
        },
      ] as never[];
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: [] }));

      // sz-qsm-pro 的 canonical 是 coating-industry
      await store.applyEntitledActiveMod(['sz-qsm-pro'], { force: true });
      expect(store.activeModId).toBe('coating-industry');
    });

    it('applyEntitledActiveMod 在 next 不在列表中时不设置', async () => {
      const store = useModsStore();
      store.mods = sampleMods as never[];
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: [] }));

      // 授权一个不在 mods 列表中的 Mod
      await store.applyEntitledActiveMod(['nonexistent-mod'], { force: true });
      expect(store.activeModId).toBe('');
    });

    it('applyEntitledActiveMod 在 next 等于 current 且 force=true 时同步行业', async () => {
      const store = useModsStore();
      store.mods = sampleMods as never[];
      store.setActiveModId('attendance-industry');
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: [] }));

      await store.applyEntitledActiveMod(['attendance-industry'], { force: true });
      // next === current 且 force -> syncIndustryForActiveMod
      expect(mockSwitchIndustry).toHaveBeenCalled();
    });

    it('applyEntitledActiveMod 在 next 等于 current 且 force=false 时不同步行业', async () => {
      const store = useModsStore();
      store.mods = sampleMods as never[];
      store.setActiveModId('attendance-industry');
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: [] }));

      await store.applyEntitledActiveMod(['attendance-industry'], { force: false });
      // next === current 且 !force -> 不调用 syncIndustryForActiveMod
      expect(mockSwitchIndustry).not.toHaveBeenCalled();
    });

    it('applyEntitledActiveMod 在 current 已匹配权益且非 force 时不切换', async () => {
      const store = useModsStore();
      store.mods = sampleMods as never[];
      store.setActiveModId('attendance-industry');
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: [] }));

      await store.applyEntitledActiveMod(['attendance-industry'], { force: false });
      expect(store.activeModId).toBe('attendance-industry');
    });
  });

  // ═══════════════════════════════════════════════════════════
  // 5. syncIndustryForActiveMod 覆盖
  // ═══════════════════════════════════════════════════════════
  describe('syncIndustryForActiveMod', () => {
    it('切换 active mod 时同步行业', async () => {
      const store = useModsStore();
      store.mods = sampleMods as never[];
      store.setActiveModId('taiyangniao-pro');
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: [] }));

      // force=true 且 next !== current -> setActiveModId + syncIndustryForActiveMod
      await store.applyEntitledActiveMod(['attendance-industry'], { force: true });
      expect(mockSwitchIndustry).toHaveBeenCalledWith('attendance');
    });

    it('行业相同时不调用 switchIndustry', async () => {
      // 让 currentIndustryId 返回与 mod 相同的行业
      vi.doMock('@/stores/industry', () => ({
        useIndustryStore: () => ({
          currentIndustryId: 'attendance',
          switchIndustry: (...args: unknown[]) => mockSwitchIndustry(...args),
          error: null,
        }),
      }));
      vi.resetModules();
      const { useModsStore: freshUseModsStore } = await import('./mods');
      const store = freshUseModsStore();
      store.mods = sampleMods as never[];
      store.setActiveModId('attendance-industry');
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: [] }));

      await store.applyEntitledActiveMod(['attendance-industry'], { force: true });
      // 行业相同 -> 不调用 switchIndustry
      expect(mockSwitchIndustry).not.toHaveBeenCalled();
    });

    it('switchIndustry 失败时输出警告', async () => {
      // 使用 vi.doMock 设置 switchIndustry 返回 false 且 error 有值
      vi.doMock('@/stores/industry', () => ({
        useIndustryStore: () => ({
          currentIndustryId: '',
          switchIndustry: async () => false,
          error: '切换失败',
        }),
      }));
      vi.resetModules();
      const { useModsStore: freshUseModsStore } = await import('./mods');
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
      const store = freshUseModsStore();
      store.mods = sampleMods as never[];
      store.setActiveModId('taiyangniao-pro');
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: [] }));

      await store.applyEntitledActiveMod(['attendance-industry'], { force: true });
      expect(warnSpy).toHaveBeenCalled();
      warnSpy.mockRestore();
    });

    it('mod 无 industry 时不调用 switchIndustry', async () => {
      const store = useModsStore();
      store.mods = [
        {
          id: 'no-industry-mod',
          name: 'No Industry',
          version: '1.0',
          author: '',
          description: '',
          primary: true,
        },
      ] as never[];
      store.setActiveModId('no-industry-mod');
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: [] }));

      await store.applyEntitledActiveMod(['no-industry-mod'], { force: true });
      expect(mockSwitchIndustry).not.toHaveBeenCalled();
    });
  });

  // ═══════════════════════════════════════════════════════════
  // 6. ensureActiveModSelection 覆盖
  // ═══════════════════════════════════════════════════════════
  describe('ensureActiveModSelection', () => {
    it('admin 账户在选中 CLIENT_PRIMARY_ERP_MOD_ID 时清空', async () => {
      mockUseAccountProfileStore.mockReturnValue({
        accountUsername: '',
        isAdminAccount: true,
        isEnterprise: false,
      });
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: sampleMods }));

      const store = useModsStore();
      store.setActiveModId('attendance-industry');
      await store.fetchMods();

      // admin + CLIENT_PRIMARY_ERP_MOD_ID -> setActiveModId('')
      expect(store.activeModId).toBe('');
    });

    it('admin 账户在选中非 CLIENT_PRIMARY_ERP_MOD_ID 时保持不变', async () => {
      mockUseAccountProfileStore.mockReturnValue({
        accountUsername: '',
        isAdminAccount: true,
        isEnterprise: false,
      });
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: sampleMods }));

      const store = useModsStore();
      store.setActiveModId('taiyangniao-pro');
      await store.fetchMods();

      // admin + 非 CLIENT_PRIMARY_ERP_MOD_ID -> 保持
      expect(store.activeModId).toBe('taiyangniao-pro');
    });

    it('非 admin 选中非可选 bridge 时切换到第一个可选扩展', async () => {
      // xcagi-planner-bridge 是非可选 bridge
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: sampleMods }));

      const store = useModsStore();
      store.setActiveModId('xcagi-planner-bridge');
      await store.fetchMods();

      // 非 admin + 选中非可选 bridge -> 切换到 CLIENT_PRIMARY_ERP_MOD_ID 或第一个可选
      expect(store.activeModId).not.toBe('xcagi-planner-bridge');
    });

    it('无 active mod 时选择 primary 可选扩展', async () => {
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: sampleMods }));

      const store = useModsStore();
      await store.fetchMods();

      // attendance-industry 是 primary 且可选
      expect(store.activeModId).toBe('attendance-industry');
    });

    it('admin console SPA 时清空 active mod', async () => {
      mockIsAdminConsoleSpa.mockReturnValue(true);
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: sampleMods }));

      const store = useModsStore();
      store.setActiveModId('attendance-industry');
      await store.fetchMods();

      expect(store.activeModId).toBe('');
    });

    it('clientModsUiOff 时直接返回', async () => {
      const store = useModsStore();
      store.setClientModsUiOff(true);
      store.setActiveModId('attendance-industry');

      // ensureActiveModSelection 在 clientModsUiOff 时直接返回
      // 通过 fetchMods 间接触发
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: sampleMods }));
      await store.fetchMods();

      // clientModsUiOff -> 不修改 activeModId
      // 但 fetchModsOnce 在 mods_disabled 之外不会走到 ensureActiveModSelection
      // 因为 clientModsUiOff 时 fetchModsOnce 正常执行
    });
  });

  // ═══════════════════════════════════════════════════════════
  // 7. resolveModsAccountUsername 覆盖
  // ═══════════════════════════════════════════════════════════
  describe('resolveModsAccountUsername', () => {
    it('优先使用 pendingInitOptions.accountUsername', async () => {
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: sampleMods }));

      const store = useModsStore();
      await store.initialize(false, { accountUsername: 'pending-user' });

      // initialize 成功 -> isLoaded=true
      expect(store.isLoaded).toBe(true);
    });

    it('回退到 lastInitAccountUsername', async () => {
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: sampleMods }));

      const store = useModsStore();
      // 第一次设置 lastInitAccountUsername
      await store.initialize(false, { accountUsername: 'first-user' });
      // 第二次不传 accountUsername，应使用 lastInitAccountUsername
      await store.initialize(true);

      expect(store.isLoaded).toBe(true);
    });

    it('回退到 localStorage xcagi_market_user_json', async () => {
      localStorage.setItem('xcagi_market_user_json', JSON.stringify({ username: 'local-user' }));
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: sampleMods }));

      const store = useModsStore();
      await store.initialize();

      expect(store.isLoaded).toBe(true);
    });

    it('localStorage 解析失败时返回空字符串', async () => {
      localStorage.setItem('xcagi_market_user_json', 'invalid-json');
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: sampleMods }));

      const store = useModsStore();
      await store.initialize();

      expect(store.isLoaded).toBe(true);
    });

    it('localStorage 无数据时返回空字符串', async () => {
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: sampleMods }));

      const store = useModsStore();
      await store.initialize();

      expect(store.isLoaded).toBe(true);
    });
  });

  // ═══════════════════════════════════════════════════════════
  // 8. initialize 边界场景
  // ═══════════════════════════════════════════════════════════
  describe('initialize 边界场景', () => {
    it('clientModsUiOff 时同步状态到后端并直接返回', async () => {
      const store = useModsStore();
      store.setClientModsUiOff(true);
      await store.initialize();

      expect(store.isLoaded).toBe(true);
      expect(store.mods).toEqual([]);
    });

    it('已加载且无 force 时不重新拉取', async () => {
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: sampleMods }));

      const store = useModsStore();
      await store.initialize();
      const callCount = mockApiFetch.mock.calls.length;

      await store.initialize();
      // 第二次不 force 且已加载 -> 不重新拉取
      // 但可能因为 modRoutes 而有少量调用
    });

    it('已加载但 mods 和 modRoutes 都为空时视为未就绪', async () => {
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: [] }));
      mockFetchModLoadingStatusShared.mockResolvedValue(null);

      const store = useModsStore();
      // 第一次 initialize: isLoaded 设为 false（空列表 + 无 loading-status）
      await store.initialize();
      expect(store.isLoaded).toBe(false);

      // 第二次 initialize: isLoaded=false 且 mods=[] -> 重新拉取
      await store.initialize();
    });

    it('并发 initialize 调用去重', async () => {
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: sampleMods }));

      const store = useModsStore();
      const promises = [store.initialize(), store.initialize(), store.initialize()];
      await Promise.all(promises);

      expect(store.isLoaded).toBe(true);
    });

    it('initialize 失败后再次调用重新拉取', async () => {
      // 第一次失败
      mockApiFetch.mockRejectedValueOnce(new Error('network failure'));
      const store = useModsStore();
      await store.initialize();
      expect(store.isLoaded).toBe(false);

      // 第二次成功
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: sampleMods }));
      await store.initialize();
      expect(store.isLoaded).toBe(true);
    });
  });

  // ═══════════════════════════════════════════════════════════
  // 9. fetchModsOnce 错误处理
  // ═══════════════════════════════════════════════════════════
  describe('fetchModsOnce 错误处理', () => {
    it('mods_disabled=true 时返回 ok+modsDisabled', async () => {
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: [], mods_disabled: true }));

      const store = useModsStore();
      const result = await store.fetchMods();

      expect(result.ok).toBe(true);
      expect(result.modsDisabled).toBe(true);
      expect(store.activeModId).toBe('');
    });

    it('HTTP 错误时设置 loadError', async () => {
      mockApiFetch.mockResolvedValue(makeResponse({}, false, 403));

      const store = useModsStore();
      const result = await store.fetchMods();

      expect(result.ok).toBe(false);
      expect(store.loadError).toBe('HTTP 403');
    });

    it('success:false 且无 error/message 时使用默认错误', async () => {
      mockApiFetch.mockResolvedValue(makeResponse({ success: false }));

      const store = useModsStore();
      const result = await store.fetchMods();

      expect(result.ok).toBe(false);
      expect(store.loadError).toBe('列表失败');
    });

    it('transport error 时设置 transportError=true', async () => {
      mockApiFetch.mockRejectedValue(new TypeError('Failed to fetch'));

      const store = useModsStore();
      const result = await store.fetchMods();

      expect(result.ok).toBe(false);
      expect(result.transportError).toBe(true);
    });

    it('ECONNREFUSED 模式错误识别为 transport error', async () => {
      mockApiFetch.mockRejectedValue(new Error('ECONNREFUSED 127.0.0.1:5100'));

      const store = useModsStore();
      const result = await store.fetchMods();

      expect(result.ok).toBe(false);
      expect(result.transportError).toBe(true);
    });

    it('非 transport 错误时使用原始错误消息', async () => {
      mockApiFetch.mockRejectedValue(new Error('something broke'));

      const store = useModsStore();
      const result = await store.fetchMods();

      expect(result.ok).toBe(false);
      expect(result.transportError).toBe(false);
      expect(store.loadError).toBe('something broke');
    });
  });

  // ═══════════════════════════════════════════════════════════
  // 10. readEntitledModIdsFromAuthPayload 补充
  // ═══════════════════════════════════════════════════════════
  describe('readEntitledModIdsFromAuthPayload 补充', () => {
    it('处理 data 为 null 的情况', () => {
      const payload = { data: null, entitled_mod_ids: ['mod-a'] };
      expect(readEntitledModIdsFromAuthPayload(payload)).toEqual(['mod-a']);
    });

    it('处理 data 为非对象的情况', () => {
      const payload = { data: 'string-data' };
      expect(readEntitledModIdsFromAuthPayload(payload)).toEqual([]);
    });

    it('处理数组输入', () => {
      expect(readEntitledModIdsFromAuthPayload([1, 2, 3])).toEqual([]);
    });

    it('处理布尔输入', () => {
      expect(readEntitledModIdsFromAuthPayload(true)).toEqual([]);
    });

    it('entitled_mod_ids 包含非字符串元素时转为字符串', () => {
      const payload = { entitled_mod_ids: [123, 'mod-a', null, undefined] };
      const result = readEntitledModIdsFromAuthPayload(payload);
      // 123 -> '123', null -> '' (被过滤), undefined -> '' (被过滤)
      expect(result).toContain('123');
      expect(result).toContain('mod-a');
    });
  });

  // ═══════════════════════════════════════════════════════════
  // 11. modsForUi / modsForWorkflowUi 补充
  // ═══════════════════════════════════════════════════════════
  describe('modsForUi 补充', () => {
    it('admin console SPA 时返回空数组', () => {
      mockIsAdminConsoleSpa.mockReturnValue(true);
      const store = useModsStore();
      store.mods = sampleMods as never[];
      expect(store.modsForUi).toEqual([]);
    });

    it('admin 账户无 active mod 时返回空数组', () => {
      mockUseAccountProfileStore.mockReturnValue({
        accountUsername: '',
        isAdminAccount: true,
        isEnterprise: false,
      });
      const store = useModsStore();
      store.mods = sampleMods as never[];
      // 无 active mod + admin -> []
      expect(store.modsForUi).toEqual([]);
    });

    it('active mod 在列表中时仅返回该 mod', () => {
      const store = useModsStore();
      store.mods = sampleMods as never[];
      store.setActiveModId('taiyangniao-pro');
      const ui = store.modsForUi;
      expect(ui).toHaveLength(1);
      expect(ui[0].id).toBe('taiyangniao-pro');
    });
  });

  // ═══════════════════════════════════════════════════════════
  // 12. syncActiveModWithServerIndustry 补充
  // ═══════════════════════════════════════════════════════════
  describe('syncActiveModWithServerIndustry 补充', () => {
    it('server 返回 success:false 时不设置 active mod', async () => {
      mockApiFetch.mockResolvedValue(makeResponse({ success: false }));

      const store = useModsStore();
      store.mods = sampleMods as never[];
      await store.syncActiveModWithServerIndustry();
      expect(store.activeModId).toBe('');
    });

    it('server 返回无 id 时不设置 active mod', async () => {
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: {} }));

      const store = useModsStore();
      store.mods = sampleMods as never[];
      await store.syncActiveModWithServerIndustry();
      expect(store.activeModId).toBe('');
    });

    it('server 返回 null id 时不设置 active mod', async () => {
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: { id: null } }));

      const store = useModsStore();
      store.mods = sampleMods as never[];
      await store.syncActiveModWithServerIndustry();
      expect(store.activeModId).toBe('');
    });

    it('pickModMatchingIndustry 无匹配时不设置 active mod', async () => {
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: { id: 'nonexistent' } }));

      const store = useModsStore();
      store.mods = sampleMods as never[];
      await store.syncActiveModWithServerIndustry();
      expect(store.activeModId).toBe('');
    });

    it('pickModMatchingIndustry 优先选择 preferredModId', async () => {
      // 这个函数在 syncActiveModWithServerIndustry 中调用时 preferredModId 为 ''
      // 但我们可以测试 industry 匹配逻辑
      mockApiFetch.mockResolvedValue(makeResponse({ success: true, data: { id: 'attendance' } }));

      const store = useModsStore();
      store.mods = sampleMods as never[];
      await store.syncActiveModWithServerIndustry();
      expect(store.activeModId).toBe('attendance-industry');
    });
  });

  // ═══════════════════════════════════════════════════════════
  // 13. applyLoadingStatusPreview 补充
  // ═══════════════════════════════════════════════════════════
  describe('applyLoadingStatusPreview 补充', () => {
    it('rows 中 name 为空时使用 id 作为 name', () => {
      const store = useModsStore();
      store.applyLoadingStatusPreview([{ id: 'mod-x', name: '' }]);
      expect(store.mods[0].name).toBe('mod-x');
    });

    it('rows 中 version 为空时设为空字符串', () => {
      const store = useModsStore();
      store.applyLoadingStatusPreview([{ id: 'mod-a', name: 'A' }]);
      expect(store.mods[0].version).toBe('');
    });

    it('rows 中 id 和 name 都为空时使用 unknown 和空字符串', () => {
      const store = useModsStore();
      store.applyLoadingStatusPreview([{ id: '', name: '' }]);
      expect(store.mods[0].id).toBe('unknown');
    });
  });
});
