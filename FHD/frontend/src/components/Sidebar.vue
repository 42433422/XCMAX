<template>
  <div class="sidebar">
    <div class="sidebar-header">
      <div class="sidebar-brand" aria-label="品牌与标题">
        <img class="sidebar-brand-logo" :src="sidebarLogoSrc" height="40" alt="XC" decoding="async" @error="onSidebarLogoError" />
        <div class="sidebar-brand-text">
          <h4>{{ sidebarBrandTitle }}</h4>
          <small style="opacity: 0.7">{{ sidebarBrandSubtitle }}</small>
        </div>
      </div>
    </div>
    <nav
      ref="sidebarMenuRef"
      class="sidebar-menu"
      data-tour="sidebar-menu"
      :class="{ 'reorder-enabled': sidebarLayoutStore.reorderEnabled, 'is-dragging': draggingKey }"
      aria-label="主导航"
    >
      <component
        :is="draggingKey ? TransitionGroup : 'div'"
        v-bind="draggingKey ? { name: 'sidebar-menu-shift', tag: 'div' } : {}"
        class="sidebar-menu-shift-wrap"
      >
        <SidebarMenuItem
          v-for="item in displayMenuItems"
          :key="item.key"
          v-memo="[
            item.key,
            item.name,
            activeView === item.key || activeParentKeys.has(item.key),
            item.children?.length ? (item.children.find((child) => child.key === activeView)?.key ?? '') : '',
            expandedKeys.has(item.key),
            pressingKey === item.key,
            draggingKey === item.key,
            dragOverKey,
          ]"
          :item="item"
          :active-view="activeView"
          :is-active="activeView === item.key || activeParentKeys.has(item.key)"
          :has-active-child="activeParentKeys.has(item.key)"
          :is-expanded="expandedKeys.has(item.key)"
          :is-pressing="pressingKey === item.key"
          :is-dragging="draggingKey === item.key"
          :long-press-ms="LONG_PRESS_MS"
          :im-unread-total="imUnreadTotal"
          @parent-click="onParentMenuClick(item)"
          @select-view="selectView"
          @reorder-pointer-down="onReorderPointerDown($event, item.key)"
          @keydown="onMenuItemKeydown($event, item.key)"
        />
      </component>
    </nav>
    <div class="sidebar-menu-bottom" role="navigation" aria-label="系统">
      <button
        class="menu-item"
        type="button"
        :class="{
          active: activeView === settingsMenuItem.key,
        }"
        :data-view="settingsMenuItem.key"
        :data-tour="`sidebar-${settingsMenuItem.key}`"
        :aria-label="settingsMenuItem.name"
        :aria-current="activeView === settingsMenuItem.key ? 'page' : undefined"
        :title="settingsMenuItem.description ? `${settingsMenuItem.name} · ${settingsMenuItem.description}` : settingsMenuItem.name"
        @click="selectView(settingsMenuItem.key)"
      >
        <span class="menu-item-icon" aria-hidden="true">
          <i class="fa" :class="settingsMenuItem.iconClass"></i>
        </span>
        <span>{{ settingsMenuItem.name }}</span>
      </button>
    </div>
    <div class="sidebar-footer">
      <div class="sidebar-status-mods-row">
        <div class="status-indicator">
          <button
            type="button"
            class="runtime-health-button"
            :title="runtimeHealth.detail"
            :aria-label="`${runtimeHealth.text}，打开系统设置`"
            @click="selectView(settingsMenuItem.key)"
          >
            <span class="status-dot" :class="runtimeHealth.tone" aria-hidden="true"></span>
            <span role="status">{{ runtimeHealth.text }}</span>
          </button>
          <DesktopAppUpdatePrompt />
          <span
            v-if="adminDeployStatusText"
            class="sidebar-update-chip"
            :class="`is-${adminDeployStatusTone}`"
            :title="adminDeployStatusTitle"
          >
            {{ adminDeployStatusText }}
          </span>
          <span
            v-if="entitlementSyncStatusText"
            class="sidebar-update-chip"
            :class="`is-${entitlementSyncStatusTone}`"
            :title="entitlementSyncStatusTitle"
          >
            {{ entitlementSyncStatusText }}
          </span>
        </div>
        <div v-if="sidebarFooterMetaVisible" class="sidebar-footer-meta">
          <div
            v-if="primaryModChip && !isAdminConsoleSpa()"
            class="sidebar-mods-badges"
            :title="primaryModChip.fullName"
            aria-label="已加载扩展模块"
          >
            <span class="sidebar-mod-chip">{{ primaryModChip.shortLabel }}</span>
          </div>
          <span v-if="sidebarAppVersionText" class="sidebar-version-chip" :title="sidebarAppVersionTitle">
            {{ sidebarAppVersionText }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
/**
 * Facade：侧边栏装配入口（实现拆分至 sidebar/ 子模块与 Sidebar.css，行为与拆分前一致）。
 */
import { TransitionGroup, computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useIndustryStore } from '@/stores/industry'
import { useSidebarLayoutStore } from '@/stores/sidebarLayout'
import { useModsStore } from '@/stores/mods'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import { SETTINGS_MENU_ITEM, sidebarLayoutSeedKeys } from '@/constants/coreMenuCatalog'
import { useVisibleNavItems } from '@/composables/useVisibleNavItems'
import { useImUnreadBadge } from '@/composables/useImUnreadBadge'
import SidebarMenuItem from '@/components/SidebarMenuItem.vue'
import DesktopAppUpdatePrompt from '@/components/DesktopAppUpdatePrompt.vue'
import { useSidebarBrand } from './sidebar/useSidebarBrand'
import { useSidebarAppVersion } from './sidebar/useSidebarAppVersion'
import { useSidebarAdminDeployStatus } from './sidebar/useSidebarAdminDeployStatus'
import { useSidebarEntitlementSync } from './sidebar/useSidebarEntitlementSync'
import { useSidebarMenuReorder } from './sidebar/useSidebarMenuReorder'

const { imUnreadTotal } = useImUnreadBadge()

const props = defineProps({
  activeView: {
    type: String,
    required: true,
  },
})

const emit = defineEmits(['change-view'])

const industryStore = useIndustryStore()
const sidebarLayoutStore = useSidebarLayoutStore()
const modsStore = useModsStore()
const { menuItems, visibleNavItems: _visibleNavItems } = useVisibleNavItems()

const {
  sidebarLogoSrc,
  onSidebarLogoError,
  sidebarBrandTitle,
  sidebarBrandSubtitle,
  primaryModChip,
} = useSidebarBrand()

const {
  shouldShowAdminDeployStatus,
  adminDeployStatusTone,
  adminDeployStatusText,
  adminDeployStatusTitle,
  refreshAdminDeployStatus,
  stopAdminDeployStatusPolling,
  syncAdminDeployStatusPolling,
} = useSidebarAdminDeployStatus()

const { sidebarAppVersionText, sidebarAppVersionTitle, runtimeHealth, startHealthPolling, stopHealthPolling } = useSidebarAppVersion({
  shouldShowAdminDeployStatus,
})

const {
  entitlementSyncStatusTone,
  entitlementSyncStatusText,
  entitlementSyncStatusTitle,
  stopEntitlementSyncPolling,
  syncEntitlementSyncPolling,
  clearEntitlementSyncNoticeTimer,
} = useSidebarEntitlementSync()

const sidebarMenuRef = ref(null)
const expandedKeys = ref(new Set())

const {
  LONG_PRESS_MS,
  pressingKey,
  draggingKey,
  dragOverKey,
  displayMenuItems,
  onReorderPointerDown,
  clearReorderGesture,
} = useSidebarMenuReorder({ sidebarLayoutStore, menuItems, sidebarMenuRef })

const sidebarFooterMetaVisible = computed(
  () => Boolean(sidebarAppVersionText.value) || Boolean(primaryModChip.value && !isAdminConsoleSpa()),
)

const settingsMenuItem = computed(() => {
  const row = _visibleNavItems.value.find((n) => n.key === SETTINGS_MENU_ITEM.key)
  return {
    key: SETTINGS_MENU_ITEM.key,
    name: row?.name || SETTINGS_MENU_ITEM.name,
    iconClass: SETTINGS_MENU_ITEM.iconClass,
    description: SETTINGS_MENU_ITEM.description,
  }
})

const activeParentKeys = computed(() => {
  const view = props.activeView
  const parents = new Set()
  for (const item of menuItems.value) {
    if (item.children?.some((child) => child.key === view)) {
      parents.add(item.key)
    }
  }
  return parents
})

const lastSelectViewAt = new Map()

const selectView = (key) => {
  if (draggingKey.value) return
  const normalized = String(key || '').trim()
  if (!normalized) return
  const now = Date.now()
  const last = lastSelectViewAt.get(normalized) || 0
  if (now - last < 80) return
  lastSelectViewAt.set(normalized, now)
  emit('change-view', normalized)
}

/** 有子菜单的父项：进入父路由（如 other-tools → 员工工作流管理）并展开子菜单 */
const onParentMenuClick = (item) => {
  if (!item.children?.length) {
    selectView(item.key)
    return
  }
  if (!expandedKeys.value.has(item.key)) {
    const next = new Set(expandedKeys.value)
    next.add(item.key)
    expandedKeys.value = next
  }
  selectView(item.key)
}

watch(
  () => props.activeView,
  (viewKey) => {
    if (!viewKey) return
    for (const item of menuItems.value) {
      if (item.children?.length && item.children.some((c) => c.key === viewKey)) {
        if (!expandedKeys.value.has(item.key)) {
          const next = new Set(expandedKeys.value)
          next.add(item.key)
          expandedKeys.value = next
        }
      }
    }
  },
  { immediate: true },
)

function focusMenuItemByKey(targetKey) {
  const root = sidebarMenuRef.value
  if (!root || !targetKey) return
  const btn = root.querySelector(`button.menu-item[data-view="${targetKey}"]`)
  if (btn instanceof HTMLElement) btn.focus()
}

function onMenuItemKeydown(event, key) {
  if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp' && event.key !== 'Home' && event.key !== 'End') {
    return
  }
  const keys = displayMenuItems.value.map((i) => i.key)
  const idx = keys.indexOf(key)
  if (idx < 0) return
  event.preventDefault()
  let nextIdx = idx
  if (event.key === 'ArrowDown') nextIdx = Math.min(keys.length - 1, idx + 1)
  else if (event.key === 'ArrowUp') nextIdx = Math.max(0, idx - 1)
  else if (event.key === 'Home') nextIdx = 0
  else if (event.key === 'End') nextIdx = keys.length - 1
  const nextKey = keys[nextIdx]
  if (nextKey) focusMenuItemByKey(nextKey)
}

onMounted(async () => {
  startHealthPolling()
  window.addEventListener('xcagi:admin-deploy-updated', refreshAdminDeployStatus)
  sidebarLayoutStore.initialize(sidebarLayoutSeedKeys())
  if (!industryStore.isLoaded) {
    try {
      await industryStore.initialize()
    } catch (_e) {
      // ignore initialize failures and keep fallback labels
    }
  }
  if (!modsStore.isLoaded) {
    void modsStore.initialize()
  }
  syncAdminDeployStatusPolling()
  syncEntitlementSyncPolling()
})

onBeforeUnmount(() => {
  stopHealthPolling()
  clearReorderGesture()
  stopAdminDeployStatusPolling()
  stopEntitlementSyncPolling()
  clearEntitlementSyncNoticeTimer()
  window.removeEventListener('xcagi:admin-deploy-updated', refreshAdminDeployStatus)
})
</script>

<style scoped src="./Sidebar.css"></style>
