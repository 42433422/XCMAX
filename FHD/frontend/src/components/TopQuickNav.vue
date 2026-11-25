<template>
  <button type="button" class="top-quick-nav__narrow-trigger" aria-label="打开全局搜索"
    aria-haspopup="dialog" :aria-expanded="paletteOpen ? 'true' : 'false'" @click="openCommandPalette">
    <i class="fa fa-search" aria-hidden="true"></i>
  </button>
  <Teleport to="body">
    <div v-if="paletteOpen" class="top-quick-nav__scrim" @mousedown.prevent="closeAndRestore" />
  </Teleport>
  <Teleport to="body" :disabled="!paletteOpen">
  <div ref="paletteRootRef" class="top-quick-nav" :class="{ 'top-quick-nav--palette': paletteOpen }"
    :role="paletteOpen ? 'dialog' : undefined" :aria-modal="paletteOpen ? 'true' : undefined"
    :aria-label="paletteOpen ? (desktopEnabled ? '工作空间命令面板' : '全局搜索') : undefined"
    @keydown="onPaletteKeydown">
    <i class="fa fa-search top-quick-nav__icon" aria-hidden="true"></i>
    <input
      ref="inputRef"
      v-model="query"
      class="top-quick-nav__input"
      type="text"
      role="combobox"
      :aria-expanded="open ? 'true' : 'false'"
      aria-controls="top-quick-nav-list"
      :aria-activedescendant="open && filtered.length ? `top-quick-nav-option-${highlightIndex}` : undefined"
      :aria-keyshortcuts="desktopEnabled ? shortcutLabel : undefined"
      aria-label="搜索页面、任务、客户、员工与业务入口"
      placeholder="搜索页面、任务、客户、员工或命令"
      autocomplete="off"
      @focus="onFocus"
      @keydown="onKeydown"
      @blur="onBlur"
    />
    <Teleport to="body" :disabled="paletteOpen">
      <ul
        v-if="open"
        id="top-quick-nav-list"
        class="top-quick-nav__list"
        role="listbox"
        aria-label="功能列表"
        :style="listStyle"
      >
        <li v-if="!filtered.length" class="top-quick-nav__empty">没有匹配的页面或记录</li>
        <li
          v-for="(item, idx) in filtered"
          :key="`${item.kind}-${item.key || item.id}-${idx}`"
          :id="`top-quick-nav-option-${idx}`"
          class="top-quick-nav__option"
          :class="{ highlighted: idx === highlightIndex }"
          role="option"
          :aria-selected="idx === highlightIndex ? 'true' : 'false'"
          @mouseenter="highlightIndex = idx"
          @mousedown.prevent="choose(item)"
        >
          <i
            v-if="item.iconClass || KIND_ICONS[item.kind]"
            class="fa top-quick-nav__option-icon"
            :class="item.iconClass || KIND_ICONS[item.kind]"
            aria-hidden="true"
          ></i>
          <span v-if="item.kind !== 'nav'" class="top-quick-nav__kind">{{ KIND_LABELS[item.kind] || '' }}</span>
          <span class="top-quick-nav__option-name">{{ item.name }}</span>
          <span v-if="item.kind === 'nav' && preferences.favorites.includes(item.key)" class="top-quick-nav__star" aria-label="常用">★</span>
        </li>
      </ul>
    </Teleport>
    <div v-if="paletteOpen" class="top-quick-nav__footer">
      <button v-if="desktopEnabled" type="button" :disabled="filtered[highlightIndex]?.kind !== 'nav'"
        @click="toggleFavoriteHighlighted">
        {{ preferences.favorites.includes(filtered[highlightIndex]?.key) ? '取消常用' : '设为常用' }}
      </button>
      <button v-if="desktopEnabled" type="button" :aria-expanded="shortcutsVisible" @click="shortcutsVisible = !shortcutsVisible">快捷键设置</button>
      <button type="button" @click="closeAndRestore">Esc 关闭</button>
    </div>
    <section v-if="paletteOpen && shortcutsVisible" class="top-quick-nav__settings" aria-label="自定义快捷键">
      <label v-for="action in WORKSPACE_COMMANDS" :key="action.id">
        <span>{{ action.label }}</span>
        <select :aria-label="`${action.label}快捷键`" :value="preferences.shortcuts[action.id]"
          @change="setCommandShortcut(action.id, $event)">
          <option v-for="chord in WORKSPACE_SHORTCUT_CHOICES" :key="chord" :value="chord">
            {{ shortcutForDisplay(chord) }}
          </option>
        </select>
      </label>
      <p v-if="shortcutError" role="alert">{{ shortcutError }}</p>
      <button type="button" @click="resetCommandShortcuts">恢复默认快捷键</button>
    </section>
  </div>
  </Teleport>
</template>

<script setup>
/**
 * 顶部中间快捷跳转框：输入功能名即搜全部侧边栏入口（与 Sidebar 同源 useVisibleNavItems），
 * 回车/点击后经 MainLayout 的 navigateToView 跳转（与侧栏点击完全同路径）。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import customersApi from '@/api/customers'
import productsApi from '@/api/products'
import ordersApi from '@/api/orders'
import { fetchEmployeeDirectory } from '@/api/employeeDirectory'
import templatePreviewApi from '@/api/templatePreview'
import { useVisibleNavItems } from '@/composables/useVisibleNavItems'
import { useModsStore } from '@/stores/mods'
import { pushErpPage } from '@/utils/erpPagePaths'
import { productReadScopeKey } from '@/utils/productReadAccountScope'
import { isDesktopShell } from '@/utils/desktopShell'
import { useAgentTaskCenterStore } from '@/stores/agentTaskCenter'
import {
  WORKSPACE_COMMANDS, WORKSPACE_SHORTCUT_CHOICES, workspaceCommandForKey,
  workspaceCommandStorageKey, readWorkspaceCommandPreferences, writeWorkspaceCommandPreferences,
  defaultWorkspaceShortcuts, validateWorkspaceShortcut, nextRecentNavKeys,
} from '@/utils/workspaceCommandShortcuts'

const emit = defineEmits(['select', 'command'])
const router = useRouter()

/** 与模板库约定的交接键：跳转前写入关键词，模板库挂载后读取。 */
const TEMPLATE_SEARCH_STORAGE_KEY = 'xcagi_template_search_keyword'
const TEMPLATE_NAV_KEY = 'template-preview'
const KIND_LABELS = { product: '产品', customer: '客户', order: '订单', employee: '员工', template: '模板', task: '任务', action: '业务入口', command: '命令' }
const KIND_ICONS = { product: 'fa-cube', customer: 'fa-user-o', order: 'fa-file-text-o', employee: 'fa-id-badge', template: 'fa-file-o', task: 'fa-tasks', action: 'fa-shield', command: 'fa-keyboard-o' }

const { visibleNavItems } = useVisibleNavItems()
const modsStore = useModsStore()
const recordScope = computed(() => productReadScopeKey(String(modsStore.activeModId || '')))

const desktopEnabled = isDesktopShell()
const macPlatform = window.xcagiDesktop?.platform === 'darwin' ||
  (typeof navigator !== 'undefined' && /Mac/i.test(navigator.platform || ''))
const shortcutLabel = computed(() => preferences.value.shortcuts.palette.replace('Mod', macPlatform ? 'Meta' : 'Control'))
const storageKey = ref('')
const preferences = ref(readWorkspaceCommandPreferences(''))
const recentKeys = computed(() => preferences.value.recent)
const paletteOpen = ref(false)
const shortcutsVisible = ref(false)
const shortcutError = ref('')
const paletteRootRef = ref(null)
let taskStore = null
// The top navigation is also mounted in isolated component tests without Pinia.
try { taskStore = useAgentTaskCenterStore() } catch { /* no task store in standalone mounts */ }
const authorizedActionLinks = [
  { id: 'create-order', name: '发起业务单据（保留原审批）', key: 'orders-create' },
  { id: 'review-approvals', name: '查看待审批业务（保留原授权）', key: 'approval-hub' },
]
let restoreTarget = null
let blurTimer = null
let unregisterNativeCommand = null

const query = ref('')
const open = ref(false)
const highlightIndex = ref(0)
const keyboardMoved = ref(false)
const inputRef = ref(null)
const records = ref([])
const recordNavKeys = { product: 'products', customer: 'customers', order: 'orders', template: TEMPLATE_NAV_KEY, employee: 'employee-workflow' }
const searchPermissionKey = computed(() => Object.values(recordNavKeys).filter(canNavigateToBusinessKey).join('|'))
const commandOptions = computed(() => desktopEnabled ? WORKSPACE_COMMANDS
  .filter((item) => item.id !== 'palette')
  .filter((item) => !['chat', 'new-chat', 'new-task', 'sessions'].includes(item.id) || visibleNavItems.value.some((nav) => nav.key === 'chat'))
  .map((item) => ({ kind: 'command', id: item.id, name: item.label })) : [])
const listStyle = ref({ position: 'fixed', top: '0px', left: '0px', width: '420px', zIndex: 4000 })
let recordTimer = null
let recordGeneration = 0

const filtered = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  const items = (visibleNavItems.value || []).map((item) => ({ ...item, kind: 'nav' }))
  const nav = keyword
    ? items.filter((item) => `${item.name || ''} ${item.key || ''} ${item.routeName || ''}`.toLowerCase().includes(keyword))
    : items
  const actionLinks = desktopEnabled ? authorizedActionLinks
    .filter((action) => (visibleNavItems.value || []).some((nav) => nav.key === action.key))
    .map((action) => ({ ...action, kind: 'action' })) : []
  const taskItems = (desktopEnabled || keyword) && taskStore && taskStore.stale !== true
    ? taskStore.tasks.filter((task) => !task.archived_at)
      .filter((task) => !keyword || `${task.title} ${task.task_id} ${task.status}`.toLowerCase().includes(keyword))
      .slice(0, 12).map((task) => ({ kind: 'task', id: task.task_id, name: task.title || task.task_id, task })) : []
  const commands = commandOptions.value.filter((item) => !keyword || `${item.name} ${item.id}`.toLowerCase().includes(keyword))
  const actions = actionLinks.filter((item) => !keyword || `${item.name} ${item.id}`.toLowerCase().includes(keyword))
  if (keyword) return [...nav, ...records.value.filter(record => canNavigateToBusinessKey(recordNavKeys[record.kind])), ...taskItems, ...actions, ...commands]
  if (!desktopEnabled) return nav
  const favorites = new Set(preferences.value.favorites)
  const rank = new Map(recentKeys.value.map((key, index) => [key, index]))
  const orderedNav = [...nav].sort((a, b) => (Number(favorites.has(b.key)) - Number(favorites.has(a.key)))
    || (rank.get(a.key) ?? Infinity) - (rank.get(b.key) ?? Infinity))
  return [...orderedNav, ...taskItems.slice(0, 5), ...actions, ...commands]
})

function recordName(row, keys) {
  return keys.map((key) => String(row?.[key] || '').trim()).filter(Boolean).join(' · ')
}

function canNavigateToBusinessKey(key) {
  return (visibleNavItems.value || []).some((nav) => nav.key === key || nav.parentKey === key)
}

async function lookupRecords(keyword) {
  const generation = ++recordGeneration
  const scope = recordScope.value
  const permissions = searchPermissionKey.value
  const [products, customers, orders, templates, employees] = await Promise.all([
    canNavigateToBusinessKey('products') ? productsApi.searchProducts(keyword).catch(() => null) : null,
    canNavigateToBusinessKey('customers') ? customersApi.getCustomers({ keyword, page: 1, per_page: 8 }).catch(() => null) : null,
    canNavigateToBusinessKey('orders') ? ordersApi.searchOrders(keyword).catch(() => null) : null,
    canNavigateToBusinessKey('template-preview') ? templatePreviewApi.listTemplates().catch(() => null) : null,
    canNavigateToBusinessKey('employee-workflow') ? fetchEmployeeDirectory().catch(() => []) : [],
  ])
  if (generation !== recordGeneration || scope !== recordScope.value || permissions !== searchPermissionKey.value) return
  const productRows = Array.isArray(products?.data) ? products.data : []
  const customerRows = Array.isArray(customers?.data) ? customers.data : []
  const orderRows = Array.isArray(orders?.data) ? orders.data : []
  const templateRows = Array.isArray(templates?.templates) ? templates.templates : []
  const employeeRows = Array.isArray(employees) ? employees : []
  const lowered = keyword.toLowerCase()
  records.value = [
    ...orderRows.slice(0, 8).map((row) => ({
      kind: 'order',
      id: row.order_number || row.id,
      name: recordName(row, ['order_number', 'customer_name']) || '订单',
      keyword: String(row.order_number || keyword),
    })),
    ...productRows.slice(0, 8).map((row) => ({
      kind: 'product',
      id: row.id,
      name: recordName(row, ['model_number', 'name']) || '产品',
      keyword: String(row.model_number || row.name || keyword),
    })),
    ...customerRows.slice(0, 8).map((row) => ({
      kind: 'customer',
      id: row.id,
      name: recordName(row, ['customer_name', 'unit_name', 'name']) || '客户',
      keyword: String(row.customer_name || row.unit_name || row.name || keyword),
    })),
    ...employeeRows
      .filter((row) =>
        [row.label, row.pack_id, row.department]
          .map((value) => String(value || '').toLowerCase())
          .join(' ')
          .includes(lowered),
      )
      .slice(0, 8)
      .map((row) => ({
        kind: 'employee',
        id: row.pack_id,
        name: recordName(row, ['label', 'department']) || '员工',
        navKey: 'employee-workflow',
      })),
    ...templateRows
      .filter((row) =>
        [row.name, row.template_type, row.business_scope, row.category, row.filename]
          .map((value) => String(value || '').toLowerCase())
          .join(' ')
          .includes(lowered),
      )
      .slice(0, 8)
      .map((row) => ({
        kind: 'template',
        id: row.id,
        name: String(row.name || '模板'),
        keyword: String(row.name || keyword),
      })),
  ]
}

function placeList() {
  const el = inputRef.value
  if (!el?.getBoundingClientRect) return
  const rect = el.getBoundingClientRect()
  listStyle.value = paletteOpen.value
    ? { position: 'relative', top: 'auto', left: 'auto', width: '100%', zIndex: 1 }
    : { position: 'fixed', top: `${rect.bottom + 6}px`, left: `${rect.left}px`,
        width: `${rect.width}px`, zIndex: 4000 }
}

function cancelBlur() {
  if (blurTimer !== null) window.clearTimeout(blurTimer)
  blurTimer = null
}

function onFocus() {
  cancelBlur()
  open.value = true
  highlightIndex.value = 0
  keyboardMoved.value = false
  placeList()
  if (query.value.trim() && !records.value.length) scheduleRecordSearch()
  // Use the existing scoped task center read path, never a second polling loop.
  if (taskStore?.stale === true && !taskStore.loading &&
    typeof taskStore.refresh === 'function') void taskStore.refresh()
}

function onViewportChange() {
  if (open.value) placeList()
}

function onBlur() {
  if (paletteOpen.value) return
  // 延迟关闭：让选项的 mousedown（已 preventDefault 不夺焦）先完成选择
  cancelBlur()
  blurTimer = window.setTimeout(() => {
    blurTimer = null
    open.value = false
    restoreTarget = null
    clearRecordSearch()
  }, 180)
}

function clearRecordSearch() {
  if (recordTimer) clearTimeout(recordTimer)
  recordTimer = null
  records.value = []
  recordGeneration += 1
}

watch(recordScope, () => {
  clearRecordSearch()
  cancelBlur()
  const nextKey = workspaceCommandStorageKey()
  storageKey.value = nextKey
  preferences.value = { ...readWorkspaceCommandPreferences(nextKey), recent: [] }
  restoreTarget = null
  paletteOpen.value = false
  shortcutsVisible.value = false
  query.value = ''
  open.value = false
}, { flush: 'sync' })

function scheduleRecordSearch() {
  highlightIndex.value = 0
  keyboardMoved.value = false
  clearRecordSearch()
  const keyword = query.value.trim()
  if (!keyword || !open.value) return
  const generation = recordGeneration
  recordTimer = setTimeout(() => {
    if (generation === recordGeneration) void lookupRecords(keyword)
  }, 250)
}

// A same-account permission change can occur while a search is in flight.
// Invalidate both displayed results and in-flight responses immediately.
watch(searchPermissionKey, scheduleRecordSearch, { flush: 'sync' })
watch(query, scheduleRecordSearch)

watch(() => filtered.value.length, length => {
  if (highlightIndex.value >= length) highlightIndex.value = 0
}, { flush: 'sync' })

watch(highlightIndex, () => {
  void nextTick(() => {
    const node = document.querySelector('#top-quick-nav-list .top-quick-nav__option.highlighted')
    if (node && typeof node.scrollIntoView === 'function') node.scrollIntoView({ block: 'nearest' })
  })
})

function shortcutForDisplay(chord) {
  return chord.replace('Mod', macPlatform ? '⌘' : 'Ctrl').replace('+Alt', macPlatform ? '+Option' : '+Alt')
}

function persistCommands() {
  writeWorkspaceCommandPreferences(storageKey.value, preferences.value)
}

function loadCommands() {
  storageKey.value = workspaceCommandStorageKey()
  preferences.value = readWorkspaceCommandPreferences(storageKey.value)
  shortcutError.value = ''
}

function onWorkspaceNavVisited(event) {
  if (!desktopEnabled) return
  const currentKey = workspaceCommandStorageKey()
  if (currentKey !== storageKey.value) {
    storageKey.value = currentKey
    preferences.value = readWorkspaceCommandPreferences(currentKey)
  }
  const key = String(event?.detail?.key || '')
  if (!(visibleNavItems.value || []).some((nav) => nav.key === key)) return
  const recent = nextRecentNavKeys(preferences.value.recent, key)
  if (recent.join('|') === preferences.value.recent.join('|')) return
  preferences.value = { ...preferences.value, recent }
  persistCommands()
}

function onCommandStorageChange(event) {
  if (storageKey.value && event.key === storageKey.value && event.storageArea === localStorage) {
    preferences.value = readWorkspaceCommandPreferences(storageKey.value)
  }
}

function setCommandShortcut(id, event) {
  const chord = String(event?.target?.value || '')
  const error = validateWorkspaceShortcut(preferences.value.shortcuts, id, chord)
  if (error) {
    shortcutError.value = error
    if (event?.target) event.target.value = preferences.value.shortcuts[id]
    return
  }
  shortcutError.value = ''
  preferences.value = {
    ...preferences.value,
    shortcuts: { ...preferences.value.shortcuts, [id]: chord },
  }
  persistCommands()
}

function resetCommandShortcuts() {
  preferences.value = { ...preferences.value, shortcuts: defaultWorkspaceShortcuts() }
  shortcutError.value = ''
  persistCommands()
}

function toggleFavoriteHighlighted() {
  const item = filtered.value[highlightIndex.value]
  if (item?.kind !== 'nav' || !(visibleNavItems.value || []).some((nav) => nav.key === item.key)) return
  const favorites = preferences.value.favorites.includes(item.key)
    ? preferences.value.favorites.filter((key) => key !== item.key)
    : [item.key, ...preferences.value.favorites].slice(0, 12)
  preferences.value = { ...preferences.value, favorites }
  persistCommands()
}

function closeAndRestore() {
  const target = restoreTarget
  restoreTarget = null
  paletteOpen.value = false
  shortcutsVisible.value = false
  open.value = false
  query.value = ''
  clearRecordSearch()
  inputRef.value?.blur?.()
  cancelBlur()
  if (target instanceof HTMLElement && target.isConnected && !target.closest('[inert]')) {
    void nextTick(() => target.focus({ preventScroll: true }))
  }
}

// Navigation owns its next focus target; do not refocus the page we just left.
function closeAfterNavigation() {
  restoreTarget = null
  closeAndRestore()
}

function openCommandPalette() {
  if (!inputRef.value || inputRef.value.closest('[inert]')) return
  if (!paletteOpen.value) {
    const active = document.activeElement
    restoreTarget = active instanceof HTMLElement && active !== inputRef.value ? active : null
  }
  paletteOpen.value = true
  open.value = true
  shortcutsVisible.value = false
  void nextTick(() => {
    inputRef.value?.focus({ preventScroll: true })
    onFocus()
    inputRef.value?.select()
  })
}

function onPaletteKeydown(event) {
  if (!paletteOpen.value) return
  if (event.isComposing || event.keyCode === 229) return
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    closeAndRestore()
    return
  }
  if (event.key !== 'Tab') return
  const controls = [...(paletteRootRef.value?.querySelectorAll('input,button:not([disabled]),select,[tabindex="0"]') || [])]
    .filter((element) => element.getClientRects().length)
  if (!controls.length) return
  const current = document.activeElement
  const first = controls[0], last = controls[controls.length - 1]
  if (event.shiftKey && current === first) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && current === last) { event.preventDefault(); first.focus() }
}

function onGlobalKeydown(event) {
  if (!desktopEnabled || event.defaultPrevented || event.repeat || event.isComposing || event.keyCode === 229) return
  if (event.getModifierState?.('AltGraph')) return
  const command = workspaceCommandForKey(event, preferences.value.shortcuts, macPlatform)
  if (!command || (command !== 'palette' && !commandOptions.value.some(item => item.id === command))) return
  const active = document.activeElement
  const input = inputRef.value
  if (!input || input.closest('[inert]')) return
  // Never steal shortcuts from modal dialogs or text editors outside our own panel.
  if (active instanceof Element && active.closest('[role="dialog"], [aria-modal="true"]') && !paletteRootRef.value?.contains(active)) return
  if (command !== 'palette' && active instanceof Element && !paletteRootRef.value?.contains(active)
    && active.closest('input, textarea, select, [contenteditable="true"]')) return
  event.preventDefault()
  if (command === 'palette') {
    if (active === input && open.value && paletteOpen.value) return
    openCommandPalette()
    return
  }
  closeAndRestore()
  emit('command', command)
}

function onNativeWorkspaceCommand(command) {
  if (!desktopEnabled || !inputRef.value || inputRef.value.closest('[inert]')) return
  const active = document.activeElement
  if (active instanceof Element && active.closest('[role="dialog"], [aria-modal="true"]') &&
    !paletteRootRef.value?.contains(active)) return
  if (command === 'palette') { openCommandPalette(); return }
  if (commandOptions.value.some(item => item.id === command)) {
    closeAndRestore()
    emit('command', command)
  }
}

onMounted(() => {
  loadCommands()
  if (desktopEnabled && typeof window.xcagiDesktop?.onWorkspaceCommand === 'function') {
    unregisterNativeCommand = window.xcagiDesktop.onWorkspaceCommand(onNativeWorkspaceCommand)
  }
  window.addEventListener('resize', onViewportChange)
  window.addEventListener('scroll', onViewportChange, true)
  window.addEventListener('storage', onCommandStorageChange)
  if (desktopEnabled) window.addEventListener('xcagi:workspace-nav-visited', onWorkspaceNavVisited)
  if (desktopEnabled) window.addEventListener('keydown', onGlobalKeydown)
})

onBeforeUnmount(() => {
  unregisterNativeCommand?.()
  unregisterNativeCommand = null
  window.removeEventListener('resize', onViewportChange)
  window.removeEventListener('scroll', onViewportChange, true)
  window.removeEventListener('storage', onCommandStorageChange)
  window.removeEventListener('xcagi:workspace-nav-visited', onWorkspaceNavVisited)
  window.removeEventListener('keydown', onGlobalKeydown)
  cancelBlur()
  restoreTarget = null
  clearRecordSearch()
})

function choose(item) {
  if (item?.kind === 'command') {
    if (!commandOptions.value.some((command) => command.id === item.id)) return
    closeAndRestore()
    emit('command', item.id)
    return
  }
  if (item?.kind === 'action') {
    if (!authorizedActionLinks.some((action) => action.key === item.key) ||
      !(visibleNavItems.value || []).some((nav) => nav.key === item.key)) return
    closeAfterNavigation()
    emit('select', item.key)
    return
  }
  if (item?.kind === 'task') {
    if (taskStore?.stale === true) return
    const live = taskStore?.tasks.find((task) => task.task_id === item.id && !task.archived_at)
    if (!live) return
    const conversation = String(live.conversation_id || live.workspace_id || live.task_id)
    closeAfterNavigation()
    void router.push({ name: 'task-workspace', params: { taskId: live.task_id }, query: { conversation } })
    return
  }
  if (item?.kind === 'template') {
    if (!records.value.includes(item) || !canNavigateToBusinessKey(TEMPLATE_NAV_KEY)) return
    try {
      sessionStorage.setItem(TEMPLATE_SEARCH_STORAGE_KEY, item.keyword || query.value.trim())
    } catch {
      /* 无 sessionStorage 时退化为不带关键词跳转 */
    }
    // 已在模板库页面时组件不会重新挂载，用事件即时下发关键词。
    window.dispatchEvent(
      new CustomEvent('xcagi:template-search', { detail: { keyword: item.keyword || query.value.trim() } }),
    )
    emit('select', TEMPLATE_NAV_KEY)
    closeAfterNavigation()
    return
  }
  if (item?.kind === 'product' || item?.kind === 'customer' || item?.kind === 'order') {
    if (!records.value.includes(item)) return
    const requiredKey = { product: 'products', customer: 'customers', order: 'orders' }[item.kind]
    if (!canNavigateToBusinessKey(requiredKey)) return
    const pathByKind = { product: '/products', customer: '/customers', order: '/orders' }
    pushErpPage(router, {
      path: pathByKind[item.kind],
      query: {
        keyword: item.keyword || query.value.trim(),
        ...((item.kind === 'product' || item.kind === 'customer') && item.id != null && item.id !== ''
          ? { focus: String(item.id) }
          : {}),
      },
    })
    closeAfterNavigation()
    return
  }
  if (item?.kind === 'employee') {
    if (!records.value.includes(item)) return
    const navKey = item.navKey || 'employee-workflow'
    if (!canNavigateToBusinessKey(navKey)) return
    emit('select', navKey)
    closeAfterNavigation()
    return
  }
  if (!item?.key || !(visibleNavItems.value || []).some((nav) => nav.key === item.key)) return
  // Selection is only an existing sidebar navigation intent, not business execution.
  preferences.value = { ...preferences.value, recent: nextRecentNavKeys(recentKeys.value, item.key) }
  persistCommands()
  closeAfterNavigation()
  emit('select', item.key)
}

function onKeydown(event) {
  if (event.isComposing || event.keyCode === 229) return
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    closeAndRestore()
    return
  }
  if (!open.value) {
    open.value = true
    placeList()
    return
  }
  const total = filtered.value.length
  if (highlightIndex.value >= total) highlightIndex.value = 0
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    if (total) {
      keyboardMoved.value = true
      highlightIndex.value = (highlightIndex.value + 1) % total
    }
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    if (total) {
      keyboardMoved.value = true
      highlightIndex.value = (highlightIndex.value - 1 + total) % total
    }
  } else if (event.key === 'Enter') {
    event.preventDefault()
    if (!query.value.trim() && !keyboardMoved.value) return
    const item = filtered.value[highlightIndex.value]
    if (item) choose(item)
  }
}
</script>

<style scoped>
.top-quick-nav__scrim {
  position: fixed;
  inset: 0;
  z-index: 4500;
  background: rgba(18, 28, 46, 0.34);
  backdrop-filter: blur(3px);
}
.top-quick-nav.top-quick-nav--palette {
  position: fixed;
  z-index: 4601;
  top: min(18vh, 180px);
  top: min(18dvh, 180px);
  max-height: calc(100dvh - min(18dvh, 180px) - 12px);
  overflow-y: auto;
  left: 50%;
  width: min(680px, calc(100vw - 36px));
  transform: translateX(-50%);
  margin: 0;
  padding: 12px 12px 0;
  box-sizing: border-box;
  border: 1px solid var(--el-border-color-light, #d7dfe8);
  border-radius: 16px;
  background: var(--el-bg-color-overlay, #fff);
  box-shadow: 0 28px 70px rgba(13, 21, 39, 0.22);
}
.top-quick-nav--palette .top-quick-nav__input {
  height: 44px;
  font-size: 15px;
  padding-left: 38px;
}
.top-quick-nav--palette .top-quick-nav__list {
  margin: 8px 0 0;
  width: 100%;
  box-sizing: border-box;
  max-height: min(48vh, 460px);
  padding: 4px 0;
  background: var(--el-bg-color-overlay, #fff);
  border: 0;
  box-shadow: none;
}

.top-quick-nav--palette .top-quick-nav__icon { left: 24px; top: 34px; }
.top-quick-nav__star { color: #b48b24; margin-left: auto; }
.top-quick-nav__footer {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  padding: 10px 0;
  margin-top: 8px;
  border-top: 1px solid var(--el-border-color-light, #e4e9f1);
}
.top-quick-nav__footer button, .top-quick-nav__settings button {
  padding: 6px 10px;
  border: 0;
  border-radius: 8px;
  background: var(--el-fill-color-light, #edf2f7);
  color: var(--el-text-color-primary, #334155);
  cursor: pointer;
}
.top-quick-nav__footer button:disabled { opacity: .45; cursor: default; }
.top-quick-nav__footer button:last-child { margin-left: auto; }
.top-quick-nav__settings {
  padding: 8px 0 12px;
  max-height: min(36vh, 300px);
  overflow: auto;
  color: var(--el-text-color-primary, #334155);
}
.top-quick-nav__settings label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 7px;
  font-size: 12px;
}
.top-quick-nav__settings select {
  max-width: 100%;
  background: var(--el-fill-color-blank, #fff);
  color: inherit;
  border: 1px solid var(--el-border-color, #b8c6d6);
  border-radius: 7px;
  min-width: 150px;
  padding: 5px 7px;
}
.top-quick-nav__settings [role="alert"] { color: var(--el-color-danger, #bf2838); }
.top-quick-nav--palette :focus-visible { outline: 2px solid var(--el-color-primary, #137cdb); outline-offset: 2px; }
@media (prefers-reduced-motion: reduce) {
  .top-quick-nav__scrim { backdrop-filter: none; }
}

.top-quick-nav {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  width: min(420px, 36vw);
  z-index: 40;
}

@media (max-width: 900px) {
  .top-quick-nav {
    position: static;
    transform: none;
    width: auto;
    flex: 1 1 140px;
    min-width: 0;
    max-width: 220px;
    margin: 0 8px;
  }
}

.top-quick-nav__icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 12px;
  color: rgba(100, 116, 139, 0.8);
  pointer-events: none;
}

.top-quick-nav__input {
  width: 100%;
  height: 32px;
  box-sizing: border-box;
  padding: 0 12px 0 30px;
  border: 1px solid rgba(203, 213, 225, 0.85);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.88);
  color: #334155;
  font-size: 13px;
  outline: none;
  transition:
    border-color 0.15s ease,
    box-shadow 0.15s ease;
}

.top-quick-nav__input::placeholder {
  color: rgba(100, 116, 139, 0.65);
}

.top-quick-nav__input:focus {
  border-color: rgba(11, 114, 217, 0.45);
  box-shadow: 0 0 0 3px rgba(24, 144, 255, 0.14);
  background: #fff;
}

.top-quick-nav__list {
  position: fixed;
  margin: 0;
  padding: 6px;
  list-style: none;
  max-height: 320px;
  overflow-y: auto;
  background: #fff;
  border: 1px solid rgba(203, 213, 225, 0.9);
  border-radius: 12px;
  box-shadow: 0 18px 44px rgba(15, 23, 42, 0.14);
}

.top-quick-nav__option {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 8px;
  font-size: 13px;
  color: #334155;
  cursor: pointer;
}

.top-quick-nav__option.highlighted {
  background: rgba(239, 246, 255, 0.96);
  color: #0b72d9;
}

.top-quick-nav__option-icon {
  width: 16px;
  text-align: center;
  font-size: 13px;
  color: rgba(71, 85, 105, 0.85);
}

.top-quick-nav__option.highlighted .top-quick-nav__option-icon {
  color: #0b72d9;
}

.top-quick-nav__kind {
  flex: none;
  font-size: 11px;
  line-height: 1;
  padding: 3px 6px;
  border-radius: 999px;
  background: rgba(219, 234, 254, 0.9);
  color: #0b72d9;
}

.top-quick-nav__empty {
  padding: 10px;
  font-size: 12px;
  color: rgba(100, 116, 139, 0.8);
  text-align: center;
}

.top-quick-nav__narrow-trigger { display: none; }
@media (max-width: 1023px) {
  .top-quick-nav:not(.top-quick-nav--palette) {
    display: none;
  }
  .top-quick-nav__narrow-trigger {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: 0 0 36px;
    width: 36px;
    height: 36px;
    border: 1px solid var(--xc-color-border);
    border-radius: var(--xc-radius-md);
    color: var(--xc-color-text);
    background: var(--xc-color-surface);
    cursor: pointer;
  }
  .top-quick-nav__narrow-trigger:focus-visible {
    outline: 2px solid var(--xc-color-primary);
    outline-offset: 2px;
  }
}
@media (max-width: 480px) {
  .top-quick-nav.top-quick-nav--palette {
    top: 12px;
    max-height: calc(100dvh - 24px);
    width: calc(100vw - 24px);
  }
  .top-quick-nav__settings label { flex-wrap: wrap; }
}
</style>
