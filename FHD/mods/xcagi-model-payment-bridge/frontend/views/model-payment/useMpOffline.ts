import { computed, ref } from 'vue';
import { swManager } from '@/utils/serviceWorker';
import { formatCacheAge } from './mpMarketCache';

/** 离线状态检测与监听（拆分自 ModelPaymentView.vue，逻辑不变） */

export function useMpOffline(deps: {
  refreshOverview: () => Promise<void>;
  refreshCatalog: () => Promise<void>;
  forceRefreshAll: () => Promise<void>;
}) {
  // ========== 离线状态检测 ==========
  const isOffline = ref(!navigator.onLine);
  const dataSource = ref<'network' | 'cache' | 'offline'>('network');
  const cacheTimestamp = ref<number | null>(null);

  // 监听Service Worker状态变化
  let unsubSW: (() => void) | null = null;

  // 离线状态计算属性
  const cacheAgeText = computed(() => {
    if (!cacheTimestamp.value) return '未知时间';
    const age = Date.now() - cacheTimestamp.value;
    return formatCacheAge(age);
  });

  const offlineStatusText = computed(() => {
    if (isOffline.value) {
      if (dataSource.value === 'offline') return '完全离线，数据来自本地存储';
      return '网络不可用，显示Service Worker缓存数据';
    }
    return '';
  });

  // ========== 离线状态管理函数 ==========

  function updateOnlineStatus() {
    isOffline.value = !navigator.onLine;

    if (isOffline.value) {
      dataSource.value = cacheTimestamp.value ? 'cache' : 'offline';
    } else {
      // 恢复在线后自动刷新
      if (dataSource.value !== 'network') {
        dataSource.value = 'network';
        deps.refreshOverview().catch(() => {});
        deps.refreshCatalog().catch(() => {});
      }
    }
  }

  async function retryConnection() {
    console.log('[ModelPayment] User requested retry...');

    // 尝试简单的网络请求检测连接
    try {
      const response = await fetch('/api/health', {
        method: 'GET',
        cache: 'no-store',
        signal: AbortSignal.timeout(5000)
      });

      if (response.ok) {
        isOffline.value = false;
        dataSource.value = 'network';

        // 刷新数据
        await deps.forceRefreshAll();
        alert('网络已恢复！数据已更新。');
      } else {
        throw new Error(`HTTP ${response.status}`);
      }
    } catch (error) {
      isOffline.value = true;
      alert('仍然无法连接到服务器。请检查您的网络连接。');
    }
  }

  function setupOnlineListeners() {
    window.addEventListener('online', updateOnlineStatus);
    window.addEventListener('offline', updateOnlineStatus);

    // 监听Service Worker状态
    unsubSW = swManager.onChange((status) => {
      isOffline.value = status.offline;

      // 如果SW报告离线但浏览器认为在线，以SW为准（更准确）
      if (status.offline && navigator.onLine) {
        console.warn('[ModelPayment] SW reports offline but browser says online');
        isOffline.value = true;
      }
    });
  }

  function cleanupOnlineListeners() {
    window.removeEventListener('online', updateOnlineStatus);
    window.removeEventListener('offline', updateOnlineStatus);

    if (unsubSW) {
      unsubSW();
      unsubSW = null;
    }
  }

  return {
    isOffline,
    dataSource,
    cacheTimestamp,
    cacheAgeText,
    offlineStatusText,
    updateOnlineStatus,
    retryConnection,
    setupOnlineListeners,
    cleanupOnlineListeners,
  };
}
