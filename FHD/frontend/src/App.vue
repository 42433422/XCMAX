<script setup>
import MainLayout from './components/MainLayout.vue'
import LegacyFloatPanels from '@/components/shell/LegacyFloatPanels.vue'
import AppGlobalProviders from '@/components/shell/AppGlobalProviders.vue'
import VirtualCursorOverlay from '@/components/aiopen/VirtualCursorOverlay.vue'
import RouteFallbackPanel from '@/components/shell/RouteFallbackPanel.vue'
import RouteErrorBoundary from '@/components/shell/RouteErrorBoundary.vue'
import { clearRouteChunkError, isUnmatchedRoute, routeChunkErrorPath } from '@/utils/routeLoadState'
import { isDesktopShell } from '@/utils/desktopShell'
import { useAppBoot } from '@/composables/useAppBoot'
import { usePrivateDeliverySync } from '@/composables/usePrivateDeliverySync'

const { hideChrome, appReady, isAdminConsoleSpa } = useAppBoot()
usePrivateDeliverySync()
</script>

<template>
  <div class="app-shell" :class="{ 'is-ready': appReady || hideChrome, 'app-shell--bare': hideChrome }">
    <LegacyFloatPanels v-if="!hideChrome" />
    <AppGlobalProviders :show-lan-gate="!isAdminConsoleSpa()" />
    <VirtualCursorOverlay />

    <router-view v-if="hideChrome" />
    <MainLayout v-else>
      <router-view v-slot="{ Component, route }">
        <transition v-if="!isAdminConsoleSpa() && !isDesktopShell()" name="route-fade" mode="out-in">
          <keep-alive :max="12">
            <component :is="Component" :key="String(route.name || route.path)" class="route-view-shell" />
          </keep-alive>
        </transition>
        <!-- 管理端与桌面壳不用 out-in：后台窗口的 requestAnimationFrame 可能暂停并卡住旧页面。 -->
        <RouteFallbackPanel v-else-if="routeChunkErrorPath" key="route-chunk-error" mode="chunk-error" :path="routeChunkErrorPath" class="route-view-shell" @dismiss="clearRouteChunkError" />
        <RouteFallbackPanel v-else-if="!Component && isUnmatchedRoute(route)" :key="`not-found:${route.fullPath}`" mode="not-found" :path="route.fullPath" class="route-view-shell" />
        <RouteErrorBoundary v-else :path="route.fullPath">
          <component :is="Component" :key="route.fullPath" class="route-view-shell" />
        </RouteErrorBoundary>
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

.route-view-shell {
  flex: 1 1 auto;
  width: 100%;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-sizing: border-box;
}

.route-view-shell > * {
  min-height: 0;
}

.route-fade-enter-active,
.route-fade-leave-active {
  transition: opacity 100ms ease;
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
