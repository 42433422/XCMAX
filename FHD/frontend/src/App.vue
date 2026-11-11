<script setup>
import MainLayout from './components/MainLayout.vue'
import LegacyFloatPanels from '@/components/shell/LegacyFloatPanels.vue'
import AppGlobalProviders from '@/components/shell/AppGlobalProviders.vue'
import VirtualCursorOverlay from '@/components/aiopen/VirtualCursorOverlay.vue'
import RouteFallbackPanel from '@/components/shell/RouteFallbackPanel.vue'
import RouteErrorBoundary from '@/components/shell/RouteErrorBoundary.vue'
import RouteLoadingFeedback from '@/components/shell/RouteLoadingFeedback.vue'
import { clearRouteChunkError, isUnmatchedRoute, routeChunkErrorPath } from '@/utils/routeLoadState'
import { isDesktopShell } from '@/utils/desktopShell'
import { probeEnterpriseSession } from '@/utils/authSessionCache'
import { repairBlankMarketAccessToken } from '@/api/marketAccount'
import { useAppBoot } from '@/composables/useAppBoot'
import { usePrivateDeliverySync } from '@/composables/usePrivateDeliverySync'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { useRoute, useRouter } from 'vue-router'

const viewPending = ref(false)
const { hideChrome, appReady, startupVisible, startupError, startupStage, retryStartup, cancelStartup, isAdminConsoleSpa } = useAppBoot(viewPending)
const startupPanel = ref(null)
watch([startupVisible, startupError], async ([visible]) => {
  if (visible) { await nextTick(); startupPanel.value?.focus() }
}, { immediate: true })
const reloadStartup = () => window.location.reload()
watch(routeChunkErrorPath, (path) => {
  if (path) startupVisible.value = false
}, { immediate: true })
watch(startupVisible, (visible) => {
  if (visible && routeChunkErrorPath.value) startupVisible.value = false
})
usePrivateDeliverySync()
const account = useAccountProfileStore()
// Identity only. Profile refreshes after idle must not drop every cached page.
const cacheScope = computed(() => JSON.stringify([productReadAccountEpoch.value,
  account.tenantId, account.marketUserId, account.localUserId, account.impersonatingMarketUserId]))
const currentRoute = useRoute()
const router = useRouter()
const scrollMemory = new Map()
const removeScrollGuards = []
let scrollActive = true, scrollGeneration = 0, scrollFrame, scrollTimer
function cancelScrollRestore() {
  scrollGeneration++
  if (scrollFrame !== undefined) cancelAnimationFrame(scrollFrame)
  if (scrollTimer !== undefined) clearTimeout(scrollTimer)
  scrollFrame = scrollTimer = undefined
}
watch(cacheScope, () => { cancelScrollRestore(); scrollMemory.clear() })
function scrollSignature(el) {
  return `${el.id || ''}::${el.className || ''}`
}
function rememberRouteScroll(fullPath) {
  const root = document.querySelector('.route-view-shell')
  if (!root) return
  const items = [root, ...root.querySelectorAll('*')]
    .filter((el) => el.scrollHeight > el.clientHeight + 40 && el.clientHeight > 40 && el.scrollTop > 0)
    .map((el) => ({ sig: scrollSignature(el), top: el.scrollTop }))
  if (items.length) scrollMemory.set(fullPath, items)
}
function restoreRouteScroll(fullPath) {
  const items = scrollMemory.get(fullPath)
  const root = document.querySelector('.route-view-shell')
  if (!items?.length || !root) return
  const nodes = [root, ...root.querySelectorAll('*')]
  for (const item of items) {
    const el = nodes.find((node) => scrollSignature(node) === item.sig)
    if (el) el.scrollTop = item.top
  }
}
let sessionProbeTimer = 0
onMounted(() => {
  if (isDesktopShell()) {
    const probe = () => {
      void probeEnterpriseSession()
      void repairBlankMarketAccessToken()
    }
    probe()
    sessionProbeTimer = window.setInterval(probe, 5_000)
  }
  removeScrollGuards.push(
    router.beforeEach((to, from) => {
      if (!scrollActive) return
      cancelScrollRestore()
      rememberRouteScroll(from.fullPath)
    }),
    router.afterEach((to, from, failure) => {
      if (failure || !scrollActive) return
      cancelScrollRestore()
      const generation = scrollGeneration, scope = cacheScope.value
      const current = () => scrollActive && generation === scrollGeneration &&
        currentRoute.fullPath === to.fullPath && cacheScope.value === scope
      const restore = () => { if (current()) restoreRouteScroll(to.fullPath) }
      nextTick(() => {
        if (!current()) return
        restore()
        scrollFrame = requestAnimationFrame(() => { scrollFrame = undefined; restore() })
        scrollTimer = setTimeout(() => { scrollTimer = undefined; restore() }, 60)
      })
    }),
  )
})
onBeforeUnmount(() => {
  if (sessionProbeTimer) window.clearInterval(sessionProbeTimer)
  scrollActive = false
  cancelScrollRestore()
  for (const remove of removeScrollGuards) remove()
  scrollMemory.clear()
})
const routeReadinessHandlers = computed(() => {
  const path = currentRoute.fullPath, scope = cacheScope.value
  const current = () => path === currentRoute.fullPath && scope === cacheScope.value
  return {
    pending: () => { if (current()) viewPending.value = true },
    resolve: () => { if (current()) viewPending.value = false },
  }
})
</script>

<template>
  <section v-if="startupVisible" ref="startupPanel" class="startup-readiness" tabindex="-1"
    role="dialog" aria-modal="true" aria-labelledby="startup-title" aria-describedby="startup-status"
    data-testid="startup-readiness" :data-state="startupError ? 'error' : 'loading'">
    <div class="startup-readiness__panel">
      <h1 id="startup-title">{{ startupError ? '工作台暂未就绪' : '正在进入工作台' }}</h1>
      <p id="startup-status" role="status" aria-live="polite">{{ startupError || startupStage }}</p>
      <div class="startup-readiness__actions">
        <button v-if="startupError" type="button" class="btn btn-primary" @click="retryStartup">重试</button>
        <button v-if="startupError" type="button" class="btn btn-secondary" @click="reloadStartup">重新加载</button>
        <button type="button" class="btn btn-secondary" @click="cancelStartup">{{ startupError ? '返回登录' : '取消' }}</button>
      </div>
    </div>
  </section>
  <div class="app-shell" data-testid="startup-workspace" :inert="startupVisible || undefined"
    :aria-hidden="startupVisible || undefined" :aria-busy="startupVisible || undefined"
    :class="{ 'is-ready': appReady || hideChrome, 'app-shell--bare': hideChrome }">
    <LegacyFloatPanels v-if="!hideChrome" />
    <AppGlobalProviders :show-lan-gate="!isAdminConsoleSpa()" />
    <VirtualCursorOverlay />

    <router-view v-if="hideChrome" />
    <MainLayout v-else>
      <router-view v-slot="{ Component, route }">
        <transition v-if="!isAdminConsoleSpa() && !isDesktopShell()" name="route-fade">
          <keep-alive :max="32">
            <component :is="Component" :key="String(route.name || route.path)" class="route-view-shell" />
          </keep-alive>
        </transition>
        <!-- 管理端与桌面壳不用 out-in：后台窗口的 requestAnimationFrame 可能暂停并卡住旧页面。 -->
        <RouteFallbackPanel v-else-if="routeChunkErrorPath" key="route-chunk-error" mode="chunk-error" :path="routeChunkErrorPath" class="route-view-shell" @dismiss="clearRouteChunkError" />
        <RouteFallbackPanel v-else-if="!Component && isUnmatchedRoute(route)" :key="`not-found:${route.fullPath}`" mode="not-found" :path="route.fullPath" class="route-view-shell" />
        <RouteErrorBoundary v-else :path="route.fullPath">
          <keep-alive v-if="isDesktopShell() && !isAdminConsoleSpa()" :key="cacheScope" :max="32">
            <Suspense v-on="routeReadinessHandlers">
              <component :is="Component" :key="route.fullPath.split('#')[0]" class="route-view-shell" />
              <template #fallback>
                <div class="route-view-shell route-view-shell--loading" aria-busy="true"><RouteLoadingFeedback active /></div>
              </template>
            </Suspense>
          </keep-alive>
          <Suspense v-else v-on="routeReadinessHandlers">
            <component :is="Component" :key="route.fullPath.split('#')[0]" class="route-view-shell" />
            <template #fallback>
              <div class="route-view-shell route-view-shell--loading" aria-busy="true"><RouteLoadingFeedback active /></div>
            </template>
          </Suspense>
        </RouteErrorBoundary>
      </router-view>
    </MainLayout>
  </div>
</template>
<style>
.startup-readiness {
  position: fixed;
  inset: 0;
  z-index: 2147483647;
  display: grid;
  place-items: center;
  padding: 24px;
  background: var(--app-bg, #f4f7fb);
  color: var(--app-text, #253858);
  outline: none;
}
.startup-readiness__panel { max-width: 480px; text-align: center; }
.startup-readiness h1 { font-size: 22px; }
.startup-readiness p { line-height: 1.6; overflow-wrap: anywhere; }
.startup-readiness__actions { display: flex; flex-wrap: wrap; justify-content: center; gap: 12px; margin-top: 24px; }
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

.route-view-shell--loading {
  justify-content: center;
  overflow: auto;
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
