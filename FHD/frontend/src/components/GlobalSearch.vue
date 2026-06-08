<template>
  <div class="global-search" @keydown.esc="closePanel">
    <button
      type="button"
      class="global-search-trigger"
      aria-label="智能搜索"
      title="智能搜索 (⌘K)"
      @click="openPanel"
    >
      🔍 搜索
    </button>
    <div v-if="open" class="global-search-panel">
      <div class="global-search-header">
        <input
          ref="inputRef"
          v-model="query"
          type="search"
          class="global-search-input"
          placeholder="搜索产品、客户…"
          @keydown.enter="runSearch"
        />
        <div class="global-search-tabs">
          <button
            v-for="tab in tabs"
            :key="tab.id"
            type="button"
            class="tab"
            :class="{ active: scope === tab.id }"
            @click="scope = tab.id"
          >
            {{ tab.label }}
          </button>
        </div>
      </div>
      <div v-if="loading" class="global-search-status">搜索中…</div>
      <div v-else-if="error" class="global-search-status error">{{ error }}</div>
      <div v-else class="global-search-results">
        <template v-if="scope === 'products' || scope === 'all'">
          <div v-if="productRows.length" class="result-group">
            <div class="result-group-title">产品</div>
            <div v-for="(row, idx) in productRows" :key="'p-' + idx" class="result-row">
              {{ row.name || row.product_name || row.model_number || '—' }}
            </div>
          </div>
        </template>
        <template v-if="scope === 'customers' || scope === 'all'">
          <div v-if="customerRows.length" class="result-group">
            <div class="result-group-title">客户</div>
            <div v-for="(row, idx) in customerRows" :key="'c-' + idx" class="result-row">
              {{ row.customer_name || row.name || '—' }}
            </div>
          </div>
        </template>
        <div v-if="!productRows.length && !customerRows.length && lastQuery" class="global-search-status">
          无结果
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { searchApi } from '@/api/search'

const tabs = [
  { id: 'all', label: '全部' },
  { id: 'products', label: '产品' },
  { id: 'customers', label: '客户' },
]

const open = ref(false)
const query = ref('')
const lastQuery = ref('')
const scope = ref('all')
const loading = ref(false)
const error = ref('')
const result = ref(null)
const inputRef = ref(null)
let debounceTimer = null

const productRows = computed(() => {
  const block = result.value?.results?.products
  return Array.isArray(block?.data) ? block.data : []
})

const customerRows = computed(() => {
  const block = result.value?.results?.customers
  return Array.isArray(block?.data) ? block.data : []
})

function openPanel() {
  open.value = true
  nextTick(() => inputRef.value?.focus())
}

function closePanel() {
  open.value = false
}

async function runSearch() {
  const q = String(query.value || '').trim()
  lastQuery.value = q
  if (!q) {
    result.value = null
    error.value = ''
    return
  }
  loading.value = true
  error.value = ''
  try {
    result.value = await searchApi.searchV0(q, scope.value, 20)
    if (!result.value?.success) {
      error.value = '搜索失败'
    }
  } catch (e) {
    error.value = e?.message || '搜索请求失败'
    result.value = null
  } finally {
    loading.value = false
  }
}

function onGlobalKeydown(e) {
  if ((e.metaKey || e.ctrlKey) && String(e.key).toLowerCase() === 'k') {
    e.preventDefault()
    if (open.value) closePanel()
    else openPanel()
  }
}

watch([query, scope], () => {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(runSearch, 280)
})

onMounted(() => {
  window.addEventListener('keydown', onGlobalKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onGlobalKeydown)
  if (debounceTimer) clearTimeout(debounceTimer)
})
</script>

<style scoped>
.global-search {
  position: relative;
  margin-left: auto;
  margin-right: 12px;
}

.global-search-trigger {
  border: 1px solid rgba(74, 144, 217, 0.35);
  background: rgba(255, 255, 255, 0.06);
  color: inherit;
  border-radius: 8px;
  padding: 6px 12px;
  cursor: pointer;
  font-size: 13px;
}

.global-search-panel {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  width: min(420px, 90vw);
  background: #1a2332;
  border: 1px solid rgba(74, 144, 217, 0.35);
  border-radius: 10px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.35);
  z-index: 100;
  padding: 12px;
}

.global-search-input {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.15);
  background: rgba(0, 0, 0, 0.25);
  color: inherit;
}

.global-search-tabs {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}

.tab {
  border: none;
  background: transparent;
  color: rgba(255, 255, 255, 0.65);
  padding: 4px 8px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
}

.tab.active {
  background: rgba(74, 144, 217, 0.25);
  color: #fff;
}

.global-search-status {
  margin-top: 10px;
  font-size: 13px;
  opacity: 0.75;
}

.global-search-status.error {
  color: #f87171;
}

.result-group {
  margin-top: 10px;
}

.result-group-title {
  font-size: 11px;
  text-transform: uppercase;
  opacity: 0.55;
  margin-bottom: 4px;
}

.result-row {
  padding: 6px 4px;
  font-size: 13px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
</style>
