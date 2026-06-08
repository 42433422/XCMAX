import { ref, computed } from 'vue';
import { lanGateApi, type LanStatus } from '@/api/lanGate';

const status = ref<LanStatus | null>(null);
const lastChecked = ref<number>(0);
const inflight = ref<Promise<LanStatus> | null>(null);

/** 由路由守卫打开：拦截 hostAdmin 等路由时的全局授权弹窗 */
const modalVisible = ref(false);
const modalRedirect = ref<string | null>(null);

const STATUS_TTL_MS = 15_000;

export function useLanGate() {
  const isReady = computed(() => status.value !== null);
  const enabled = computed(() => status.value?.enabled ?? false);
  const authorized = computed(() => status.value?.authorized ?? false);
  const isAdminHost = computed(() => status.value?.is_admin_host ?? false);
  const isAdminKey = computed(() => status.value?.is_admin ?? false);
  const inWhitelist = computed(() => status.value?.in_whitelist ?? false);

  async function refresh(force = false): Promise<LanStatus> {
    const now = Date.now();
    if (!force && status.value && now - lastChecked.value < STATUS_TTL_MS) {
      return status.value;
    }
    if (inflight.value) {
      return inflight.value;
    }
    const p = lanGateApi
      .status()
      .then((s) => {
        status.value = s;
        lastChecked.value = Date.now();
        return s;
      })
      .finally(() => {
        inflight.value = null;
      });
    inflight.value = p;
    return p;
  }

  async function logout(): Promise<void> {
    try {
      await lanGateApi.logout();
    } catch {
      /* ignore */
    }
    status.value = null;
    lastChecked.value = 0;
  }

  function reset(): void {
    status.value = null;
    lastChecked.value = 0;
    inflight.value = null;
  }

  function openLanGateModal(redirectFullPath: string): void {
    modalRedirect.value = redirectFullPath || '/';
    modalVisible.value = true;
  }

  function dismissLanGateModal(): void {
    modalVisible.value = false;
    modalRedirect.value = null;
  }

  return {
    status,
    isReady,
    enabled,
    authorized,
    isAdminHost,
    isAdminKey,
    inWhitelist,
    refresh,
    logout,
    reset,
    modalVisible,
    modalRedirect,
    openLanGateModal,
    dismissLanGateModal
  };
}
