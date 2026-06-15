import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import { authApi, type AccountKind } from '@/api/auth';
import {
  invalidateEnterpriseSessionCache,
  validateEnterpriseSessionCached,
} from '@/utils/authSessionCache';
import { fetchProductSku, isEnterpriseEdition } from '@/utils/productSku';
import { refreshTenantScopedClientStores } from '@/utils/refreshTenantScopedClientStores';
import { setRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime';
import type { TenantStorageScopeInput } from '@/utils/tenantStorageScope';

function buildScopeInput(
  tenantId: number | null,
  marketUserId: number | null,
  localUserId: number | null,
  accountKind: AccountKind,
  marketUsername: string,
): TenantStorageScopeInput {
  return {
    tenantId,
    marketUserId,
    localUserId,
    marketUsername: marketUsername || undefined,
    accountKind,
  };
}

function syncTenantScopedStoresFromProfile(
  tenantId: number | null,
  marketUserId: number | null,
  localUserId: number | null,
  accountKind: AccountKind,
  marketUsername: string,
) {
  const input = buildScopeInput(
    tenantId,
    marketUserId,
    localUserId,
    accountKind,
    marketUsername,
  );
  setRuntimeTenantStorageScopeInput(input);
  refreshTenantScopedClientStores(input);
}

export const useAccountProfileStore = defineStore('accountProfile', () => {
  const accountKind = ref<AccountKind>('enterprise');
  const companyBrand = ref('');
  const marketIsAdmin = ref(false);
  const marketIsEnterprise = ref(false);
  const tenantId = ref<number | null>(null);
  const tenantName = ref('');
  const marketUserId = ref<number | null>(null);
  const localUserId = ref<number | null>(null);
  const impersonatingMarketUserId = ref<number | null>(null);
  const impersonatingUsername = ref('');
  const loaded = ref(false);

  const isAdminAccount = computed(
    () => accountKind.value === 'admin' && marketIsAdmin.value,
  );

  const isImpersonating = computed(() => impersonatingMarketUserId.value != null);

  const displayBrand = computed(() => {
    const brand = companyBrand.value.trim();
    if (brand) return brand;
    return '';
  });

  function applySessionFields(data: Record<string, unknown>) {
    const kind = String(data.account_kind || 'enterprise').trim();
    if (kind === 'personal' || kind === 'enterprise' || kind === 'admin') {
      accountKind.value = kind;
    }
    companyBrand.value = String(data.company_brand || '').trim();
    marketIsAdmin.value = Boolean(data.market_is_admin);
    marketIsEnterprise.value = Boolean(data.market_is_enterprise);
    const tid = data.tenant_id;
    tenantId.value = tid === null || tid === undefined || tid === '' ? null : Number(tid);
    tenantName.value = String(data.tenant_name || data.company_brand || '').trim();
    const mid = data.market_user_id;
    marketUserId.value =
      mid === null || mid === undefined || mid === '' ? null : Number(mid);
    const lid = data.local_user_id;
    if (lid === null || lid === undefined || lid === '') {
      const nested = data.user;
      if (nested && typeof nested === 'object' && !Array.isArray(nested)) {
        const uid = (nested as Record<string, unknown>).id;
        localUserId.value =
          uid === null || uid === undefined || uid === '' ? null : Number(uid);
      }
    } else {
      localUserId.value = Number(lid);
    }
    const imp = data.impersonating_market_user_id;
    impersonatingMarketUserId.value =
      imp === null || imp === undefined || imp === '' ? null : Number(imp);
    impersonatingUsername.value = String(data.impersonating_username || '').trim();
    loaded.value = true;
    syncTenantScopedStoresFromProfile(
      tenantId.value,
      marketUserId.value,
      localUserId.value,
      accountKind.value,
      impersonatingUsername.value,
    );
  }

  function applyFromMeData(data: Record<string, unknown> | null | undefined) {
    if (!data || typeof data !== 'object') return;
    applySessionFields(data);
  }

  function applyFromLoginPayload(raw: Record<string, unknown>) {
    const payload =
      raw.data && typeof raw.data === 'object' && !Array.isArray(raw.data)
        ? (raw.data as Record<string, unknown>)
        : raw;
    applySessionFields(payload);
  }

  async function refreshFromServer() {
    try {
      let sku = 'generic';
      try {
        sku = await fetchProductSku();
      } catch {
        /* ignore */
      }
      if (isEnterpriseEdition(sku)) {
        const valid = await validateEnterpriseSessionCached();
        if (!valid) {
          clear();
          return;
        }
      }
      const res = await authApi.getCurrentUser();
      if (res?.success && res.data) {
        applyFromMeData(res.data as Record<string, unknown>);
        return;
      }
      invalidateEnterpriseSessionCache();
      clear();
    } catch {
      invalidateEnterpriseSessionCache();
      clear();
    }
  }

  function clear() {
    accountKind.value = 'enterprise';
    companyBrand.value = '';
    marketIsAdmin.value = false;
    marketIsEnterprise.value = false;
    tenantId.value = null;
    tenantName.value = '';
    marketUserId.value = null;
    localUserId.value = null;
    impersonatingMarketUserId.value = null;
    impersonatingUsername.value = '';
    loaded.value = false;
    setRuntimeTenantStorageScopeInput(null);
    refreshTenantScopedClientStores({ tenantId: null, accountKind: 'enterprise' });
  }

  return {
    accountKind,
    companyBrand,
    marketIsAdmin,
    marketIsEnterprise,
    tenantId,
    tenantName,
    marketUserId,
    localUserId,
    impersonatingMarketUserId,
    impersonatingUsername,
    loaded,
    isAdminAccount,
    isImpersonating,
    displayBrand,
    applyFromMeData,
    applyFromLoginPayload,
    refreshFromServer,
    clear,
  };
});
