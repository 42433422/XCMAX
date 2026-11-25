<template>
  <div class="top-quick-nav">
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
      aria-label="搜索功能、订单、产品、客户、员工或模板"
      placeholder="搜索功能、订单、产品、客户、员工或模板"
      autocomplete="off"
      @focus="onFocus"
      @keydown="onKeydown"
      @blur="onBlur"
    />
    <Teleport to="body">
      <ul
        v-if="open"
        id="top-quick-nav-list"
        class="top-quick-nav__list"
        role="listbox"
        aria-label="功能列表"
        :style="listStyle"
      >
        <li v-if="!filtered.length" class="top-quick-nav__empty">没有匹配的功能、订单、产品、客户、员工或模板</li>
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
        </li>
      </ul>
    </Teleport>
  </div>
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

const emit = defineEmits(['select'])
const router = useRouter()

/** 与模板库约定的交接键：跳转前写入关键词，模板库挂载后读取。 */
const TEMPLATE_SEARCH_STORAGE_KEY = 'xcagi_template_search_keyword'
const TEMPLATE_NAV_KEY = 'template-preview'
const KIND_LABELS = { product: '产品', customer: '客户', order: '订单', employee: '员工', template: '模板' }
const KIND_ICONS = { product: 'fa-cube', customer: 'fa-user-o', order: 'fa-file-text-o', employee: 'fa-id-badge', template: 'fa-file-o' }

const { visibleNavItems } = useVisibleNavItems()
const modsStore = useModsStore()
const recordScope = computed(() => productReadScopeKey(String(modsStore.activeModId || '')))

const desktopEnabled = isDesktopShell()
const macPlatform = typeof navigator !== 'undefined' && /Mac/i.test(navigator.platform || '')
const shortcutLabel = macPlatform ? 'Meta+K' : 'Control+K'
const recentKeys = ref([])
let restoreTarget = null
let blurTimer = null

const query = ref('')
const open = ref(false)
const highlightIndex = ref(0)
const keyboardMoved = ref(false)
const inputRef = ref(null)
const records = ref([])
const listStyle = ref({ position: 'fixed', top: '0px', left: '0px', width: '420px', zIndex: 4000 })
let recordTimer = null
let recordGeneration = 0

const filtered = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  const items = (visibleNavItems.value || []).map((item) => ({ ...item, kind: 'nav' }))
  const nav = keyword
    ? items.filter((item) => `${item.name || ''} ${item.key || ''} ${item.routeName || ''}`.toLowerCase().includes(keyword))
    : items
  if (keyword) return [...nav, ...records.value]
  // Reuse the current permission-filtered menu, never cache business records or hidden destinations.
  if (!desktopEnabled) return nav
  const rank = new Map(recentKeys.value.map((key, index) => [key, index]))
  return [...nav].sort((a, b) => (rank.get(a.key) ?? Infinity) - (rank.get(b.key) ?? Infinity))
})

function recordName(row, keys) {
  return keys.map((key) => String(row?.[key] || '').trim()).filter(Boolean).join(' · ')
}

async function lookupRecords(keyword) {
  const generation = ++recordGeneration
  const scope = recordScope.value
  const [products, customers, orders, templates, employees] = await Promise.all([
    productsApi.searchProducts(keyword).catch(() => null),
    customersApi.getCustomers({ keyword, page: 1, per_page: 8 }).catch(() => null),
    ordersApi.searchOrders(keyword).catch(() => null),
    templatePreviewApi.listTemplates().catch(() => null),
    fetchEmployeeDirectory().catch(() => []),
  ])
  if (generation !== recordGeneration || scope !== recordScope.value) return
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
  listStyle.value = {
    position: 'fixed',
    top: `${rect.bottom + 6}px`,
    left: `${rect.left}px`,
    width: `${rect.width}px`,
    zIndex: 4000,
  }
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
}

function onViewportChange() {
  if (open.value) placeList()
}

function onBlur() {
  // 延迟关闭：让选项的 mousedown（已 preventDefault 不夺焦）先完成选择
  cancelBlur()
  blurTimer = window.setTimeout(() => {
    blurTimer = null
    open.value = false
    restoreTarget = null
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
  recentKeys.value = []
  restoreTarget = null
  query.value = ''
  open.value = false
}, { flush: 'sync' })

watch(query, () => {
  highlightIndex.value = 0
  keyboardMoved.value = false
  clearRecordSearch()
  const keyword = query.value.trim()
  if (!keyword) return
  const generation = recordGeneration
  recordTimer = setTimeout(() => {
    if (generation === recordGeneration) lookupRecords(keyword)
  }, 250)
})

watch(highlightIndex, () => {
  void nextTick(() => {
    const node = document.querySelector('#top-quick-nav-list .top-quick-nav__option.highlighted')
    if (node && typeof node.scrollIntoView === 'function') node.scrollIntoView({ block: 'nearest' })
  })
})

function closeAndRestore() {
  const target = restoreTarget
  restoreTarget = null
  open.value = false
  inputRef.value?.blur?.()
  cancelBlur()
  if (target instanceof HTMLElement && target.isConnected && !target.closest('[inert]')) {
    target.focus({ preventScroll: true })
  }
}

function onGlobalKeydown(event) {
  if (!desktopEnabled || event.defaultPrevented || event.repeat || event.isComposing || event.keyCode === 229) return
  if (event.altKey || event.shiftKey || event.key.toLowerCase() !== 'k') return
  if (macPlatform ? (!event.metaKey || event.ctrlKey) : (!event.ctrlKey || event.metaKey)) return
  const active = document.activeElement
  const input = inputRef.value
  if (!input || !input.getClientRects().length || input.closest('[inert]')) return
  // Preserve active dialogs and their focus traps; never take over their keyboard handling.
  if (active instanceof Element && active.closest('[role="dialog"], [aria-modal="true"]')) return
  event.preventDefault()
  if (active === input && open.value) return
  restoreTarget = active instanceof HTMLElement && active !== input ? active : null
  input.focus({ preventScroll: true })
  onFocus()
  input.select()
}

onMounted(() => {
  window.addEventListener('resize', onViewportChange)
  window.addEventListener('scroll', onViewportChange, true)
  if (desktopEnabled) window.addEventListener('keydown', onGlobalKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onViewportChange)
  window.removeEventListener('scroll', onViewportChange, true)
  window.removeEventListener('keydown', onGlobalKeydown)
  cancelBlur()
  restoreTarget = null
  clearRecordSearch()
})

function choose(item) {
  if (item?.kind === 'template') {
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
    query.value = ''
    records.value = []
    open.value = false
    inputRef.value?.blur?.()
    return
  }
  if (item?.kind === 'product' || item?.kind === 'customer' || item?.kind === 'order') {
    if (!records.value.includes(item)) return
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
    query.value = ''
    records.value = []
    open.value = false
    inputRef.value?.blur?.()
    return
  }
  if (item?.kind === 'employee') {
    if (!records.value.includes(item)) return
    emit('select', item.navKey || 'employee-workflow')
    query.value = ''
    records.value = []
    open.value = false
    inputRef.value?.blur?.()
    return
  }
  if (!item?.key || !(visibleNavItems.value || []).some((nav) => nav.key === item.key)) return
  // Selection is only an existing sidebar navigation intent, not business execution.
  recentKeys.value = [item.key, ...recentKeys.value.filter((key) => key !== item.key)].slice(0, 8)
  restoreTarget = null
  emit('select', item.key)
  query.value = ''
  open.value = false
  inputRef.value?.blur?.()
}

function onKeydown(event) {
  if (event.isComposing || event.keyCode === 229) return
  if (event.key === 'Escape') {
    event.preventDefault()
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

@media (max-width: 1023px) {
  .top-quick-nav {
    display: none;
  }
}
</style>
