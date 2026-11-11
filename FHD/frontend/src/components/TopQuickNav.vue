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
      aria-label="搜索功能、产品型号或客户"
      placeholder="搜索功能、产品型号或客户"
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
        <li v-if="!filtered.length" class="top-quick-nav__empty">没有匹配的功能、产品或客户</li>
        <li
          v-for="(item, idx) in filtered"
          :key="`${item.kind}-${item.key || item.id}-${idx}`"
          class="top-quick-nav__option"
          :class="{ highlighted: idx === highlightIndex }"
          role="option"
          :aria-selected="idx === highlightIndex ? 'true' : 'false'"
          @mouseenter="highlightIndex = idx"
          @mousedown.prevent="choose(item)"
        >
          <i v-if="item.iconClass" class="fa top-quick-nav__option-icon" :class="item.iconClass" aria-hidden="true"></i>
          <span v-if="item.kind !== 'nav'" class="top-quick-nav__kind">{{ item.kind === 'product' ? '产品' : '客户' }}</span>
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
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import customersApi from '@/api/customers'
import productsApi from '@/api/products'
import { useVisibleNavItems } from '@/composables/useVisibleNavItems'
import { pushErpPage } from '@/utils/erpPagePaths'

const emit = defineEmits(['select'])
const router = useRouter()

const { visibleNavItems } = useVisibleNavItems()

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
  return keyword ? [...nav, ...records.value] : nav
})

function recordName(row, keys) {
  return keys.map((key) => String(row?.[key] || '').trim()).filter(Boolean).join(' · ')
}

async function lookupRecords(keyword) {
  const generation = ++recordGeneration
  const [products, customers] = await Promise.all([
    productsApi.searchProducts(keyword).catch(() => null),
    customersApi.getCustomers({ keyword, page: 1, per_page: 8 }).catch(() => null),
  ])
  if (generation !== recordGeneration) return
  const productRows = Array.isArray(products?.data) ? products.data : []
  const customerRows = Array.isArray(customers?.data) ? customers.data : []
  records.value = [
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

function onFocus() {
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
  window.setTimeout(() => {
    open.value = false
  }, 180)
}

watch(query, () => {
  highlightIndex.value = 0
  keyboardMoved.value = false
  if (recordTimer) clearTimeout(recordTimer)
  const keyword = query.value.trim()
  records.value = []
  recordGeneration += 1
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

if (typeof window !== 'undefined') {
  window.addEventListener('resize', onViewportChange)
  window.addEventListener('scroll', onViewportChange, true)
}

onBeforeUnmount(() => {
  window.removeEventListener('resize', onViewportChange)
  window.removeEventListener('scroll', onViewportChange, true)
  if (recordTimer) clearTimeout(recordTimer)
})

function choose(item) {
  if (item?.kind === 'product' || item?.kind === 'customer') {
    pushErpPage(router, {
      path: item.kind === 'product' ? '/products' : '/customers',
      query: {
        keyword: item.keyword || query.value.trim(),
        ...(item.id != null && item.id !== '' ? { focus: String(item.id) } : {}),
      },
    })
    query.value = ''
    records.value = []
    open.value = false
    inputRef.value?.blur?.()
    return
  }
  if (!item?.key) return
  emit('select', item.key)
  query.value = ''
  open.value = false
  inputRef.value?.blur?.()
}

function onKeydown(event) {
  if (event.isComposing || event.keyCode === 229) return
  if (event.key === 'Escape') {
    open.value = false
    inputRef.value?.blur?.()
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
