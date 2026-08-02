import { ref, computed, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRouter } from 'vue-router';
import { storeToRefs } from 'pinia';
import api, { ApiError } from '@/api';
import { systemApi, type Industry as ApiIndustry } from '@/api/system';
import { intentPackagesApi, type IntentPackage as ApiIntentPackage } from '@/api/intentPackages';
import { useIndustryStore } from '@/stores/industry';
import { useModsStore } from '@/stores/mods';
import { useAccountProfileStore } from '@/stores/accountProfile';
import { appAlert, appConfirm } from '@/utils/appDialog';
import { DEFAULT_INDUSTRY_ID } from '@/constants/industryDefaults';
import { getIndustryPreset } from '@/constants/industryPresets';
import { isProtectedClientModId } from '@/constants/protectedMods';
import {
  ACCOUNT_CUSTOM_MOD_IDS,
  expectedHostBridgeModIds,
  isHostBridgeModId,
  isSelectableExtensionModId,
  isWorkflowEmployeeModId,
} from '@/constants/genericModPack';
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl';
import { asRecord, asString } from '@/utils/typeGuards';
import type { ApiMessageResult } from './utils';

type ManifestIndustry = {
  id?: string | number
  name?: string
  units?: { primary?: string }
  intent_keywords?: IntentKeywordMap
  [key: string]: unknown
}

type IntentKeywordMap = {
  create_order?: string | string[]
  quantity_unit?: string | string[]
  print_label?: string | string[]
  [key: string]: unknown
}

type IntentPackageKey = 'base' | 'industry' | 'product' | 'quantity' | 'customer'

type IntentPackageState = {
  name: string
  iconClass: string
  description: string
  enabled: boolean
  keywords: string[]
}

export function useSettingsMods() {
  const { t } = useI18n();
  const router = useRouter();
  const isAdminConsole = isAdminConsoleSpa();
  const industryStore = useIndustryStore();
  const accountProfileStore = useAccountProfileStore();
  const modsStore = useModsStore();
  const { clientModsUiOff, loadError, isLoaded, mods, modRoutes, activeModId } = storeToRefs(modsStore);

  const MODEL_PAYMENT_BRIDGE_ID = 'xcagi-model-payment-bridge';

  const modelPaymentBridgeInstalled = computed(() =>
    mods.value.some((m) => String(m.id || '').trim() === MODEL_PAYMENT_BRIDGE_ID),
  );

  function openSettingsExtensions() {
    const el = document.querySelector('[data-tutorial-id="settings-extensions"]');
    if (el instanceof HTMLDetailsElement) {
      el.open = true;
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }
    void router.push({ name: 'mod-store' });
  }

  const uninstallingModId = ref('');
  const hostPackExpanded = ref(false);

  const hostBridgeMods = computed(() => {
    const expected = new Set(expectedHostBridgeModIds());
    return mods.value
      .filter((m) => isHostBridgeModId(String(m.id || '')))
      .sort((a, b) => {
        const aid = String(a.id || '');
        const bid = String(b.id || '');
        const tier = (id: string) => (expected.has(id) ? 0 : 1);
        const t = tier(aid) - tier(bid);
        if (t !== 0) return t;
        return String(a.name || aid).localeCompare(String(b.name || bid), 'zh-CN');
      });
  });

  const hostBridgeInstalledCount = computed(() => {
    const ids = new Set(mods.value.map((m) => String(m.id || '').trim()));
    return expectedHostBridgeModIds().filter((id) => ids.has(id)).length;
  });

  const hostBridgeExpectedCount = computed(() => expectedHostBridgeModIds().length);

  const selectableExtensionMods = computed(() =>
    mods.value.filter((m) => isSelectableExtensionModId(String(m.id || ''))),
  );

  const workflowEmployeeMods = computed(() =>
    mods.value.filter((m) => isWorkflowEmployeeModId(String(m.id || ''))),
  );

  const showModelPaymentBridge = computed(() => {
    if (isAdminConsole) return true;
    return modelPaymentBridgeInstalled.value;
  });

  function goHostPackOnboarding() {
    router.push({ path: '/onboarding', query: { step: 'host-pack' } });
  }

  function goModStore() {
    router.push({ name: 'mod-store' });
  }

  const activeModMeta = computed(() => {
    const mid = String(activeModId.value || '').trim();
    if (!mid) return null;
    return mods.value.find((m) => String(m.id || '').trim() === mid) || null;
  });

  /** 取 active mod 的 manifest.industry，不存在返回 null。供主单位/意图关键词读取 */
  const activeModIndustry = computed<ManifestIndustry | null>(() => {
    const meta = activeModMeta.value;
    const ind = meta && typeof meta === 'object' ? (meta as { industry?: unknown }).industry : null;
    return ind && typeof ind === 'object' ? (ind as ManifestIndustry) : null;
  });

  const modRoutesRetrying = ref(false);

  const modRoutesStatusText = computed(() => {
    if (clientModsUiOff.value) return '';
    if (loadError.value) return loadError.value;
    if (
      isLoaded.value &&
      mods.value.length > 0 &&
      modRoutes.value.length === 0
    ) {
      return t('settings.modRoutesNotLoaded');
    }
    return '';
  });

  const showModRoutesRetry = computed(() => Boolean(modRoutesStatusText.value));

  const modSettingsFoldMeta = computed(() => {
    const host = hostBridgeMods.value.length
      ? t('settings.modFoldCore', {
          installed: hostBridgeInstalledCount.value,
          expected: hostBridgeExpectedCount.value,
        })
      : '';
    const ext = t('settings.modFoldIndustry', { count: selectableExtensionMods.value.length });
    const wf = workflowEmployeeMods.value.length
      ? t('settings.modFoldWorkflow', { count: workflowEmployeeMods.value.length })
      : '';
    return [host, ext, wf].filter(Boolean).join(' · ') || t('settings.manageExtensions');
  });

  async function retryModRoutesLoad() {
    modRoutesRetrying.value = true;
    try {
      await modsStore.refresh();
      if (loadError.value) {
        await appAlert(loadError.value);
      } else if (mods.value.length > 0 && modRoutes.value.length === 0) {
        await appAlert(t('settings.stillNoRoutes'));
      } else {
        await appAlert(t('settings.modsReloaded'));
      }
    } finally {
      modRoutesRetrying.value = false;
    }
  }

  async function onActiveModChange(modId: string) {
    const next = String(modId || '').trim();
    if (!next || activeModId.value === next) return;

    // 行业现在由后端 SSOT 决定（industryStore.switchIndustry 已删除）：
    // 切换 active mod 后，前端只更新 activeModId，行业由后端在 mod 加载时
    // 自动同步；UI 派生（useIndustryUiText / activeModIndustry）会跟随 mod 选择。
    modsStore.setActiveModId(next);

    // 切换 Mod 会改变侧栏菜单、工作流员工与 X-XCAGI-Active-Mod-Id 请求头；
    // 刷新页面让后端按新 active mod 重新拉取行业 SSOT 与路由表。
    window.location.reload();
  }

  async function onUninstallMod(modId: string) {
    const mid = String(modId || '').trim();
    if (!mid) return;
    if (isProtectedClientModId(mid)) {
      await appAlert(t('settings.protectedMod'));
      return;
    }
    const meta = mods.value.find((m) => String(m.id || '').trim() === mid) || null;
    const label = (meta && String(meta.name || '').trim()) || mid;
    let question = t('settings.uninstallConfirm', { label, id: mid });
    if (meta && meta.primary) {
      question += t('settings.uninstallPrimaryHint');
    }
    if (activeModId.value === mid) {
      question += t('settings.uninstallActiveHint');
    }
    if (!(await appConfirm(question, { danger: true }))) return;
    uninstallingModId.value = mid;
    try {
      const data = await api.delete<ApiMessageResult>(`/api/mods/${encodeURIComponent(mid)}`);
      if (!data || !data.success) {
        await appAlert(t('settings.uninstallFailed', { detail: (data && (data.message || data.error)) || t('settings.unknownError') }));
        return;
      }
      await appAlert(typeof data.message === 'string' ? data.message : t('settings.uninstalled', { id: mid }));
      window.location.reload();
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : String(err);
      await appAlert(t('settings.uninstallRequestFailed', { detail: msg }));
    } finally {
      uninstallingModId.value = '';
    }
  }

  const accountCustomModIds = new Set<string>(ACCOUNT_CUSTOM_MOD_IDS);

  const installedAccountCustomMod = computed(() =>
    mods.value.find((m) => accountCustomModIds.has(String(m.id || '').trim())) || null,
  );

  const deliveryBrandName = computed(() => {
    const customName = String(installedAccountCustomMod.value?.name || '').trim();
    if (customName) return customName;
    const brand = String(accountProfileStore.displayBrand || '').trim();
    return brand;
  });

  const industries = ref<ApiIndustry[]>([]);
  const currentIndustry = ref(DEFAULT_INDUSTRY_ID);
  const currentIndustryUnit = ref('天');

  const currentIndustryLabel = computed(() => {
    const fromMod = String(activeModIndustry.value?.name || '').trim();
    if (fromMod) return fromMod;
    const id = String(currentIndustry.value || DEFAULT_INDUSTRY_ID).trim() || DEFAULT_INDUSTRY_ID;
    return String(getIndustryPreset(id).name || id || t('settings.genericIndustry')).trim();
  });

  const systemDisplayName = computed(() => {
    const brand = deliveryBrandName.value;
    if (brand) return t('settings.deliveryWorkbench', { brand });
    return t('settings.genericHost');
  });

  const aboutDisplayLine = computed(() => {
    const brand = deliveryBrandName.value;
    const industry = currentIndustryLabel.value;
    if (brand) {
      const industryPart = industry
        ? t('settings.aboutIndustryLine', { industry })
        : t('settings.aboutCustomLine');
      return t('settings.aboutWithBrand', { brand, industryPart });
    }
    return t('settings.aboutModCapability');
  });

  const intentPackages = ref<Record<IntentPackageKey, IntentPackageState>>({
    base: {
      name: '基础意图',
      iconClass: 'fa-file-text-o',
      description: '考勤与单据通用意图：创建、查询、修改、导出、审批',
      enabled: true,
      keywords: ['考勤', '查询', '导出', '请假', '加班', '修改', '创建', '统计']
    },
    industry: {
      name: '行业特定',
      iconClass: 'fa-industry',
      description: '当前组织的考勤制度用语与业务词汇',
      enabled: true,
      keywords: []
    },
    product: {
      name: '员工识别',
      iconClass: 'fa-cubes',
      description: '工号、姓名、部门等员工信息的识别与解析',
      enabled: true,
      keywords: ['工号', '姓名', '部门', '岗位', '职级']
    },
    quantity: {
      name: '工时解析',
      iconClass: 'fa-sort-numeric-asc',
      description: '出勤天数、工时小时数及中文数字的智能解析',
      enabled: true,
      keywords: ['天', '小时', '半天', '次', '二十三', '一十']
    },
    customer: {
      name: '组织识别',
      iconClass: 'fa-users',
      description: '部门名称、上下级关系与办公地点等信息的识别',
      enabled: true,
      keywords: ['部门', '科室', '班组', '分公司', '联系人']
    }
  });

  const currentIndustryConfig = computed(() => {
    return industryStore.industries.find(i => i.id === currentIndustry.value);
  });

  const INTENT_PACKAGE_ORDER: IntentPackageKey[] = ['base', 'industry', 'product', 'quantity', 'customer'];

  const intentPackageEntries = computed(() => {
    const pkgs = intentPackages.value;
    return INTENT_PACKAGE_ORDER.filter((key) => pkgs[key]).map((key) => ({
      key,
      ...pkgs[key],
      name: t(`settings.intentPackages.${key}.name`),
      description: t(`settings.intentPackages.${key}.description`),
      keywords: Array.isArray(pkgs[key].keywords)
        ? pkgs[key].keywords.filter((kw) => String(kw || '').trim()).slice(0, 12)
        : [],
    }));
  });

  const currentIntentIndustryLabel = computed(() => {
    const cfg = currentIndustryConfig.value;
    if (cfg?.name) return String(cfg.name);
    const preset = getIndustryPreset(String(currentIndustry.value || DEFAULT_INDUSTRY_ID));
    return preset?.name || String(currentIndustry.value || '').trim() || '';
  });

  async function loadIndustries() {
    try {
      const response = await systemApi.getIndustries();
      if (response.success) {
        const payload = response.data as ApiIndustry[] | { industries?: ApiIndustry[]; current?: string | number } | undefined;
        industries.value = Array.isArray(payload) ? payload : payload?.industries || [];
        const cur =
          (!Array.isArray(payload) ? payload?.current : undefined) ??
          industryStore.currentIndustry?.id ??
          DEFAULT_INDUSTRY_ID;
        currentIndustry.value = String(cur).trim() || DEFAULT_INDUSTRY_ID;
      }
    } catch (e) {
      console.error('加载行业列表失败:', e);
    }
  }

  async function loadCurrentIndustryDetail() {
    try {
      const response = await systemApi.getCurrentIndustry();
      if (response.success) {
        // 主单位优先采用 active mod 的 manifest.industry.units.primary —— 让"切 mod"
        // 在后端尚未对齐前也能立刻把主单位切对。
        const fromMod = activeModIndustry.value?.units?.primary;
        const units = asRecord(response.data).units as Record<string, unknown> | undefined
        currentIndustryUnit.value =
          (typeof fromMod === 'string' && fromMod.trim()) ||
          asString(units?.primary) ||
          '天';
        updateIndustryKeywords();
      }
    } catch (e) {
      console.error('加载行业详情失败:', e);
      // server 失败时也用 mod manifest 兜底，避免主单位卡在默认「天」之前的状态
      const fromMod = activeModIndustry.value?.units?.primary;
      if (typeof fromMod === 'string' && fromMod.trim()) {
        currentIndustryUnit.value = fromMod.trim();
      }
      updateIndustryKeywords();
    }
  }

  function updateIndustryKeywords() {
    // 优先读 active mod 的 manifest.intent_keywords，让"行业特定"芯片立即跟随 mod 切换；
    // 没有 mod 或 mod 未声明 intent_keywords 时回到 industryStore.currentConfig。
    const modKw = activeModIndustry.value?.intent_keywords;
    const config = industryStore.currentConfig;
    const kw = (modKw && typeof modKw === 'object' ? modKw : asRecord(config).intent_keywords) as IntentKeywordMap | undefined;
    if (!kw || typeof kw !== 'object') return;
    const keywords: string[] = [];
    if (kw.create_order) {
      keywords.push(...(Array.isArray(kw.create_order) ? kw.create_order : [kw.create_order]));
    }
    if (kw.quantity_unit) {
      keywords.push(...(Array.isArray(kw.quantity_unit) ? kw.quantity_unit : [kw.quantity_unit]));
    }
    if (kw.print_label) {
      keywords.push(...(Array.isArray(kw.print_label) ? kw.print_label : [kw.print_label]));
    }
    intentPackages.value.industry.keywords = [...new Set(keywords.map((kw) => String(kw || '').trim()).filter(Boolean))].slice(0, 12);
  }

  async function loadIntentPackages() {
    try {
      const response = await intentPackagesApi.getPackages();
      const payload = response.data as ApiIntentPackage[] | { packages?: Record<string, Partial<IntentPackageState>> } | undefined;
      const packages = !Array.isArray(payload) ? payload?.packages : undefined;
      if (response.success && packages) {
        for (const key of Object.keys(packages) as IntentPackageKey[]) {
          const target = intentPackages.value[key];
          const source = packages[key];
          if (target && source) {
            if (typeof source.enabled === 'boolean') target.enabled = source.enabled;
            if (Array.isArray(source.keywords)) target.keywords = source.keywords;
          }
        }
      }
    } catch (e) {
      console.error('加载意图包失败:', e);
    }
  }

  watch(
    activeModIndustry,
    () => {
      updateIndustryKeywords();
    },
    { deep: true },
  );

  return {
    clientModsUiOff,
    loadError,
    isLoaded,
    mods,
    modRoutes,
    activeModId,
    modelPaymentBridgeInstalled,
    showModelPaymentBridge,
    uninstallingModId,
    hostPackExpanded,
    hostBridgeMods,
    hostBridgeInstalledCount,
    hostBridgeExpectedCount,
    selectableExtensionMods,
    workflowEmployeeMods,
    activeModMeta,
    activeModIndustry,
    modRoutesRetrying,
    modRoutesStatusText,
    showModRoutesRetry,
    modSettingsFoldMeta,
    installedAccountCustomMod,
    deliveryBrandName,
    industries,
    currentIndustry,
    currentIndustryUnit,
    currentIndustryConfig,
    currentIndustryLabel,
    currentIntentIndustryLabel,
    intentPackages,
    intentPackageEntries,
    systemDisplayName,
    aboutDisplayLine,
    openSettingsExtensions,
    goHostPackOnboarding,
    goModStore,
    retryModRoutesLoad,
    onActiveModChange,
    onUninstallMod,
    loadIndustries,
    loadCurrentIndustryDetail,
    updateIndustryKeywords,
    loadIntentPackages,
  };
}
