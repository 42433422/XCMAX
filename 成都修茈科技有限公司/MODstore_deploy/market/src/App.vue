<template>
  <div
    class="app-shell"
    :class="{
      'app-shell--wb-home': isWorkbenchHome,
      'app-shell--viewport-locked': showAuthenticatedShell,
      'app-shell--android-embedded': isAndroidEmbeddedShell,
      'app-shell--drawer-open': showAuthenticatedShell && isMobileViewport && wbSidebar.mobileOpen,
    }"
  >
    <div v-if="showAuthenticatedShell" class="app-body" :style="{ '--wb-sidebar-w': wbSidebarWidthCss }">
      <nav class="navbar app-legacy-nav-compat" role="navigation" aria-label="主导航" aria-hidden="true" style="display: none">
        <span>工作台</span>
        <span>会员</span>
        <span>AI 客服</span>
        <span>AI 测试</span>
        <button type="button" class="nav-self-credit-btn" @click="openSelfCreditModal">
          ¥{{ Number(balance || 0).toFixed(2) }}
        </button>
        <button type="button" class="mode-tab" @click="switchMode('client')">客户端</button>
        <button v-if="isAdmin" type="button" class="mode-tab" @click="switchMode('admin')">管理端</button>
        <span v-if="currentMode === 'admin'">AI 客服后台</span>
      </nav>
      <AppMobileNav
        :is-android-embedded-shell="isAndroidEmbeddedShell"
        @toggle-mobile="wbSidebar.toggleMobileDrawer()"
      />
      <AppSidebar
        :is-android-embedded-shell="isAndroidEmbeddedShell"
        :is-mobile-viewport="isMobileViewport"
        :conv-swipe-offset="convSwipeOffset"
        @new-chat="handleNewChat"
        @pick-conversation="handlePickConversation"
        @conv-touchstart="onConvTouchStart"
        @conv-touchmove="onConvTouchMove"
        @conv-touchend="onConvTouchEnd"
        @conv-mousedown="onConvMouseDown"
        @remove-conversation="void confirmRemoveConversation($event)"
        @mode-click="handleModeClick"
        @settings="handleSidebarSettings"
        @admin-enter="enterAdminRoute"
        @logout="() => void doLogout()"
        @back-client="switchMode('client')"
      />
      <main
        class="main-content main-content--with-sidebar"
        :class="{
          'main-content--home': isHome,
          'main-content--employee-full': isEmployeeWorkbench,
          'main-content--wb-home': isWorkbenchHome,
          'main-content--account': isAccountPage,
          'main-content--download': isDownloadPage,
        }"
      >
        <div class="main-content-router">
          <router-view v-slot="{ Component }">
            <keep-alive :max="6">
              <component v-if="Component" :is="Component" :key="topLevelRouterCacheKey" />
            </keep-alive>
          </router-view>
        </div>
      </main>
    </div>
    <main
      v-if="!showAuthenticatedShell"
      class="main-content"
      :class="{
        'main-content--home': isHome,
        'main-content--employee-full': isEmployeeWorkbench,
        'main-content--wb-home': isWorkbenchHome,
        'main-content--account': isAccountPage,
        'main-content--download': isDownloadPage,
      }"
    >
      <div class="main-content-router">
        <router-view v-slot="{ Component }">
          <!-- keep-alive：从 AI 客服、脚本工作流沙箱等返回时保留工作台内存态（「做」规划、一档聊天等），避免整页重新挂载丢进度 -->
          <!-- max 从 24 降为 6：限制同时持有响应式订阅的实例数，减少内存与后台 watcher 开销 -->
          <keep-alive :max="6">
            <component v-if="Component" :is="Component" :key="topLevelRouterCacheKey" />
          </keep-alive>
        </router-view>
      </div>
    </main>
    <Teleport to="body">
      <CorpButlerRoot v-if="shouldShowGuestCorpButler" />
      <FloatingAgentRoot v-if="shouldShowButler" :male-avatar="shouldUseMaleButlerAvatar" />
      <div
        v-if="selfCreditOpen"
        class="nav-self-credit-overlay"
        role="presentation"
        @click.self="closeSelfCreditModal"
      >
        <div
          class="nav-self-credit-dialog"
          role="dialog"
          aria-modal="true"
          :aria-label="t('nav.adminSelfCreditTitle')"
          @click.stop
        >
          <h3 class="nav-self-credit-dialog__title">{{ t('nav.adminSelfCreditTitle') }}</h3>
          <p class="nav-self-credit-dialog__hint">{{ t('nav.adminSelfCreditHint') }}</p>
          <label class="nav-self-credit-dialog__label">{{ t('nav.adminSelfCreditAmount') }}</label>
          <input
            v-model="selfCreditAmount"
            type="number"
            min="0.01"
            step="0.01"
            class="nav-self-credit-dialog__input"
            autocomplete="off"
          />
          <label class="nav-self-credit-dialog__label">{{ t('nav.adminSelfCreditNote') }}</label>
          <input v-model="selfCreditNote" type="text" class="nav-self-credit-dialog__input" autocomplete="off" />
          <p v-if="selfCreditErr" class="nav-self-credit-dialog__err">{{ selfCreditErr }}</p>
          <div class="nav-self-credit-dialog__actions">
            <button type="button" class="nav-self-credit-dialog__primary" :disabled="selfCreditBusy" @click="submitSelfCredit">
              {{ t('nav.adminSelfCreditSubmit') }}
            </button>
            <button type="button" class="nav-self-credit-dialog__secondary" :disabled="selfCreditBusy" @click="closeSelfCreditModal">
              {{ t('nav.adminSelfCreditCancel') }}
            </button>
          </div>
        </div>
      </div>
      <div
        v-if="adminUnlockOpen"
        class="nav-self-credit-overlay"
        role="presentation"
        @click.self="closeAdminUnlockModal"
      >
        <div
          class="nav-self-credit-dialog"
          role="dialog"
          aria-modal="true"
          aria-label="管理端解锁"
          @click.stop
        >
          <h3 class="nav-self-credit-dialog__title">解锁管理端</h3>
          <p class="nav-self-credit-dialog__hint">
            请输入<strong>连续 6 位</strong>十六进制身份校验码（可从 XCmax「服务器功能」页眉<strong>身份码</strong>复制，或从当日摘要邮件正文中复制）。<br />
            <span class="nav-admin-unlock__hint-warn">须与<strong>当前浏览器所连市场 API</strong>为同一套 MODstore，或运维已配置<strong>跨库校验</strong>（自建签发 + 公网消费，见服务器 .env.example）。</span><br />
            <span class="nav-admin-unlock__hint-warn"
              >若摘要邮件由<strong>自建服务器</strong>发出，而当前站点为公网修茈市场，则<strong>本页无法校验该码</strong>；请用 XCmax 页眉的<strong>打开市场</strong>或自建站点解锁。</span
            ><br />
            <span class="nav-admin-unlock__hint-warn">请勿填示例；可含空格，失焦或提交时会自动去掉非十六进制字符并只取前 6 位。</span>
          </p>
          <label class="nav-self-credit-dialog__label">身份校验码</label>
          <input
            v-model="adminUnlockCode"
            type="text"
            maxlength="32"
            inputmode="text"
            autocomplete="off"
            spellcheck="false"
            class="nav-self-credit-dialog__input nav-admin-unlock__code"
            placeholder="粘贴 6 位码"
            @blur="onAdminUnlockInputBlur"
            @keyup.enter="submitAdminUnlock"
          />
          <p v-if="adminUnlockErr" class="nav-self-credit-dialog__err">{{ adminUnlockErr }}</p>
          <div class="nav-self-credit-dialog__actions">
            <button type="button" class="nav-self-credit-dialog__primary" :disabled="adminUnlockBusy" @click="submitAdminUnlock">
              {{ adminUnlockBusy ? '校验中…' : '解锁管理端' }}
            </button>
            <button type="button" class="nav-self-credit-dialog__secondary" @click="closeAdminUnlockModal">
              取消
            </button>
          </div>
        </div>
      </div>
    </Teleport>
    <AppToastHost />
    <AppConfirmDialog />
  </div>
</template>

<script setup lang="ts">
// 拆分后本文件为根组装入口（façade）：逻辑在 ./app-shell/，模板子组件在 ./app-shell/，样式在 ./app-shell/app.css。
// 根结构与初始化时序与拆分前保持一致；defineExpose 面不变（仅 isAiTestRoute）。
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from './i18n'
import { useAuthStore } from './stores/auth'
import { getAccessToken } from './infrastructure/storage/tokenStore'
import { useNotificationStore } from './stores/notifications'
import { useWalletStore } from './stores/wallet'
import { connectRealtime, disconnectRealtime } from './realtimeClient'
import FloatingAgentRoot from './components/floating-agent/FloatingAgentRoot.vue'
import CorpButlerRoot from './corp-butler/CorpButlerRoot.vue'
import { useWorkbenchSidebarStore } from './stores/workbenchSidebar'
import { resolveTopLevelRouterCacheKey } from './router/topLevelCacheKey'
import { installVisualViewportInset } from './composables/useVisualViewportInset'
import AppToastHost from './components/AppToastHost.vue'
import AppConfirmDialog from './components/AppConfirmDialog.vue'
import AppMobileNav from './app-shell/AppMobileNav.vue'
import AppSidebar from './app-shell/AppSidebar.vue'
import * as appShellTypes from './app-shell/appShellTypes'
import { useAppGlobalState } from './app-shell/useAppGlobalState'
import { useSelfCredit } from './app-shell/useSelfCredit'
import { useAdminUnlock } from './app-shell/useAdminUnlock'
import { useConversationSwipe } from './app-shell/useConversationSwipe'
import { useShellActions } from './app-shell/useShellActions'

const router = useRouter()
const route = useRoute()

const topLevelRouterCacheKey = computed(() =>
  resolveTopLevelRouterCacheKey({
    path: route.path,
    name: route.name,
    fullPath: route.fullPath,
  }),
)

const isAccountPage = computed(() => route.name === 'account')
const isPublicLayoutRoute = computed(() => route.meta.layout === 'public')
const isDownloadPage = computed(() => false)
const isWorkbenchHome = computed(() => {
  const n = String(route.name || '')
  const p = route.path
  return p === '/' || p === '/workbench/home' || n === 'home' || n === 'workbench-home'
})

/** Android App 内嵌单 Mod 运行时：隐藏整站侧栏与悬浮管家 */
const isAndroidEmbeddedShell = computed(() => {
  if (typeof window === 'undefined') return false
  const w = window as Window & { __XCAGI_CLIENT__?: string }
  const androidClient =
    w.__XCAGI_CLIENT__ === 'android' ||
    document.documentElement.classList.contains('xcagi-client-android')
  if (!androidClient) return false
  const embedded =
    new URLSearchParams(window.location.search).get('embedded') === 'android' ||
    document.documentElement.classList.contains('xcagi-embedded-android')
  return embedded && route.path.startsWith('/workbench/mod/')
})
const isAiTestRoute = computed(() => {
  const n = String(route.name || '')
  return n === 'ai-test-sandbox' || n === 'ai-test-exam' || route.path.startsWith('/ai-test')
})
const { t } = useI18n()
const authStore = useAuthStore()
const walletStore = useWalletStore()
const notificationStore = useNotificationStore()
const wbSidebar = useWorkbenchSidebarStore()
const isMobileViewport = ref(false)
function syncMobileViewport() {
  isMobileViewport.value =
    typeof window !== 'undefined' && window.matchMedia('(max-width: 768px)').matches
}
const wbSidebarWidthCss = computed(() => {
  if (isAndroidEmbeddedShell.value) return '0px'
  if (isMobileViewport.value) return '0px'
  return wbSidebar.sidebarCollapsed ? '56px' : '240px'
})
const { isLoggedIn, isAdmin, currentMode, user: authUser } = storeToRefs(authStore)
const { balance } = storeToRefs(walletStore)
/** 有 JWT 即渲染带侧栏壳层；公开落地页（layout: public）始终全宽展示，避免与 HomeView 顶栏/移动端 Tab 叠层 */
const showAuthenticatedShell = computed(() => {
  void authUser.value
  if (isPublicLayoutRoute.value) return false
  return Boolean(getAccessToken())
})

const { isHome, isEmployeeWorkbench, checkHome, refreshGlobalState, _scheduleGlobalRefresh } = useAppGlobalState()

const BUTLER_EXCLUDED_PATHS = ['/about', '/login', '/login-email', '/forgot-password', '/register']
const shouldShowButler = computed(() => {
  const p = route.path || ''
  if (!isLoggedIn.value) return false
  if (isAndroidEmbeddedShell.value) return false
  return !BUTLER_EXCLUDED_PATHS.some((ep) => p === ep || p.startsWith(ep + '/'))
})
/** 管理员账号统一男版小 C；普通用户统一女版（含桌面客户端）。 */
const shouldUseMaleButlerAvatar = computed(() => isAdmin.value)
/** 未登录访客在公开落地页使用官网咨询引擎（不调用需登录的 Butler API） */
const shouldShowGuestCorpButler = computed(() => {
  if (isLoggedIn.value) return false
  if (isAndroidEmbeddedShell.value) return false
  return String(route.name || '') === 'about'
})

const {
  selfCreditOpen, selfCreditAmount, selfCreditNote, selfCreditErr, selfCreditBusy,
  openSelfCreditModal, closeSelfCreditModal, submitSelfCredit,
} = useSelfCredit()

const {
  pendingAdminRouteName, adminUnlockOpen, adminUnlockCode, adminUnlockErr, adminUnlockBusy,
  onAdminUnlockInputBlur, openAdminUnlockModal, closeAdminUnlockModal, submitAdminUnlock, enterAdminRoute,
} = useAdminUnlock({ isAdmin, currentMode })

const {
  convSwipeOffset, convJustSwiped,
  onConvTouchStart, onConvTouchMove, onConvTouchEnd, onConvMouseDown, onConvMouseMove, onConvMouseUp,
} = useConversationSwipe()

const {
  switchMode, handleSidebarSettings, handleNewChat, handlePickConversation,
  emitWorkbenchModeSwitch, handleModeClick, confirmRemoveConversation, doLogout,
} = useShellActions({
  router, wbSidebar, isWorkbenchHome, convSwipeOffset, convJustSwiped, currentMode, enterAdminRoute,
})

// 顶层 const 保持 wrapper.vm 对拆分前绑定的可访问面一致。
const formatConvTime = appShellTypes.formatConvTime

watch(
  () => wbSidebar.mobileOpen,
  (open, wasOpen) => {
    if (!isMobileViewport.value) return
    if (!open && wasOpen) {
      nextTick(() => {
        const sidebar = document.getElementById('wb-sidebar')
        const active = document.activeElement
        if (sidebar && active && sidebar.contains(active)) {
          document.querySelector<HTMLElement>('.wb-mobile-hamburger')?.focus()
        }
      })
      return
    }
    if (!open) return
    nextTick(() => {
      const btn = document.querySelector<HTMLElement>('#wb-sidebar .wb-sidebar-new-chat')
      btn?.focus()
    })
  },
)

onMounted(() => {
  syncMobileViewport()
  window.addEventListener('resize', syncMobileViewport)
  cleanupVisualViewportInset = installVisualViewportInset()
  checkHome()
  wbSidebar.initConversations()
  void refreshGlobalState()
})

let cleanupVisualViewportInset: (() => void) | null = null

onUnmounted(() => {
  window.removeEventListener('resize', syncMobileViewport)
  cleanupVisualViewportInset?.()
  cleanupVisualViewportInset = null
})

router.afterEach(() => {
  checkHome()
  _scheduleGlobalRefresh()
})

watch(
  isLoggedIn,
  (v) => {
    if (v) {
      connectRealtime(() => void notificationStore.refreshUnread())
    } else {
      disconnectRealtime(true)
    }
  },
  { immediate: true },
)

/** 聊天首页依赖左侧会话栏；从「统一工作台」等页返回时恢复展开（桌面端） */
watch(
  isWorkbenchHome,
  (onHome) => {
    if (!onHome || isMobileViewport.value) return
    wbSidebar.sidebarCollapsed = false
  },
  { immediate: true },
)

onMounted(() => {
  window.addEventListener('mousemove', onConvMouseMove)
  window.addEventListener('mouseup', onConvMouseUp)
})

onUnmounted(() => {
  window.removeEventListener('mousemove', onConvMouseMove)
  window.removeEventListener('mouseup', onConvMouseUp)
})

defineExpose({ isAiTestRoute })
</script>

<style src="./app-shell/app.css"></style>
