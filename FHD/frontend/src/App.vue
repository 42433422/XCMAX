<script setup>
import MainLayout from './components/MainLayout.vue'
import LegacyFloatPanels from '@/components/shell/LegacyFloatPanels.vue'
import AppGlobalProviders from '@/components/shell/AppGlobalProviders.vue'
import VirtualCursorOverlay from '@/components/aiopen/VirtualCursorOverlay.vue'
import { useAppBoot } from '@/composables/useAppBoot'

const {
  hideChrome,
  appReady,
  isProMode,
  handleToggleProMode,
  isAdminConsoleSpa,
} = useAppBoot()
</script>

<template>
  <div class="app-shell" :class="{ 'is-ready': appReady || hideChrome, 'app-shell--bare': hideChrome }">
    <LegacyFloatPanels v-if="!hideChrome" />
    <AppGlobalProviders :show-lan-gate="!isAdminConsoleSpa()" />
    <VirtualCursorOverlay />

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
