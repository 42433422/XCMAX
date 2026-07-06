<script setup>
import MainLayout from './components/MainLayout.vue'
import LegacyFloatPanels from '@/components/shell/LegacyFloatPanels.vue'
import AppGlobalProviders from '@/components/shell/AppGlobalProviders.vue'
import VirtualCursorOverlay from '@/components/aiopen/VirtualCursorOverlay.vue'
import { useAppBoot } from '@/composables/useAppBoot'
import { routePendingRef } from '@/composables/useRoutePending'

const {
  hideChrome,
  appReady,
  isProMode,
  handleToggleProMode,
  isAdminConsoleSpa,
} = useAppBoot()

// 指示器安装在 router 模块（须先于初始导航）；这里只读状态
const routePending = routePendingRef()
</script>

<template>
  <div class="app-shell" :class="{ 'is-ready': appReady || hideChrome, 'app-shell--bare': hideChrome }">
    <LegacyFloatPanels v-if="!hideChrome" />
    <AppGlobalProviders :show-lan-gate="!isAdminConsoleSpa()" />
    <VirtualCursorOverlay />
    <div v-if="routePending" class="route-pending-pill" role="status" aria-live="polite">
      <span class="route-pending-spinner" aria-hidden="true"></span>
      <span>页面加载中…</span>
    </div>

    <router-view v-if="hideChrome" />
    <MainLayout
      v-else
      :is-pro-mode="isProMode"
      @toggle-pro-mode="handleToggleProMode"
    >
      <router-view v-slot="{ Component, route }">
        <transition name="route-fade" mode="out-in">
          <div :key="route.fullPath" class="route-view-shell">
            <keep-alive v-if="!isAdminConsoleSpa()" :max="12">
              <component :is="Component" />
            </keep-alive>
            <component v-else :is="Component" />
          </div>
        </transition>
      </router-view>
    </MainLayout>
  </div>
</template>

<style>
.app-shell {
  opacity: 1;
  transition: opacity 320ms ease;
  height: 100vh;
  overflow: hidden;
  background:
    radial-gradient(circle at 50% 0%, rgba(255, 255, 255, 0.88), transparent 42%),
    linear-gradient(135deg, #edf5fb 0%, #e7eef6 48%, #eef3f8 100%);
}

@media (prefers-reduced-motion: reduce) {
  .app-shell {
    transition-duration: 1ms;
  }
}

.app-shell.app-shell--bare {
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
}

.app-shell.app-shell--bare > :last-child {
  flex: 1 1 auto;
  min-height: 0;
  width: 100%;
}

.route-pending-pill {
  position: fixed;
  top: 14px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 4000;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.96);
  border: 1px solid rgba(147, 197, 253, 0.65);
  box-shadow: 0 8px 24px rgba(37, 99, 235, 0.18);
  color: #1e3a8a;
  font-size: 13px;
  font-weight: 600;
  pointer-events: none;
}

.route-pending-spinner {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 2px solid rgba(37, 99, 235, 0.25);
  border-top-color: #2563eb;
  animation: route-pending-spin 0.8s linear infinite;
}

@keyframes route-pending-spin {
  to {
    transform: rotate(360deg);
  }
}

.route-view-shell {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.route-view-shell > * {
  flex: 1 1 auto;
  min-height: 0;
}

.route-fade-enter-active,
.route-fade-leave-active {
  transition: opacity 250ms ease;
}

.route-fade-enter-from,
.route-fade-leave-to {
  opacity: 0;
}

@media (prefers-reduced-motion: reduce) {
  .route-fade-enter-active,
  .route-fade-leave-active {
    transition-duration: 1ms;
  }
}
</style>
