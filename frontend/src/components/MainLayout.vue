<template>
  <div class="main-container">
    <div
      class="sidebar-shell"
      :class="{ collapsed: sidebarCollapsed }"
      :style="sidebarShellStyle"
      @mouseenter="onSidebarMouseEnter"
    >
      <Sidebar
        :active-view="currentRouteName"
        :is-pro-mode="isProMode"
        @change-view="handleViewChange"
        @toggle-pro-mode="$emit('toggle-pro-mode')"
      />
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
      <button
        class="sidebar-peek-button"
        type="button"
        aria-label="展开侧边栏"
        title="展开侧边栏"
        @click="onHoverTriggerClick"
      >
        ▶
      </button>
    </div>
    <div class="main-content">
      <div class="top-bar">
        <div class="page-title-wrap">
          <div class="page-kicker">XCmax 服务器后台</div>
          <div class="page-title">{{ currentViewTitle }}</div>
        </div>
        <div
          class="mode-badge"
          :class="[props.isProMode ? 'pro' : 'normal', { 'with-mod': hasModsForUi }]"
        >
          {{ modeBadgeText }}
        </div>
        <TopAssistantFloat />
      </div>
      <slot></slot>
    </div>
    <FloatingChatAssistant :visible="shouldShowFloatingChatAssistant" />
    <TutorialOverlay />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import { useIndustryStore } from '@/stores/industry'
import { useModsStore } from '@/stores/mods'
import { useResizablePane } from '@/composables/useResizablePane'
import { DEFAULT_INDUSTRY_ID } from '@/constants/industryDefaults'
import { resolveCoreNavLabel, INDUSTRY_MENU_LABELS } from '@/utils/coreNavLabel'
import { useModRoutes } from '@/composables/useModRoutes'
import FloatingChatAssistant from './FloatingChatAssistant.vue'
import PaneResizeHandle from './PaneResizeHandle.vue'
import Sidebar from './Sidebar.vue'
import TopAssistantFloat from './TopAssistantFloat.vue'
import TutorialOverlay from './TutorialOverlay.vue'

const props = defineProps({
  isProMode: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['toggle-pro-mode'])

const route = useRoute()
const router = useRouter()
const industryStore = useIndustryStore()
const modsStore = useModsStore()
const { modsForUi } = storeToRefs(modsStore)
const { modMenuItems } = useModRoutes()
const SIDEBAR_INACTIVITY_MS = 15000
const SIDEBAR_HOVER_OPEN_MS = 1000
const SIDEBAR_DISABLE_MQ = '(max-width: 767px)'
const SIDEBAR_PANE_KEY = 'main-layout.sidebar'
const ACTIVITY_EVENTS = ['mousemove', 'mousedown', 'keydown', 'wheel', 'touchstart']
const sidebarCollapsed = ref(false)
const isSidebarFeatureEnabled = ref(true)
let sidebarCollapseTimer = null
let sidebarHoverTimer = null
let sidebarViewportMedia = null

const isSandboxMode = new URLSearchParams(window.location.search).has('sandbox')

/** 原版模式或未加载扩展时为空，与侧栏 Mod 菜单一致 */
const hasModsForUi = computed(() => modsForUi.value.length > 0)

/** 顶栏角标：普通/专业 + 已加载 Mod 时追加简写（如 ·Pro） */
function resolveModBadgeSuffix() {
  const list = modsForUi.value
  if (!list.length) return ''
  const lead = list.find((m) => m.primary) || list[0]
  const name = String(lead?.name || lead?.id || 'Mod').trim()
  if (!name) return 'Mod'
  return name.length <= 8 ? name : `${name.slice(0, 7)}…`
}

const modeBadgeText = computed(() => {
  if (isSandboxMode) return '沙箱模式'
  const base = props.isProMode ? '管理端' : '普通版'
  if (!hasModsForUi.value) return base
  return `${base}·${resolveModBadgeSuffix()}`
})

const modPathToSidebarKey = computed(() => {
  const m = {}
  for (const item of modMenuItems.value) {
    if (item.path) m[item.path] = item.key
  }
  return m
})

const viewTitlesBase = {
  'xcmax-admin': '服务器后台',
  chat: '智能对话',
  'ai-ecosystem': '智能生态',
  brain: '智脑集成',
  'model-payment': '模型服务',
  'kitten-finance': '财务分析',
  'mod-store': '扩展市场',
  products: '人员管理',
  'materials-list': '班次列表',
  materials: '服务器功能模块',
  'traditional-mode': '表格模式',
  'business-docking': '业务对接',
  orders: '考勤单管理',
  'orders-create': '新建考勤单',
  'shipment-records': '考勤记录',
  customers: '部门管理',
  'data-sources': '数据来源',
  'wechat-contacts': '企业微信联系人',
  print: '考勤表打印',
  'printer-list': '打印机列表',
  'template-preview': '模板库',
  console: '模板库',
  settings: '系统设置',
  tools: '工具表',
  'workflow-visualization': '流程可视化',
  purchase: '耗材申领',
  'label-editor': '模板编辑器',
  'batch-analyze': '批量分析',
  'chat-debug': '对话调试',
  'enterprise-customer-service': '外部客服',
  'other-tools': '员工工作流',
  'workflow-employee-space': '员工空间',
  'workflow-employee-stitch-full': '员工工作流全景',
  'workflow-employee-load-remove': '加载和去除员工'
}

const routeNameMap = {
  '/xcmax-admin': 'xcmax-admin',
  '/': 'chat',
  '/ai-ecosystem': 'ai-ecosystem',
  '/brain': 'brain',
  '/model-payment': 'model-payment',
  '/kitten-finance': 'kitten-finance',
  '/mod-store': 'mod-store',
  '/products': 'products',
  '/materials-list': 'materials-list',
  '/materials': 'materials',
  '/traditional-mode': 'traditional-mode',
  '/business-docking': 'business-docking',
  '/orders': 'orders',
  '/orders/create': 'orders-create',
  '/shipment-records': 'shipment-records',
  '/customers': 'customers',
  '/data-sources': 'data-sources',
  '/wechat-contacts': 'wechat-contacts',
  '/print': 'print',
  '/printer-list': 'printer-list',
  '/template-preview': 'template-preview',
  '/console': 'console',
  '/settings': 'settings',
  '/tools': 'tools',
  '/workflow-visualization': 'workflow-visualization',
  '/purchase': 'purchase',
  '/label-editor': 'label-editor',
  '/batch-analyze': 'batch-analyze',
  '/chat-debug': 'chat-debug',
  '/enterprise-customer-service': 'enterprise-customer-service',
  '/approval-hub': 'approval-hub',
  '/approval-hub/workspace': 'approval-hub',
  '/approval-hub/flows': 'approval-hub',
  '/approval-hub/rules': 'approval-hub',
  '/inventory': 'inventory',
  '/other-tools': 'other-tools',
  '/other-tools/employee-load-remove': 'other-tools',
  '/workflow-employee-space': 'workflow-employee-space',
  '/workflow-employee-space/stitch-full': 'workflow-employee-stitch-full'
}

const currentRouteName = computed(() => {
  const modKey = modPathToSidebarKey.value[route.path]
  if (modKey) return modKey
  const direct = routeNameMap[route.path]
  if (direct) return direct
  // 对嵌套子路由：沿着 matched 链找第一个命中 routeNameMap 的父路径
  for (const matched of [...route.matched].reverse()) {
    if (matched.path && routeNameMap[matched.path]) return routeNameMap[matched.path]
  }
  return String(route.name || '') || 'chat'
})

const shouldShowFloatingChatAssistant = computed(() => {
  return currentRouteName.value !== 'chat'
})

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
  const byIndustry =
    INDUSTRY_MENU_LABELS[industryId] || INDUSTRY_MENU_LABELS[DEFAULT_INDUSTRY_ID]
  return {
    ...viewTitlesBase,
    ...byIndustry,
  }
})

const currentViewTitle = computed(() => {
  if (route.name === 'workflow-employee-load-remove') {
    const metaTitle = route.meta?.title
    if (typeof metaTitle === 'string' && metaTitle.trim()) return metaTitle
    return '加载和去除员工'
  }
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

const handleViewChange = (viewKey) => {
  const modItem = modMenuItems.value.find((m) => m.key === viewKey)
  if (modItem?.path) {
    router.push(modItem.path)
    return
  }
  // 侧栏 key 与核心路由 name 一致，优先按名称跳转，避免 routeNameMap 漏配或反查顺序问题
  if (typeof viewKey === 'string' && router.hasRoute(viewKey)) {
    router.push({ name: viewKey })
    return
  }
  const routePath = Object.entries(routeNameMap).find(
    ([, name]) => name === viewKey
  )?.[0]
  if (routePath) {
    router.push(routePath)
    return
  }
  console.warn('[MainLayout] 侧栏无对应路由:', viewKey)
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

const scheduleSidebarAutoCollapse = () => {
  if (!isSidebarFeatureEnabled.value || sidebarCollapsed.value) return
  clearSidebarCollapseTimer()
  sidebarCollapseTimer = window.setTimeout(() => {
    sidebarCollapsed.value = true
  }, SIDEBAR_INACTIVITY_MS)
}

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
  isSidebarFeatureEnabled.value = !event.matches
  clearSidebarHoverTimer()
  clearSidebarCollapseTimer()
  if (!isSidebarFeatureEnabled.value) {
    sidebarCollapsed.value = false
    stopSidebarResize()
    return
  }
  scheduleSidebarAutoCollapse()
}

onMounted(async () => {
  if (!industryStore.isLoaded) {
    try {
      await industryStore.initialize()
    } catch (_e) {
      // 行业信息加载失败时，顶部标题保持默认文案
    }
  }
  sidebarViewportMedia = window.matchMedia(SIDEBAR_DISABLE_MQ)
  onViewportChange(sidebarViewportMedia)
  if (typeof sidebarViewportMedia.addEventListener === 'function') {
    sidebarViewportMedia.addEventListener('change', onViewportChange)
  } else if (typeof sidebarViewportMedia.addListener === 'function') {
    sidebarViewportMedia.addListener(onViewportChange)
  }
  ACTIVITY_EVENTS.forEach((eventName) => {
    window.addEventListener(eventName, handleGlobalActivity, { passive: true })
  })
})

onBeforeUnmount(() => {
  stopSidebarResize()
  clearSidebarHoverTimer()
  clearSidebarCollapseTimer()
  ACTIVITY_EVENTS.forEach((eventName) => {
    window.removeEventListener(eventName, handleGlobalActivity)
  })
  if (!sidebarViewportMedia) return
  if (typeof sidebarViewportMedia.removeEventListener === 'function') {
    sidebarViewportMedia.removeEventListener('change', onViewportChange)
  } else if (typeof sidebarViewportMedia.removeListener === 'function') {
    sidebarViewportMedia.removeListener(onViewportChange)
  }
})
</script>

<style scoped>
.main-container {
  position: relative;
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

.mode-badge {
  margin-left: auto;
  padding: 7px 12px;
  border-radius: 999px;
  font-size: var(--app-font-size-caption, 12px);
  line-height: 1;
  font-weight: 800;
  letter-spacing: 0.01em;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.72);
}

.mode-badge.normal {
  color: #1e3a8a;
  background: linear-gradient(135deg, rgba(239, 246, 255, 0.96), rgba(219, 234, 254, 0.92));
  border: 1px solid rgba(147, 197, 253, 0.62);
}

.mode-badge.pro {
  color: #7dd3fc;
  background: linear-gradient(135deg, rgba(14, 116, 144, 0.3), rgba(15, 23, 42, 0.78));
  border: 1px solid rgba(125, 211, 252, 0.35);
}

/* 已加载 Mod：在普通/专业底子上略强调「扩展环境」 */
.mode-badge.with-mod.normal {
  background: linear-gradient(135deg, #eef2ff 0%, #e0e7ff 100%);
  border-color: #a5b4fc;
  color: #3730a3;
}

.mode-badge.with-mod.pro {
  box-shadow: 0 0 0 1px rgba(125, 211, 252, 0.2);
}

</style>
