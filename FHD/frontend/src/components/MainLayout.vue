<template>
  <div class="main-container">
    <div class="sidebar-shell" :class="{ collapsed: sidebarCollapsed }" :style="sidebarShellStyle" @mouseenter="onSidebarMouseEnter">
      <Sidebar :active-view="currentRouteName" @change-view="handleViewChange" />
      <PaneResizeHandle
        v-if="isSidebarFeatureEnabled && !sidebarCollapsed"
        orientation="vertical"
        label="调整侧边栏宽度"
        @resize-start="onSidebarResizeStart"
        @reset="resetSidebarWidth"
      />
    </div>
    <div
      v-if="isSidebarFeatureEnabled && sidebarCollapsed"
      class="sidebar-hover-trigger"
      @mouseenter="onHoverTriggerEnter"
      @mouseleave="onHoverTriggerLeave"
    >
      <button class="sidebar-peek-button" type="button" aria-label="展开侧边栏" title="展开侧边栏" @click="onHoverTriggerClick">▶</button>
    </div>
    <div class="main-content">
      <div v-if="isImpersonating" class="impersonate-bar" role="status">
        <span class="impersonate-bar__text">
          正在代管：<strong>{{ impersonationLabel }}</strong>
        </span>
        <button type="button" class="impersonate-bar__end" :disabled="endingImpersonation" @click="endImpersonation">
          {{ endingImpersonation ? '结束中…' : '结束代管' }}
        </button>
      </div>
      <div class="top-bar">
        <div class="page-title-wrap">
          <div class="page-kicker">{{ topKickerText }}</div>
          <div class="page-title">{{ currentViewTitle }}</div>
          <div v-if="accountUsername && displayBrand" class="page-account-sub muted">
            {{ accountUsername }}
          </div>
        </div>
        <button
          type="button"
          class="top-bar-settings-btn"
          :class="{ active: currentRouteName === 'settings' }"
          aria-label="系统设置"
          title="系统设置"
          data-tutorial-id="top-bar-settings"
          @click="openSettings"
        >
          <i class="fa fa-cog" aria-hidden="true"></i>
        </button>
        <TopAssistantFloat />
      </div>
      <slot></slot>
    </div>
    <DocumentPreviewPictureInPicture />
    <FloatingChatAssistant :visible="shouldShowFloatingChatAssistant" :male-avatar="adminConsoleSpa" />
    <VirtualCursor />
    <OnboardingTutorial />
    <TutorialOverlay v-if="!onboardingTutorialStore.active" />
    <TutorialTrainingCoach />
    <MobileBottomNav v-if="mobileBottomNavVisible" />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import { useIndustryStore } from '@/stores/industry'
import { useModsStore } from '@/stores/mods'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { xcmaxAdminApi } from '@/api/xcmaxAdmin'
import { LS_MARKET_USER_JSON } from '@/api/marketAccount'
import { isAdminConsoleSpa as detectAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import { ADMIN_OPERATOR_BRAND_SUBTITLE } from '@/constants/adminOperatorNav'
import { appAlert } from '@/utils/appDialog'
import { useResizablePane } from '@/composables/useResizablePane'
import { DEFAULT_INDUSTRY_ID } from '@/constants/industryDefaults'
import { getIndustryPreset } from '@/constants/industryPresets'
import { resolveCoreNavLabel, INDUSTRY_MENU_LABELS } from '@/utils/coreNavLabel'
import { isChatSidebarActive, normalizeSidebarActiveKey } from '@/utils/sidebarActiveKey'
import { SIDEBAR_ROUTE_NAME_MAP } from '@/constants/sidebarRouteNameMap'
import { navigateFromSidebarKey } from '@/utils/sidebarNavigation'
import { useModRoutes } from '@/composables/useModRoutes'
import FloatingChatAssistant from './FloatingChatAssistant.vue'
import DocumentPreviewPictureInPicture from './DocumentPreviewPictureInPicture.vue'
import PaneResizeHandle from './PaneResizeHandle.vue'
import Sidebar from './Sidebar.vue'
import TopAssistantFloat from './TopAssistantFloat.vue'
import TutorialOverlay from './TutorialOverlay.vue'
import VirtualCursor from './VirtualCursor.vue'
import OnboardingTutorial from './OnboardingTutorial.vue'
import TutorialTrainingCoach from './tutorial/TutorialTrainingCoach.vue'
import MobileBottomNav from './MobileBottomNav.vue'
import { useOnboardingTutorialStore } from '@/stores/onboardingTutorial'
import { useTutorialStore } from '@/stores/tutorial'
import { setTutorialBuildContextFactory } from '@/stores/tutorial'
import { useTutorialCatalog } from '@/composables/useTutorialCatalog'
import { documentPreviewPip } from '@/state/documentPreviewPip'
const route = useRoute()
const router = useRouter()
const onboardingTutorialStore = useOnboardingTutorialStore()
const tutorialStore = useTutorialStore()
const { active: onboardingTutorialActive } = storeToRefs(onboardingTutorialStore)
const { isActive: legacyTutorialActive } = storeToRefs(tutorialStore)
const isAnyTutorialActive = computed(() => onboardingTutorialActive.value || legacyTutorialActive.value)
const industryStore = useIndustryStore()
const modsStore = useModsStore()
const accountProfileStore = useAccountProfileStore()
const { modsForUi } = storeToRefs(modsStore)
const { displayBrand, isImpersonating, impersonatingUsername, companyBrand } = storeToRefs(accountProfileStore)
const endingImpersonation = ref(false)
const { modMenuItems } = useModRoutes()
const SIDEBAR_INACTIVITY_MS = 15000
const SIDEBAR_HOVER_OPEN_MS = 1000
const SIDEBAR_DISABLE_MQ = '(max-width: 767px)'
const MOBILE_BOTTOM_NAV_MQ = '(max-width: 768px)'
const SIDEBAR_PANE_KEY = 'main-layout.sidebar'
const ACTIVITY_EVENTS = ['mousemove', 'mousedown', 'keydown', 'wheel', 'touchstart']
const sidebarCollapsed = ref(false)
const isSidebarFeatureEnabled = ref(true)
let sidebarCollapseTimer = null
let sidebarHoverTimer = null
let sidebarViewportMedia = null
const showMobileBottomNav = ref(false)
let mobileBottomNavMedia = null
let layoutActive = true
const adminConsoleSpa = detectAdminConsoleSpa()

const { buildContext: tutorialBuildContext } = useTutorialCatalog()
setTutorialBuildContextFactory(() => tutorialBuildContext.value)

const workbenchKicker = computed(() => {
  const id = String(industryStore.currentIndustryId || DEFAULT_INDUSTRY_ID).trim() || DEFAULT_INDUSTRY_ID
  const name = getIndustryPreset(id).name
  return `${name}工作台`
})

const topKickerText = computed(() => {
  if (adminConsoleSpa) return ADMIN_OPERATOR_BRAND_SUBTITLE
  const brand = String(displayBrand.value || '').trim()
  if (brand) return brand
  return workbenchKicker.value
})

const accountUsername = computed(() => {
  try {
    const raw = window.localStorage.getItem(LS_MARKET_USER_JSON)
    if (!raw) return ''
    const u = JSON.parse(raw)
    return String(u?.username || '').trim()
  } catch {
    return ''
  }
})

const impersonationLabel = computed(() => {
  const brand = String(companyBrand.value || '').trim()
  if (brand) return brand
  const user = String(impersonatingUsername.value || '').trim()
  return user || '目标用户'
})

async function endImpersonation() {
  endingImpersonation.value = true
  try {
    await xcmaxAdminApi.endImpersonate()
    await accountProfileStore.refreshFromServer()
    try {
      await modsStore.initialize(true)
    } catch {
      /* ignore */
    }
    window.location.reload()
  } catch (e) {
    await appAlert(`结束代管失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    endingImpersonation.value = false
  }
}

const modPathToSidebarKey = computed(() => {
  const m = {}
  for (const item of modMenuItems.value) {
    if (item.path) m[item.path] = item.key
  }
  return m
})

const viewTitlesBase = {
  chat: '智能对话',
  'ai-ecosystem': '智能生态',
  brain: '智脑集成',
  'model-payment': '模型服务',
  'kitten-finance': '财务分析',
  'mod-store': '能力库',
  products: '业务对象',
  'materials-list': '资源库',
  materials: '资源库',
  'traditional-mode': '表格模式',
  'business-docking': '数据对接中心',
  orders: '业务单据',
  'orders-create': '新建业务单据',
  'shipment-records': '业务记录',
  customers: '组织管理',
  'data-sources': '数据来源',
  print: '模板与打印',
  'printer-list': '打印机列表',
  'template-preview': '模板库',
  console: '模板库',
  settings: '系统设置',
  im: '信息',
  tools: '工具表',
  'other-tools': '员工视图',
  'employee-workflow': '员工工作台',
  'erp-hr': '人事考勤',
  'attendance-employees': '人员管理',
  'attendance-departments': '部门管理',
  'attendance-records': '考勤记录',
  'workflow-employee-space': '员工空间',
  'workflow-visualization': '流程可视化',
  purchase: '耗材申领',
  'label-editor': '模板编辑器',
  'batch-analyze': '批量分析',
  'chat-debug': '对话调试',
  'enterprise-customer-service': '信息',
  'internal-customer-service': '信息',
  'admin-entitlements': '账号权益',
  'xcmax-admin': '服务器后台总览',
  'automation-policy': '自动化方针',
  'duty-time-architecture': '同时完成时间架构',
  'duty-roster-graph': '员工可视化',
  'server-functions': '服务器功能模块',
}

const routeNameMap = SIDEBAR_ROUTE_NAME_MAP

const currentRouteName = computed(() => {
  const modKey = modPathToSidebarKey.value[route.path]
  let raw = modKey || routeNameMap[route.path] || ''
  if (!raw) {
    for (const matched of [...route.matched].reverse()) {
      if (matched.path && routeNameMap[matched.path]) {
        raw = routeNameMap[matched.path]
        break
      }
    }
  }
  if (!raw) raw = String(route.name || '') || 'chat'
  return normalizeSidebarActiveKey(raw, route)
})

/** 侧栏选中「智能对话」时隐藏悬浮入口（含 Mod 门面 /mod/.../chat） */
const shouldShowFloatingChatAssistant = computed(() => !isChatSidebarActive(currentRouteName.value, route) && !documentPreviewPip.visible)

const {
  paneStyle: sidebarShellStyle,
  resetSize: resetSidebarWidth,
  startResize: onSidebarResizeStart,
  stopResize: stopSidebarResize,
} = useResizablePane({
  paneKey: SIDEBAR_PANE_KEY,
  cssVarName: '--sidebar-width',
  orientation: 'vertical',
  defaultSize: 236,
  minSize: 220,
  maxSize: 360,
  enabled: () => isSidebarFeatureEnabled.value && !sidebarCollapsed.value,
  onResizeStart: () => {
    clearSidebarCollapseTimer()
    clearSidebarHoverTimer()
  },
  onResizeEnd: () => {
    if (isSidebarFeatureEnabled.value && !sidebarCollapsed.value) {
      scheduleSidebarAutoCollapse()
    }
  },
})

/** 顶栏与页面标题：仅核心 + 行业（与侧栏 resolveCoreNavLabel / INDUSTRY_MENU_LABELS 同源），不含 Mod menu_overrides */
const viewTitles = computed(() => {
  const industryId = String(industryStore.currentIndustryId || DEFAULT_INDUSTRY_ID)
  const byIndustry = INDUSTRY_MENU_LABELS[industryId] || INDUSTRY_MENU_LABELS[DEFAULT_INDUSTRY_ID]
  return {
    ...viewTitlesBase,
    ...byIndustry,
  }
})

const currentViewTitle = computed(() => {
  const key = currentRouteName.value
  const industryId = String(industryStore.currentIndustryId || DEFAULT_INDUSTRY_ID)
  const fromNav = resolveCoreNavLabel(key, industryId, modsForUi.value)
  if (fromNav) return fromNav
  const fromMap = viewTitles.value[key]
  if (typeof fromMap === 'string' && fromMap.trim()) return fromMap
  const metaTitle = route.meta?.title
  if (typeof metaTitle === 'string' && metaTitle.trim()) return metaTitle
  return '未知页面'
})

async function navigateToView(viewKey) {
  await navigateFromSidebarKey(router, viewKey, {
    modMenuItems: modMenuItems.value,
    routeNameMap,
    getModRoutes: () => modsStore.modRoutes,
  })
}

const handleViewChange = (viewKey) => {
  void navigateToView(viewKey)
}

function openSettings() {
  void router.push({ name: 'settings' })
}

const clearSidebarCollapseTimer = () => {
  if (sidebarCollapseTimer) {
    window.clearTimeout(sidebarCollapseTimer)
    sidebarCollapseTimer = null
  }
}

const clearSidebarHoverTimer = () => {
  if (sidebarHoverTimer) {
    window.clearTimeout(sidebarHoverTimer)
    sidebarHoverTimer = null
  }
}

const ensureSidebarExpandedForTutorial = () => {
  clearSidebarCollapseTimer()
  clearSidebarHoverTimer()
  if (isSidebarFeatureEnabled.value) {
    sidebarCollapsed.value = false
  }
}

const scheduleSidebarAutoCollapse = () => {
  clearSidebarCollapseTimer()
  if (document.documentElement.classList.contains('xcagi-electron')) return void (sidebarCollapsed.value = false)
  if (isAnyTutorialActive.value) return
  if (!isSidebarFeatureEnabled.value || sidebarCollapsed.value) return
  sidebarCollapseTimer = window.setTimeout(() => {
    if (isAnyTutorialActive.value) return
    sidebarCollapsed.value = true
  }, SIDEBAR_INACTIVITY_MS)
}
watch(isAnyTutorialActive, (active) => {
  if (active) {
    ensureSidebarExpandedForTutorial()
    return
  }
  if (isSidebarFeatureEnabled.value && !sidebarCollapsed.value) {
    scheduleSidebarAutoCollapse()
  }
})

const handleGlobalActivity = () => {
  if (!isSidebarFeatureEnabled.value) return
  if (sidebarCollapsed.value) return
  scheduleSidebarAutoCollapse()
}

const onSidebarMouseEnter = () => {
  handleGlobalActivity()
}

const onHoverTriggerEnter = () => {
  if (!isSidebarFeatureEnabled.value || !sidebarCollapsed.value) return
  clearSidebarHoverTimer()
  sidebarHoverTimer = window.setTimeout(() => {
    sidebarCollapsed.value = false
    scheduleSidebarAutoCollapse()
  }, SIDEBAR_HOVER_OPEN_MS)
}

const onHoverTriggerLeave = () => {
  clearSidebarHoverTimer()
}

const onHoverTriggerClick = () => {
  clearSidebarHoverTimer()
  sidebarCollapsed.value = false
  scheduleSidebarAutoCollapse()
}

const onViewportChange = (event) => {
  const matches = Boolean(event?.matches)
  isSidebarFeatureEnabled.value = !matches
  clearSidebarHoverTimer()
  clearSidebarCollapseTimer()
  if (!isSidebarFeatureEnabled.value) {
    sidebarCollapsed.value = false
    stopSidebarResize()
    return
  }
  scheduleSidebarAutoCollapse()
}

const onMobileNavViewportChange = (event) => {
  showMobileBottomNav.value = Boolean(event?.matches)
}

const mobileBottomNavVisible = computed(() => showMobileBottomNav.value && !adminConsoleSpa && route.meta?.hideChrome !== true)

onMounted(async () => {
  if (!accountProfileStore.loaded) {
    try {
      await accountProfileStore.refreshFromServer()
    } catch {
      /* ignore */
    }
  }
  if (!industryStore.isLoaded) {
    try {
      await industryStore.initialize()
    } catch (_e) {
      // 行业信息加载失败时，顶部标题保持默认文案
    }
  }
  if (!layoutActive || typeof window === 'undefined') return
  sidebarViewportMedia = window.matchMedia?.(SIDEBAR_DISABLE_MQ) ?? null
  if (sidebarViewportMedia) {
    onViewportChange(sidebarViewportMedia)
    if (typeof sidebarViewportMedia.addEventListener === 'function') {
      sidebarViewportMedia.addEventListener('change', onViewportChange)
    } else if (typeof sidebarViewportMedia.addListener === 'function') {
      sidebarViewportMedia.addListener(onViewportChange)
    }
  }
  mobileBottomNavMedia = window.matchMedia?.(MOBILE_BOTTOM_NAV_MQ) ?? null
  if (mobileBottomNavMedia) {
    onMobileNavViewportChange(mobileBottomNavMedia)
    if (typeof mobileBottomNavMedia.addEventListener === 'function') {
      mobileBottomNavMedia.addEventListener('change', onMobileNavViewportChange)
    } else if (typeof mobileBottomNavMedia.addListener === 'function') {
      mobileBottomNavMedia.addListener(onMobileNavViewportChange)
    }
  }
  ACTIVITY_EVENTS.forEach((eventName) => {
    window.addEventListener(eventName, handleGlobalActivity, { passive: true })
  })
})

onBeforeUnmount(() => {
  layoutActive = false
  stopSidebarResize()
  clearSidebarHoverTimer()
  clearSidebarCollapseTimer()
  ACTIVITY_EVENTS.forEach((eventName) => {
    window.removeEventListener(eventName, handleGlobalActivity)
  })
  if (sidebarViewportMedia) {
    if (typeof sidebarViewportMedia.removeEventListener === 'function') {
      sidebarViewportMedia.removeEventListener('change', onViewportChange)
    } else if (typeof sidebarViewportMedia.removeListener === 'function') {
      sidebarViewportMedia.removeListener(onViewportChange)
    }
  }
  if (mobileBottomNavMedia) {
    if (typeof mobileBottomNavMedia.removeEventListener === 'function') {
      mobileBottomNavMedia.removeEventListener('change', onMobileNavViewportChange)
    } else if (typeof mobileBottomNavMedia.removeListener === 'function') {
      mobileBottomNavMedia.removeListener(onMobileNavViewportChange)
    }
  }
})
</script>

<style scoped>
.main-container {
  position: relative;
}

@media (max-width: 768px) {
  .main-container :deep(.main-content) {
    padding-bottom: calc(64px + env(safe-area-inset-bottom, 0));
  }
}

.sidebar-shell {
  position: relative;
  width: var(--sidebar-width, 236px);
  flex: 0 0 var(--sidebar-width, 236px);
  height: 100vh;
  min-width: 0;
  overflow: visible;
  transition:
    width 260ms cubic-bezier(0.2, 0.8, 0.2, 1),
    flex-basis 260ms cubic-bezier(0.2, 0.8, 0.2, 1);
}

.sidebar-shell :deep(.sidebar) {
  width: var(--sidebar-width, 236px);
  height: 100%;
  transition:
    transform 260ms cubic-bezier(0.2, 0.8, 0.2, 1),
    opacity 220ms ease;
  transform: translateX(0);
  opacity: 1;
}

.sidebar-shell.collapsed {
  width: 0;
  flex-basis: 0;
}

.sidebar-shell.collapsed :deep(.sidebar) {
  transform: translateX(100%);
  opacity: 0;
  pointer-events: none;
}

.sidebar-hover-trigger {
  position: absolute;
  top: 0;
  left: 0;
  bottom: 0;
  width: 18px;
  z-index: 30;
  display: flex;
  align-items: center;
  justify-content: center;
}

.sidebar-peek-button {
  width: 16px;
  height: 52px;
  border: 1px solid rgba(74, 144, 217, 0.45);
  border-left: none;
  border-radius: 0 10px 10px 0;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(231, 240, 251, 0.95));
  color: #2563eb;
  font-size: 10px;
  line-height: 1;
  font-weight: 700;
  cursor: pointer;
  box-shadow: 0 6px 16px rgba(37, 99, 235, 0.16);
  transition:
    transform 160ms ease,
    box-shadow 160ms ease,
    background 160ms ease;
}

.sidebar-peek-button:hover {
  transform: translateX(1px);
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.2);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(219, 234, 254, 0.96));
}

.sidebar-peek-button:active {
  transform: translateX(0);
}

.page-title-wrap {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.page-kicker {
  font-size: 11px;
  line-height: 1;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: rgba(71, 85, 105, 0.72);
}

.page-account-sub {
  font-size: 12px;
  line-height: 1.2;
  color: rgba(100, 116, 139, 0.9);
}

.impersonate-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 8px 16px;
  background: linear-gradient(90deg, #fff7ed, #ffedd5);
  border-bottom: 1px solid #fdba74;
  color: #9a3412;
  font-size: 13px;
}

.impersonate-bar__end {
  border: 1px solid #fb923c;
  background: #fff;
  color: #c2410c;
  border-radius: 8px;
  padding: 4px 12px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.impersonate-bar__end:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.top-bar-settings-btn {
  margin-left: 10px;
  width: 36px;
  height: 36px;
  border: 1px solid rgba(203, 213, 225, 0.85);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.88);
  color: #475569;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition:
    background 0.15s ease,
    border-color 0.15s ease,
    color 0.15s ease;
}

.top-bar-settings-btn:hover,
.top-bar-settings-btn.active {
  color: #0b72d9;
  border-color: rgba(11, 114, 217, 0.35);
  background: rgba(239, 246, 255, 0.96);
}
</style>
