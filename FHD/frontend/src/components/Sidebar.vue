<template>
  <div class="sidebar">
    <div class="sidebar-header">
      <div class="sidebar-brand" aria-label="品牌与标题">
        <img
          class="sidebar-brand-logo"
          :src="sidebarLogoSrc"
          height="40"
          alt="XC"
          decoding="async"
          @error="onSidebarLogoError"
        />
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
            item.children?.length
              ? (item.children.find((child) => child.key === activeView)?.key ?? '')
              : '',
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
        <div class="status-indicator" :title="systemStatusTitle">
          <span class="status-dot" :class="systemStatusTone"></span>
          <span>{{ systemStatusText }}</span>
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
          <span
            v-if="sidebarAppVersionText"
            class="sidebar-version-chip"
            :title="sidebarAppVersionTitle"
          >
            {{ sidebarAppVersionText }}
          </span>
        </div>
      </div>
      <button
        v-if="clientModeTiersUiEnabled && !isSandboxMode && !isAdminConsoleSpa()"
        class="mode-switch"
        id="modeSwitch"
        type="button"
        aria-label="切换专业模式"
        @click="toggleProMode"
      >
        <span class="mode-label">
          {{ isProMode ? '切换到普通版' : '切换到专业版' }}
        </span>
        <div
          class="toggle-switch"
          id="proModeToggle"
          :class="{ active: isProMode }"
        >
          <div class="toggle-slider"></div>
        </div>
      </button>
      <div v-if="clientModeTiersUiEnabled && !isAdminConsoleSpa()" class="current-mode-text">
        当前：{{ currentModeText }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { TransitionGroup, computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useIndustryStore } from '@/stores/industry'
import { useSidebarLayoutStore } from '@/stores/sidebarLayout'
import { useModsStore } from '@/stores/mods'
import { useAccountProfileStore } from '@/stores/accountProfile'
import {
  ADMIN_OPERATOR_BRAND_SUBTITLE,
  ADMIN_OPERATOR_BRAND_TITLE,
} from '@/constants/adminOperatorNav'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import {
  isClientModeTiersUiEnabled,
  PRO_INTENT_EXPERIENCE_KEY,
} from '@/constants/clientModeTiers'
import { DEFAULT_INDUSTRY_ID } from '@/constants/industryDefaults'
import { getIndustryPreset } from '@/constants/industryPresets'
import { useIndustryUiText } from '@/composables/useIndustryUiText'
import {
  isPlatformShellModeEnabled,
} from '@/constants/platformShellMode'
import { SETTINGS_MENU_ITEM, sidebarLayoutSeedKeys } from '@/constants/coreMenuCatalog'
import { useVisibleNavItems } from '@/composables/useVisibleNavItems'
import { useImUnreadBadge } from '@/composables/useImUnreadBadge'
import { useDesktopRuntimeStatus } from '@/composables/useDesktopRuntimeStatus'
import { primeCsrfCookie } from '@/api/core'
import { xcmaxAdminApi } from '@/api/xcmaxAdmin'
import SidebarMenuItem from '@/components/SidebarMenuItem.vue'
import DesktopAppUpdatePrompt from '@/components/DesktopAppUpdatePrompt.vue'
import './sidebarRuntimeStatus.css'
import packageJson from '../../package.json'

const { imUnreadTotal } = useImUnreadBadge()

const props = defineProps({
  activeView: {
    type: String,
    required: true,
  },
  isProMode: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['change-view', 'toggle-pro-mode'])

const industryStore = useIndustryStore()
const sidebarLayoutStore = useSidebarLayoutStore()
const modsStore = useModsStore()
const accountProfileStore = useAccountProfileStore()
const { modsForUi } = storeToRefs(modsStore)
const { isAdminAccount, displayBrand } = storeToRefs(accountProfileStore)
const { menuItems, visibleNavItems: _visibleNavItems } = useVisibleNavItems()
const { assistantSubtitle } = useIndustryUiText()

function shortModLabel(name) {
  const s = String(name || '').trim()
  if (!s) return 'Mod'
  return s.length > 8 ? `${s.slice(0, 7)}…` : s
}

const loadedModChips = computed(() =>
  (modsForUi.value || []).map((m) => ({
    id: m.id,
    shortLabel: shortModLabel((m.name && String(m.name).trim()) || m.id),
    fullName: (m.name && String(m.name).trim()) || m.id,
  })),
)

const primaryModChip = computed(() => {
  const chips = loadedModChips.value
  return chips.length > 0 ? chips[0] : null
})

const clientModeTiersUiEnabled = isClientModeTiersUiEnabled()
const proIntentExperienceEnabled = ref(localStorage.getItem(PRO_INTENT_EXPERIENCE_KEY) === '1')
const LONG_PRESS_MS = 1000
const sidebarMenuRef = ref(null)
const pressingKey = ref('')
const draggingKey = ref('')
const dragOverKey = ref('')
const expandedKeys = ref(new Set())
const adminDeployStatus = ref(null)
const adminDeployStatusError = ref('')
const adminDeployStatusLoading = ref(false)
const entitlementSyncStatus = ref(null)
const entitlementSyncStatusError = ref('')
const entitlementSyncLoading = ref(false)
const entitlementSyncNoticeUntil = ref(0)
let activeReorderPointerId = null
let pressTimer = null
let boundWindowPointerMove = null
let boundWindowPointerUp = null
let boundWindowPointerCancel = null
let dragMoveRaf = 0
let pendingDragPoint = null
let adminDeployPollTimer = null
let entitlementSyncPollTimer = null
let entitlementSyncNoticeTimer = null
/** @type {{ key: string, midY: number }[]} */
let menuHitCache = []

const isSandboxMode = new URLSearchParams(window.location.search).has('sandbox')
const isPlatformShellMode = isPlatformShellModeEnabled()

function startupAsset(fileName) {
  const base = String(import.meta.env.BASE_URL || '/')
  return `${base}startup/${fileName}`.replace(/([^:]\/)\/+/g, '$1')
}

/** 与开屏 / 登录同源：带 XC 字标；PNG 透明底，JPG 作兜底 */
const brandLogoCandidates = [
  startupAsset('xc-logo-text.png'),
  startupAsset('xc-logo-text.jpg'),
  startupAsset('xc-logo-base.jpg'),
]
const sidebarLogoSrc = ref(brandLogoCandidates[0])
let brandLogoFallbackIndex = 0

function onSidebarLogoError() {
  brandLogoFallbackIndex += 1
  if (brandLogoFallbackIndex < brandLogoCandidates.length) {
    sidebarLogoSrc.value = brandLogoCandidates[brandLogoFallbackIndex]
    return
  }
  if (sidebarLogoSrc.value !== `${import.meta.env.BASE_URL}vite.svg`) {
    sidebarLogoSrc.value = `${import.meta.env.BASE_URL}vite.svg`
  }
}
const sidebarSystemSubtitle = assistantSubtitle

const sidebarBrandTitle = computed(() => {
  if (isAdminConsoleSpa() && isAdminAccount.value) return ADMIN_OPERATOR_BRAND_TITLE
  if (isSandboxMode) return '沙箱测试'
  if (isPlatformShellMode) return 'XCAGI 平台壳'
  const id = String(industryStore.currentIndustryId || DEFAULT_INDUSTRY_ID).trim() || DEFAULT_INDUSTRY_ID
  const name = getIndustryPreset(id).name
  return name.includes('助手') ? name : `${name}助手`
})

const sidebarBrandSubtitle = computed(() => {
  if (isAdminConsoleSpa() && isAdminAccount.value) return ADMIN_OPERATOR_BRAND_SUBTITLE
  if (isSandboxMode) return 'MODstore 在线测试'
  if (isPlatformShellMode) return '通用宿主 · 能力由 Mod 提供'
  const brand = String(displayBrand.value || '').trim()
  if (brand) return brand
  return sidebarSystemSubtitle.value
})

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

const displayMenuItems = computed(() => {
  const items = menuItems.value
  const drag = draggingKey.value
  const over = dragOverKey.value
  if (!drag || !over || drag === over) return items
  const keys = items.map((m) => m.key)
  const from = keys.indexOf(drag)
  const to = keys.indexOf(over)
  if (from < 0 || to < 0) return items
  const nextKeys = [...keys]
  const [lifted] = nextKeys.splice(from, 1)
  nextKeys.splice(to, 0, lifted)
  const byKey = new Map(items.map((m) => [m.key, m]))
  return nextKeys.map((k) => byKey.get(k)).filter(Boolean)
})

const currentModeText = computed(() => {
  if (props.isProMode) {
    return '专业版（增强执行）'
  }
  if (proIntentExperienceEnabled.value) {
    return '普通版（专业意图体验）'
  }
  return '普通版（标准对话）'
})

const shouldShowAdminDeployStatus = computed(() => isAdminConsoleSpa() && isAdminAccount.value)
const shouldShowEntitlementSyncStatus = computed(() => {
  if (isAdminConsoleSpa()) return false
  if (!accountProfileStore.loaded) return false
  return Boolean(accountProfileStore.marketUserId || displayBrand.value)
})

const {
  sidebarAppVersionText, sidebarAppVersionTitle, systemStatusTone,
  systemStatusText, systemStatusTitle, startSystemStatusPolling, stopSystemStatusPolling,
} = useDesktopRuntimeStatus({
  shouldHideVersion: shouldShowAdminDeployStatus,
  fallbackVersion: packageJson.version,
  displayVersion,
})

const sidebarFooterMetaVisible = computed(
  () =>
    Boolean(sidebarAppVersionText.value) ||
    Boolean(primaryModChip.value && !isAdminConsoleSpa()),
)

function displayVersion(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  return text.toLowerCase().startsWith('v') ? text : `v${text}`
}

const adminDeployDisplayVersion = computed(() =>
  displayVersion(
    adminDeployStatus.value?.update_hub?.version ||
      adminDeployStatus.value?.admin_local?.version ||
      '',
  ),
)

const adminDeployStatusTone = computed(() => {
  if (adminDeployStatusError.value) return 'error'
  const flags = adminDeployStatus.value?.flags || {}
  if (flags.needs_push || flags.needs_pack) return 'warn'
  if (flags.enterprise_pending) return 'info'
  if (flags.up_to_date) return 'ok'
  return 'muted'
})

const adminDeployStatusText = computed(() => {
  if (!shouldShowAdminDeployStatus.value) return ''
  if (adminDeployStatusLoading.value && !adminDeployStatus.value) return '版本检测中'
  if (adminDeployStatusError.value) return '版本未知'
  const flags = adminDeployStatus.value?.flags || {}
  const version = adminDeployDisplayVersion.value
  if (flags.enterprise_pending) return `新版本 ${version || ''} 已推送`.trim()
  if (flags.needs_push || flags.needs_pack) return `${version || '新版本'} 待推送`
  if (flags.up_to_date) return `${version || '当前版本'} 最新`
  return version || ''
})

const adminDeployStatusTitle = computed(() => {
  if (adminDeployStatusError.value) return adminDeployStatusError.value
  const hub = adminDeployStatus.value?.update_hub || {}
  const local = adminDeployStatus.value?.admin_local || {}
  return [
    local.version ? `管理端 ${displayVersion(local.version)}` : '',
    hub.version ? `update 站 ${displayVersion(hub.version)}` : '',
    hub.git_sha ? `Git ${String(hub.git_sha).slice(0, 12)}` : '',
  ].filter(Boolean).join(' · ')
})

const entitlementSyncHasFreshNotice = computed(() => entitlementSyncNoticeUntil.value > Date.now())

const entitlementSyncStatusTone = computed(() => {
  if (entitlementSyncStatusError.value) return 'error'
  if (entitlementSyncLoading.value && !entitlementSyncStatus.value) return 'muted'
  if (entitlementSyncHasFreshNotice.value) return 'info'
  if (entitlementSyncStatus.value?.has_snapshot) return 'ok'
  return 'muted'
})

const entitlementSyncStatusText = computed(() => {
  if (!shouldShowEntitlementSyncStatus.value) return ''
  if (entitlementSyncStatusError.value) return '权益未同步'
  if (entitlementSyncLoading.value && !entitlementSyncStatus.value) return '权益同步中'
  if (entitlementSyncHasFreshNotice.value) return '权益已更新'
  if (entitlementSyncStatus.value?.has_snapshot) return '权益已同步'
  return ''
})

const entitlementSyncStatusTitle = computed(() => {
  if (entitlementSyncStatusError.value) return entitlementSyncStatusError.value
  const snap = entitlementSyncStatus.value?.snapshot || {}
  const profile = snap.profile || {}
  const mods = Array.isArray(snap.mod_ids) ? snap.mod_ids.join('、') : ''
  return [
    snap.username ? `账号 ${snap.username}` : '',
    profile.tier ? `等级 ${profile.tier}` : '',
    profile.industry_id ? `行业 ${profile.industry_id}` : '',
    mods ? `Mod ${mods}` : '',
  ].filter(Boolean).join(' · ')
})

function entitlementSyncStorageKey() {
  const accountKey =
    accountProfileStore.marketUserId ||
    accountProfileStore.impersonatingMarketUserId ||
    displayBrand.value ||
    'current'
  return `xcagi_entitlements_seen_${accountKey}`
}

function accountEntitlementSignature() {
  return JSON.stringify({
    kind: accountProfileStore.accountKind || '',
    brand: displayBrand.value || '',
    marketUserId: accountProfileStore.marketUserId || '',
    tier: accountProfileStore.tier || '',
    accountTier: accountProfileStore.accountTier || '',
    budgetRange: accountProfileStore.budgetRange || '',
    membership: accountProfileStore.marketMembershipTier || '',
    industries: accountProfileStore.entitledIndustries || [],
  })
}

function fallbackEntitlementSyncStatus(updatedAtMs = 0) {
  return {
    has_snapshot: true,
    updated_at_ms: updatedAtMs,
    account: {
      market_user_id: accountProfileStore.marketUserId,
      username: displayBrand.value || '',
      account_kind: accountProfileStore.accountKind,
      market_is_enterprise: accountProfileStore.marketIsEnterprise,
      market_is_admin: accountProfileStore.marketIsAdmin,
    },
    snapshot: {
      market_user_id:
        accountProfileStore.marketUserId == null ? '' : String(accountProfileStore.marketUserId),
      username: displayBrand.value || '',
      is_admin: accountProfileStore.marketIsAdmin,
      is_enterprise: accountProfileStore.marketIsEnterprise,
      profile: {
        tier: accountProfileStore.tier || accountProfileStore.accountKind || '',
        account_tier: accountProfileStore.accountTier || '',
        budget_range: accountProfileStore.budgetRange || '',
        industry_id: (accountProfileStore.entitledIndustries || [])[0] || '',
        entitled_industries: accountProfileStore.entitledIndustries || [],
      },
      mod_ids: (modsForUi.value || []).map((m) => String(m.id || '')).filter(Boolean),
      meta: {
        updated_at_ms: updatedAtMs,
        target: 'account_profile',
        push_mode: 'pull_fallback',
      },
    },
  }
}

function markEntitlementSyncNotice(updatedAtMs) {
  if (!updatedAtMs) return
  const isFresh = Math.abs(Date.now() - updatedAtMs) <= 24 * 60 * 60 * 1000
  try {
    localStorage.setItem(entitlementSyncStorageKey(), String(updatedAtMs))
  } catch {
    /* ignore storage failures */
  }
  if (!isFresh) return
  entitlementSyncNoticeUntil.value = Date.now() + 45_000
  if (entitlementSyncNoticeTimer != null) {
    window.clearTimeout(entitlementSyncNoticeTimer)
  }
  entitlementSyncNoticeTimer = window.setTimeout(() => {
    entitlementSyncNoticeUntil.value = 0
    entitlementSyncNoticeTimer = null
  }, 45_000)
}

const syncProIntentExperience = () => {
  proIntentExperienceEnabled.value = localStorage.getItem(PRO_INTENT_EXPERIENCE_KEY) === '1'
}

async function refreshAdminDeployStatus() {
  if (!shouldShowAdminDeployStatus.value || adminDeployStatusLoading.value) return
  adminDeployStatusLoading.value = true
  adminDeployStatusError.value = ''
  try {
    const res = await xcmaxAdminApi.checkDeployUpdates('stable')
    adminDeployStatus.value = res?.data || null
    if (!adminDeployStatus.value) throw new Error(res?.message || '版本检测失败')
  } catch (e) {
    adminDeployStatus.value = null
    adminDeployStatusError.value = e instanceof Error ? e.message : String(e || '版本检测失败')
  } finally {
    adminDeployStatusLoading.value = false
  }
}

function stopAdminDeployStatusPolling() {
  if (adminDeployPollTimer != null) {
    window.clearInterval(adminDeployPollTimer)
    adminDeployPollTimer = null
  }
}

function startAdminDeployStatusPolling() {
  if (!shouldShowAdminDeployStatus.value || adminDeployPollTimer != null) return
  void refreshAdminDeployStatus()
  adminDeployPollTimer = window.setInterval(() => {
    void refreshAdminDeployStatus()
  }, 180000)
}

function syncAdminDeployStatusPolling() {
  if (shouldShowAdminDeployStatus.value) {
    startAdminDeployStatusPolling()
  } else {
    stopAdminDeployStatusPolling()
    adminDeployStatus.value = null
    adminDeployStatusError.value = ''
  }
}

async function refreshEntitlementSyncStatus(options = {}) {
  if (!shouldShowEntitlementSyncStatus.value || entitlementSyncLoading.value) return
  entitlementSyncLoading.value = true
  entitlementSyncStatusError.value = ''
  const beforeSignature = accountEntitlementSignature()
  try {
    if (options.pull) {
      await primeCsrfCookie()
      await xcmaxAdminApi.pullSync()
      await accountProfileStore.refreshFromServer()
    }
    let statusData = null
    try {
      const res = await xcmaxAdminApi.getCurrentEntitlementsSyncStatus()
      statusData = res?.data || null
    } catch {
      const afterSignature = accountEntitlementSignature()
      const changedAtMs =
        beforeSignature && afterSignature && beforeSignature !== afterSignature ? Date.now() : 0
      statusData = fallbackEntitlementSyncStatus(changedAtMs)
      if (changedAtMs > 0) {
        markEntitlementSyncNotice(changedAtMs)
        window.dispatchEvent(
          new CustomEvent('xcagi:account-entitlements-updated', {
            detail: { updated_at_ms: changedAtMs, snapshot: statusData.snapshot },
          }),
        )
      }
    }
    entitlementSyncStatus.value = statusData
    const updatedAtMs = Number(statusData?.updated_at_ms || 0)
    if (updatedAtMs > 0) {
      let seen = ''
      try {
        seen = localStorage.getItem(entitlementSyncStorageKey()) || ''
      } catch {
        seen = ''
      }
      if (String(updatedAtMs) !== seen) {
        markEntitlementSyncNotice(updatedAtMs)
        window.dispatchEvent(
          new CustomEvent('xcagi:account-entitlements-updated', {
            detail: { updated_at_ms: updatedAtMs, snapshot: statusData?.snapshot || null },
          }),
        )
      }
    }
  } catch (e) {
    entitlementSyncStatusError.value =
      e instanceof Error ? e.message : String(e || '权益同步失败')
  } finally {
    entitlementSyncLoading.value = false
  }
}

function stopEntitlementSyncPolling() {
  if (entitlementSyncPollTimer != null) {
    window.clearInterval(entitlementSyncPollTimer)
    entitlementSyncPollTimer = null
  }
}

function startEntitlementSyncPolling() {
  if (!shouldShowEntitlementSyncStatus.value || entitlementSyncPollTimer != null) return
  // 权益快照由服务器主动推送到本机；侧边栏轮询只读本地快照。
  // 旧逻辑每 30 秒强制访问远端同步端口，离线部署会持续产生连接失败日志，
  // 同时把“本地状态读取”错误地变成了外网依赖。
  void refreshEntitlementSyncStatus()
  entitlementSyncPollTimer = window.setInterval(() => {
    void refreshEntitlementSyncStatus()
  }, 30_000)
}

function syncEntitlementSyncPolling() {
  if (shouldShowEntitlementSyncStatus.value) {
    startEntitlementSyncPolling()
  } else {
    stopEntitlementSyncPolling()
    entitlementSyncStatus.value = null
    entitlementSyncStatusError.value = ''
    entitlementSyncNoticeUntil.value = 0
  }
}

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

watch(() => props.activeView, (viewKey) => {
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
}, { immediate: true })

watch(shouldShowAdminDeployStatus, () => {
  syncAdminDeployStatusPolling()
})

watch(shouldShowEntitlementSyncStatus, () => {
  syncEntitlementSyncPolling()
})

const toggleProMode = () => {
  emit('toggle-pro-mode')
}

function clearPressTimer() {
  if (pressTimer) {
    window.clearTimeout(pressTimer)
    pressTimer = null
  }
}

function focusMenuItemByKey(targetKey) {
  const root = sidebarMenuRef.value
  if (!root || !targetKey) return
  const btn = root.querySelector(`button.menu-item[data-view="${targetKey}"]`)
  if (btn instanceof HTMLElement) btn.focus()
}

function onMenuItemKeydown(event, key) {
  if (
    event.key !== 'ArrowDown' &&
    event.key !== 'ArrowUp' &&
    event.key !== 'Home' &&
    event.key !== 'End'
  ) {
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

function refreshMenuHitCache() {
  const root = sidebarMenuRef.value
  if (!root) {
    menuHitCache = []
    return
  }
  menuHitCache = Array.from(root.querySelectorAll('button.menu-item[data-view]'))
    .filter((btn) => btn.getAttribute('data-view') !== draggingKey.value)
    .map((btn) => {
      const rect = btn.getBoundingClientRect()
      return {
        key: String(btn.getAttribute('data-view') || ''),
        midY: rect.top + rect.height / 2,
      }
    })
}

function menuKeyUnderPoint(clientX, clientY) {
  const root = sidebarMenuRef.value
  if (!root) return ''
  const rect = root.getBoundingClientRect()
  if (
    clientX < rect.left ||
    clientX > rect.right ||
    clientY < rect.top ||
    clientY > rect.bottom
  ) {
    return ''
  }
  if (!menuHitCache.length) refreshMenuHitCache()
  let nearestKey = ''
  let nearestDistance = Number.POSITIVE_INFINITY
  for (const entry of menuHitCache) {
    const distance = Math.abs(entry.midY - clientY)
    if (distance < nearestDistance) {
      nearestDistance = distance
      nearestKey = entry.key
    }
  }
  return nearestKey
}

function clearDragMoveRaf() {
  if (dragMoveRaf) {
    window.cancelAnimationFrame(dragMoveRaf)
    dragMoveRaf = 0
  }
  pendingDragPoint = null
}

function detachReorderWindowListeners() {
  if (boundWindowPointerMove) {
    window.removeEventListener('pointermove', boundWindowPointerMove, true)
    boundWindowPointerMove = null
  }
  if (boundWindowPointerUp) {
    window.removeEventListener('pointerup', boundWindowPointerUp, true)
    boundWindowPointerUp = null
  }
  if (boundWindowPointerCancel) {
    window.removeEventListener('pointercancel', boundWindowPointerCancel, true)
    boundWindowPointerCancel = null
  }
}

function clearReorderGesture() {
  clearPressTimer()
  pressingKey.value = ''
  draggingKey.value = ''
  dragOverKey.value = ''
  activeReorderPointerId = null
  menuHitCache = []
  clearDragMoveRaf()
  detachReorderWindowListeners()
}

function flushDragMove() {
  dragMoveRaf = 0
  if (!pendingDragPoint || !draggingKey.value) {
    pendingDragPoint = null
    return
  }
  const { x, y } = pendingDragPoint
  pendingDragPoint = null
  const key = menuKeyUnderPoint(x, y)
  if (key && key !== dragOverKey.value) {
    dragOverKey.value = key
    refreshMenuHitCache()
  }
}

function onWindowPointerMove(event) {
  if (activeReorderPointerId !== null && event.pointerId !== activeReorderPointerId) return
  if (!draggingKey.value) return
  pendingDragPoint = { x: event.clientX, y: event.clientY }
  if (!dragMoveRaf) {
    dragMoveRaf = window.requestAnimationFrame(flushDragMove)
  }
}

function onWindowPointerUp(event) {
  if (activeReorderPointerId !== null && event.pointerId !== activeReorderPointerId) return
  if (draggingKey.value) {
    const from = draggingKey.value
    const to = dragOverKey.value
    if (to && to !== from) {
      sidebarLayoutStore.moveItem(from, to, menuItems.value.map((m) => m.key))
    }
  }
  clearReorderGesture()
}

function attachReorderWindowListeners() {
  detachReorderWindowListeners()
  boundWindowPointerMove = onWindowPointerMove
  boundWindowPointerUp = onWindowPointerUp
  boundWindowPointerCancel = clearReorderGesture
  window.addEventListener('pointermove', boundWindowPointerMove, true)
  window.addEventListener('pointerup', boundWindowPointerUp, true)
  window.addEventListener('pointercancel', boundWindowPointerCancel, true)
}

function onReorderPointerDown(event, key) {
  if (!sidebarLayoutStore.reorderEnabled) return
  if (event.button !== 2) return
  event.preventDefault()
  clearReorderGesture()
  activeReorderPointerId = event.pointerId
  pressingKey.value = key
  attachReorderWindowListeners()
  pressTimer = window.setTimeout(() => {
    if (activeReorderPointerId !== event.pointerId || pressingKey.value !== key) return
    pressingKey.value = ''
    draggingKey.value = key
    dragOverKey.value = key
    refreshMenuHitCache()
  }, LONG_PRESS_MS)
}

watch(draggingKey, (key) => {
  if (key) {
    window.requestAnimationFrame(() => refreshMenuHitCache())
  } else {
    menuHitCache = []
  }
})

onMounted(async () => {
  window.addEventListener('storage', syncProIntentExperience)
  window.addEventListener('xcagi:pro-intent-experience-changed', syncProIntentExperience)
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
  startSystemStatusPolling()
})

onBeforeUnmount(() => {
  clearReorderGesture()
  stopAdminDeployStatusPolling()
  stopEntitlementSyncPolling()
  stopSystemStatusPolling()
  if (entitlementSyncNoticeTimer != null) {
    window.clearTimeout(entitlementSyncNoticeTimer)
    entitlementSyncNoticeTimer = null
  }
  window.removeEventListener('storage', syncProIntentExperience)
  window.removeEventListener('xcagi:pro-intent-experience-changed', syncProIntentExperience)
  window.removeEventListener('xcagi:admin-deploy-updated', refreshAdminDeployStatus)
})
</script>

<style scoped>
.sidebar-status-mods-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 6px 8px;
  margin-bottom: 10px;
}

.sidebar-status-mods-row .status-indicator {
  margin-bottom: 0;
  flex-shrink: 0;
  min-width: 0;
}

.sidebar-update-chip {
  display: inline-flex;
  align-items: center;
  max-width: 132px;
  margin-left: 6px;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 10px;
  line-height: 1.35;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: middle;
  border: 1px solid transparent;
}

.sidebar-update-chip.is-ok {
  color: #047857;
  background: #d1fae5;
  border-color: #a7f3d0;
}

.sidebar-update-chip.is-info {
  color: #1d4ed8;
  background: #dbeafe;
  border-color: #bfdbfe;
}

.sidebar-update-chip.is-warn {
  color: #b45309;
  background: #fef3c7;
  border-color: #fde68a;
}

.sidebar-update-chip.is-error {
  color: #b91c1c;
  background: #fee2e2;
  border-color: #fecaca;
}

.sidebar-update-chip.is-muted {
  color: #475569;
  background: #e2e8f0;
  border-color: #cbd5e1;
}

.sidebar-mods-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  justify-content: flex-end;
  min-width: 0;
  max-width: 100%;
}

.sidebar-footer-meta {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 4px 6px;
  min-width: 0;
  margin-left: auto;
}

.sidebar-version-chip {
  display: inline-flex;
  align-items: center;
  max-width: 88px;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 10px;
  line-height: 1.35;
  font-weight: 700;
  white-space: nowrap;
  color: #475569;
  background: #e2e8f0;
  border: 1px solid #cbd5e1;
}

.sidebar-mod-chip {
  display: inline-block;
  max-width: 100%;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 10px;
  line-height: 1.35;
  font-weight: 600;
  color: #3730a3;
  background: #e0e7ff;
  border: 1px solid #c7d2fe;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sidebar-menu-shift-wrap {
  display: flex;
  flex-direction: column;
  width: 100%;
}

.sidebar-menu-bottom {
  flex-shrink: 0;
  width: 100%;
  padding: 8px 10px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  box-sizing: border-box;
}

.sidebar-menu.reorder-enabled :deep(.menu-item.pressing) {
  background: rgba(125, 211, 252, 0.1);
}

.sidebar-menu.reorder-enabled.is-dragging :deep(.menu-item.dragging) {
  opacity: 0.5;
}

.sidebar-menu.reorder-enabled.is-dragging .sidebar-menu-shift-move {
  transition: transform 0.26s cubic-bezier(0.22, 1, 0.36, 1) !important;
}
</style>
