import { createApp } from 'vue';
import { createPinia } from 'pinia';
import type { Router } from 'vue-router';
import ElementPlus from 'element-plus';
import 'element-plus/dist/index.css';
import * as ElementPlusIconsVue from '@element-plus/icons-vue';
import './fhd/installFetchDbReadToken';
import App from './App.vue';
import router from './router';
import { registerModRoutes } from './router/registerModRoutes';
import { fetchModRoutesPayloadShared } from './utils/modRoutesSharedFetch';
import { CLIENT_MODS_UI_OFF_KEY } from '@/stores/mods';
import { applySidebarThemeFromStorage } from './utils/sidebarTheme';
import { installClientConsoleBridge } from './utils/clientDebugLog';

import './styles/css/base.css';
import './styles/css/components/sidebar.css';
import './styles/css/components/chat.css';
import './styles/css/components/tables.css';
import './styles/css/components/modals.css';
import './styles/css/components/ui-components.css';
import './styles/css/animations/transitions.css';
import './styles/css/animations/ui-effects.css';
import './styles/css/animations/pro-mode.css';
import './styles/css/animations/gpu-optimizations.css';
import './styles/css/office-theme.css';
import 'font-awesome/css/font-awesome.min.css';

window.__VUE_APP_ACTIVE__ = true;
window.__VUE_CHAT_OWNS_INPUT__ = true;

function readVanillaNoModUi(): boolean {
  try {
    return localStorage.getItem(CLIENT_MODS_UI_OFF_KEY) === '1';
  } catch {
    return false;
  }
}

/**
 * 与 mount 并行预取 Mod 路由，避免在 bootstrap 里 await 网络导致整页长时间不挂载（用户感觉「卡死」）。
 * 深链直达 Mod 页时若此请求晚于首跳，仍可由 modsStore.initialize 内 registerModRoutes 补齐。
 */
async function prefetchModRoutesAfterMount(appRouter: Router): Promise<void> {
  if (readVanillaNoModUi()) return;

  try {
    const entries = await fetchModRoutesPayloadShared();
    if (entries?.length) {
      await registerModRoutes(appRouter, entries);
    }
  } catch (e) {
    console.warn('[mods] Prefetch mod routes failed (offline or API error):', e);
  }
}

function bootstrap() {
  applySidebarThemeFromStorage();
  installClientConsoleBridge();

  const app = createApp(App);
  const pinia = createPinia();

  app.config.errorHandler = (err, _instance, info) => {
    console.error('[Vue]', info || 'unknown hook', err);
  };
  window.addEventListener('unhandledrejection', (event) => {
    console.error('[unhandledrejection]', event.reason);
  });

  app.use(pinia);
  app.use(router);
  app.use(ElementPlus);

  for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
    app.component(key, component);
  }

  app.mount('#app');

  void prefetchModRoutesAfterMount(router);
}

bootstrap();
