import { onMounted, onUnmounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { fetchImUnreadTotal } from '@/api/im';
import {
  XCMAX_SYNC_IM_MESSAGE_EVENT,
  XCMAX_SYNC_IM_READ_EVENT,
} from '@/composables/useXcmaxSync';
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl';

const imUnreadTotal = ref(0);
let pollTimer: ReturnType<typeof setInterval> | null = null;

function isPublicRoute(name: unknown): boolean {
  const n = String(name || '');
  return (
    n === 'login' ||
    n.startsWith('login-') ||
    n === 'lan-gate' ||
    n === 'product-onboarding'
  );
}

export function useImUnreadBadge() {
  const route = useRoute();

  async function refreshImUnreadTotal(): Promise<void> {
    // 公共页（登录/授权等）不轮询未读，避免对未鉴权接口发请求
    if (isPublicRoute(route.name) || isAdminConsoleSpa()) {
      imUnreadTotal.value = 0;
      return;
    }
    // fetchImUnreadTotal 内部已吞掉所有异常并返回 0
    const total = await fetchImUnreadTotal();
    imUnreadTotal.value = total;
    try {
      if (window.xcagiDesktop?.setBadge) {
        await window.xcagiDesktop.setBadge(total);
      }
    } catch {
      /* ignore */
    }
  }

  function onSyncImActivity(): void {
    void refreshImUnreadTotal();
  }

  onMounted(() => {
    void refreshImUnreadTotal();
    pollTimer = setInterval(() => void refreshImUnreadTotal(), 30_000);
    window.addEventListener(XCMAX_SYNC_IM_MESSAGE_EVENT, onSyncImActivity);
    window.addEventListener(XCMAX_SYNC_IM_READ_EVENT, onSyncImActivity);
  });
  onUnmounted(() => {
    if (pollTimer) clearInterval(pollTimer);
    window.removeEventListener(XCMAX_SYNC_IM_MESSAGE_EVENT, onSyncImActivity);
    window.removeEventListener(XCMAX_SYNC_IM_READ_EVENT, onSyncImActivity);
  });

  return { imUnreadTotal, refreshImUnreadTotal };
}
