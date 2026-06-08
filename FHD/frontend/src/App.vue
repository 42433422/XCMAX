<script setup>
import MainLayout from './components/MainLayout.vue'
import StartupSplash from '@/components/shell/StartupSplash.vue'
import LegacyFloatPanels from '@/components/shell/LegacyFloatPanels.vue'
import AppGlobalProviders from '@/components/shell/AppGlobalProviders.vue'
import { useAppBoot } from '@/composables/useAppBoot'

const {
  hideChrome,
  startupVisible,
  appReady,
  startupProgressPct,
  startupModNames,
  primaryModName,
  modsLoading,
  modsLoadError,
  isProMode,
  handleToggleProMode,
  skipStartupSplash,
  isAdminConsoleSpa,
} = useAppBoot()
</script>

<template>
  <StartupSplash
    :visible="startupVisible"
    :hide-chrome="hideChrome"
    :primary-mod-name="primaryModName"
    :startup-mod-names="startupModNames"
    :mods-loading="modsLoading"
    :mods-load-error="modsLoadError"
    :startup-progress-pct="startupProgressPct"
    @skip="skipStartupSplash"
  />

  <div class="app-shell" :class="{ 'is-ready': appReady || hideChrome, 'app-shell--bare': hideChrome }">
    <LegacyFloatPanels v-if="!hideChrome" />
    <AppGlobalProviders :show-lan-gate="!isAdminConsoleSpa()" />

    <router-view v-if="hideChrome" />
    <MainLayout
      v-else
      :is-pro-mode="isProMode"
      @toggle-pro-mode="handleToggleProMode"
    >
      <router-view v-slot="{ Component, route }">
        <keep-alive v-if="!isAdminConsoleSpa()" :max="12">
          <component :is="Component" :key="route.fullPath" />
        </keep-alive>
        <component v-else :is="Component" :key="route.fullPath" />
      </router-view>
    </MainLayout>
  </div>
</template>

<style>
.app-shell {
  opacity: 1;
  transition: opacity 320ms ease;
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
</style>
