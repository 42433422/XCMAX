<template>
  <div class="data-table-wrapper" ref="tableWrapper" :aria-busy="loading" @scroll="handleScroll">
    <table class="data-table">
      <thead>
        <tr>
          <th v-if="selectable">
            <input type="checkbox" v-model="localSelectAll" aria-label="选择全部已加载记录" @change.stop="handleSelectAll" />
          </th>
          <th v-for="col in columns" :key="col.key" :style="columnStyle(col)" :aria-sort="col.sortable ? (sortKey === col.key ? sortDirection : 'none') : undefined">
            <button v-if="col.sortable" type="button" class="data-table-sort" :title="remoteSort ? '交由服务端排序' : '仅对已加载记录排序'" @click="toggleSort(col.key)">
              {{ col.label }} <span aria-hidden="true">{{ sortKey === col.key ? (sortDirection === 'ascending' ? '↑' : sortDirection === 'descending' ? '↓' : '↕') : '↕' }}</span>
            </button>
            <template v-else>{{ col.label }}</template>
          </th>
          <th v-if="$slots.actions">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="showLoadingRow && loading && localData.length === 0">
          <td :colspan="totalColumns" class="empty-state">加载中...</td>
        </tr>
        <tr v-else-if="localData.length === 0 && !loading">
          <td v-if="error" :colspan="totalColumns" class="empty-state" role="alert">
            {{ error }} <button type="button" class="data-table-retry" @click="emit('retry')">重试</button>
          </td>
          <td v-else :colspan="totalColumns" class="empty-state">{{ emptyText }}</td>
        </tr>
        <template v-else>
          <tr
            v-for="(row, index) in visibleData"
            :key="getRowKey(row, pageStart + index)"
            :data-row-id="String(getRowId(row) ?? '')"
            :class="{ 'is-focused': isFocusedRow(row) }"
          >
            <td v-if="selectable">
              <input
                type="checkbox"
                :value="getRowId(row)"
                :aria-label="`选择记录 ${String(getRowId(row))}`"
                v-model="localSelectedIds"
                @click.stop
              />
            </td>
            <td v-for="col in columns" :key="col.key" :style="columnStyle(col)">
              <slot :name="`cell-${col.key}`" :row="row" :value="getCellValue(row, col)">
                {{ formatCell(row, col) }}
              </slot>
            </td>
            <td v-if="$slots.actions" class="data-table-actions-cell">
              <div class="data-table-actions-inner">
                <slot name="actions" :row="row" :index="pageStart + index"></slot>
              </div>
            </td>
          </tr>
        </template>
        <tr v-if="error && !loading && localData.length > 0">
          <td :colspan="totalColumns" class="empty-state" role="alert">
            {{ error }} <button type="button" class="data-table-retry" @click="emit('retry')">重试</button>
          </td>
        </tr>
        <tr v-if="loading && localData.length > 0 && isLastPage">
          <td :colspan="totalColumns" class="loading-state">加载中...</td>
        </tr>
        <tr v-if="hasMore && !loading && !error && localData.length > 0 && isLastPage">
          <td :colspan="totalColumns" class="has-more-tip">滚动加载更多</td>
        </tr>
        <tr v-if="!hasMore && !loading && !error && localData.length > 0 && isLastPage">
          <td :colspan="totalColumns" class="no-more-tip">没有更多数据了</td>
        </tr>
      </tbody>
      <tfoot v-if="pageCount > 1">
        <tr>
          <td :colspan="totalColumns">
            <nav class="data-table-pages" aria-label="已加载记录分页">
              <button type="button" :disabled="page === 0" @click="changePage(page - 1)">上一页</button>
              <span aria-live="polite">{{ page + 1 }} / {{ pageCount }} · 已加载 {{ localData.length }} 条</span>
              <button type="button" :disabled="isLastPage" @click="changePage(page + 1)">下一页</button>
            </nav>
          </td>
        </tr>
      </tfoot>
    </table>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, useSlots } from 'vue'

const props = defineProps({
  columns: {
    type: Array,
    required: true,
  },
  data: {
    type: Array,
    default: () => [],
  },
  loading: {
    type: Boolean,
    default: false,
  },
  showLoadingRow: {
    type: Boolean,
    default: true,
  },
  selectable: {
    type: Boolean,
    default: false,
  },
  selectedIds: {
    type: Array,
    default: () => [],
  },
  rowKey: {
    type: String,
    default: 'id',
  },
  emptyText: {
    type: String,
    default: '暂无数据',
  },
  hasMore: {
    type: Boolean,
    default: true,
  },
  highlightId: {
    type: [String, Number],
    default: '',
  },
  height: {
    type: String,
    default: '500px',
  },
  error: { type: String, default: '' },
  remoteSort: { type: Boolean, default: false },
})

const emit = defineEmits(['update:selectedIds', 'select-change', 'row-click', 'load-more', 'sort-change', 'retry'])

const tableWrapper = ref(null)
const slots = useSlots()

const handleScroll = () => {
  if (!tableWrapper.value || props.loading || props.error || !props.hasMore || !isLastPage.value) return

  const { scrollTop, scrollHeight, clientHeight } = tableWrapper.value
  const threshold = 100

  if (scrollHeight - scrollTop - clientHeight < threshold) {
    emit('load-more')
  }
}

const localSelectedIds = ref([...props.selectedIds])
const localSelectAll = ref(false)
let isSyncing = false

const totalColumns = computed(() => {
  let count = props.columns.length
  if (props.selectable) count++
  if (slots.actions) count++
  return count
})

const localData = computed(() => props.data)
const sortKey = ref('')
const sortDirection = ref('none')
const sortCollator = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' })
const columnStyle = (column) => {
  const length = (value) => typeof value === 'number' ? `${value}px` : value
  return {
    width: length(column.width),
    minWidth: length(column.minWidth),
    textAlign: ['left', 'center', 'right'].includes(column.align) ? column.align : undefined,
  }
}
function toggleSort(key) {
  sortDirection.value = sortKey.value !== key || sortDirection.value === 'none'
    ? 'ascending' : sortDirection.value === 'ascending' ? 'descending' : 'none'
  sortKey.value = sortDirection.value === 'none' ? '' : key
  page.value = 0
  emit('sort-change', { key: sortKey.value || null, order: sortDirection.value, scope: props.remoteSort ? 'server' : 'loaded' })
}
const sortedData = computed(() => {
  if (props.remoteSort || !sortKey.value) return localData.value
  const column = props.columns.find((item) => item.key === sortKey.value && item.sortable)
  if (!column) return localData.value
  const compare = (a, b) => {
    const left = getCellValue(a, column)
    const right = getCellValue(b, column)
    if (left == null || right == null) return left == null ? (right == null ? 0 : 1) : -1
    if (typeof left === 'number' && typeof right === 'number') return left - right
    return sortCollator.compare(String(left), String(right))
  }
  return [...localData.value].sort((a, b) => (sortDirection.value === 'descending' ? -1 : 1) * compare(a, b))
})
// Real table rows support arbitrary heights and custom slot contents.
// Limit mounted rows independently of the caller's server-side paging.
const PAGE_SIZE = 100
const page = ref(0)
const pageCount = computed(() => Math.max(1, Math.ceil(localData.value.length / PAGE_SIZE)))
const pageStart = computed(() => page.value * PAGE_SIZE)
const isLastPage = computed(() => page.value === pageCount.value - 1)
const visibleData = computed(() => sortedData.value.slice(pageStart.value, pageStart.value + PAGE_SIZE))

function changePage(next) {
  page.value = Math.max(0, Math.min(next, pageCount.value - 1))
  if (tableWrapper.value) tableWrapper.value.scrollTop = 0
}

watch(pageCount, (count) => {
  if (page.value >= count) changePage(count - 1)
})

watch(
  localSelectedIds,
  (newVal) => {
    if (isSyncing) return
    isSyncing = true
    emit('update:selectedIds', [...newVal])
    emit('select-change', [...newVal])
    nextTick(() => {
      isSyncing = false
    })
  },
  { deep: true },
)

watch(
  () => props.selectedIds,
  (newVal) => {
    if (isSyncing) return
    isSyncing = true
    localSelectedIds.value = [...newVal]
    nextTick(() => {
      isSyncing = false
    })
  },
  { deep: true },
)

const getRowId = (row) => row[props.rowKey] ?? row.id ?? row

watch([localSelectedIds, localData], () => {
  localSelectAll.value = localData.value.length > 0
    && localData.value.every((row) => localSelectedIds.value.includes(getRowId(row)))
}, { deep: true, immediate: true })

const isFocusedRow = (row) => {
  const id = String(props.highlightId || '')
  return id !== '' && String(getRowId(row) ?? '') === id
}

watch(
  () => [props.highlightId, props.data],
  async () => {
    const id = String(props.highlightId || '')
    if (!id || !tableWrapper.value) return
    const index = sortedData.value.findIndex((row) => String(getRowId(row) ?? '') === id)
    if (index < 0) return
    const targetPage = Math.floor(index / PAGE_SIZE)
    if (targetPage !== page.value) changePage(targetPage)
    await nextTick()
    const host = tableWrapper.value
    if (!host || String(props.highlightId || '') !== id) return
    Array.from(host.querySelectorAll('[data-row-id]'))
      .find((element) => element.dataset.rowId === id)
      ?.scrollIntoView?.({ block: 'center' })
  },
)

const getRowKey = (row, index) => {
  return row[props.rowKey] ?? row.id ?? index
}

const getCellValue = (row, col) => {
  if (col.key.includes('.')) {
    return col.key.split('.').reduce((obj, key) => obj?.[key], row)
  }
  return row[col.key]
}

const formatCell = (row, col) => {
  const value = getCellValue(row, col)
  if (value === null || value === undefined) return col.default ?? '-'
  return value
}

const handleSelectAll = () => {
  localSelectedIds.value = localSelectAll.value ? localData.value.map(getRowId) : []
}

defineExpose({
  clearSelection: () => {
    localSelectedIds.value = []
    localSelectAll.value = false
  },
  selectAll: () => {
    localSelectAll.value = true
    localSelectedIds.value = localData.value.map(getRowId)
  },
})
</script>

<style scoped>
.data-table-wrapper {
  overflow-y: auto;
  overflow-x: auto;
  max-height: v-bind(height);
  border: 1px solid rgba(203, 213, 225, 0.82);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.78);
  box-shadow:
    0 12px 28px rgba(15, 23, 42, 0.06),
    inset 0 1px 0 rgba(255, 255, 255, 0.78);
}

.data-table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  font-size: 13px;
}

.data-table-sort,
.data-table-retry {
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font: inherit;
}
.data-table-sort { display: inline-flex; align-items: center; gap: 6px; font-weight: inherit; padding: 0; }
.data-table-sort:focus-visible, .data-table-retry:focus-visible { outline: 2px solid var(--primary-color, #0b72d9); outline-offset: 3px; }
.data-table-retry { margin-left: 10px; text-decoration: underline; }
.data-table th,
.data-table td {
  padding: 12px 14px;
  text-align: left;
  border-bottom: 1px solid rgba(226, 232, 240, 0.9);
}

/* 不使用 sticky 表头：粘性 th 叠在数据行上会拦截操作列点击（pointer-events 在部分环境下仍不可靠） */
.data-table th {
  background: linear-gradient(180deg, rgba(248, 250, 252, 0.98), rgba(241, 245, 249, 0.94));
  font-weight: 800;
  color: #334155;
  white-space: nowrap;
}

.data-table-actions-cell {
  position: relative;
  z-index: 2;
  white-space: nowrap;
  vertical-align: middle;
}

.data-table-actions-inner {
  position: relative;
  z-index: 2;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.data-table-actions-inner :deep(.btn) {
  position: relative;
  z-index: 3;
}

.data-table tbody tr:hover {
  background-color: rgba(219, 234, 254, 0.46);
}

.data-table tbody tr.is-focused {
  background-color: rgba(24, 144, 255, 0.16);
}

.empty-state {
  text-align: center;
  color: #64748b;
  padding: 48px !important;
  font-weight: 650;
  background: radial-gradient(circle at 50% 0%, rgba(14, 116, 217, 0.08), transparent 35%), rgba(248, 250, 252, 0.72);
}

.loading-state,
.has-more-tip,
.no-more-tip {
  text-align: center;
  color: #64748b;
  font-size: 13px;
  padding: 14px !important;
  background: rgba(248, 250, 252, 0.72);
}

.has-more-tip {
  color: #475569;
}

.no-more-tip {
  color: #94a3b8;
}

.data-table-pages {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 12px;
}
.data-table-pages button:disabled {
  opacity: 0.5;
  cursor: default;
}

.data-table input[type='checkbox'] {
  width: 16px;
  height: 16px;
  min-height: 0;
  accent-color: var(--primary-color, #0b72d9);
  cursor: pointer;
}
</style>
