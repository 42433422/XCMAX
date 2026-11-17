<template>
  <div class="market-overview-panel" data-testid="market-overview-panel">
    <header class="mo-head">
      <div class="mo-head__title">
        <h2>智能生态市场 · 运营台</h2>
        <span class="mo-head__meta">AI 员工审核与上下架</span>
      </div>
      <div class="mo-head__actions">
        <el-input
          v-model="search"
          class="mo-search"
          size="small"
          clearable
          placeholder="搜索员工名称或包 ID"
          aria-label="搜索商品"
          @keyup.enter="applySearch"
          @clear="applySearch"
        />
        <el-select v-model="status" class="mo-status" size="small" aria-label="商品状态" @change="applySearch">
          <el-option label="全部状态" value="" />
          <el-option label="待审核" value="pending" />
          <el-option label="在架" value="listed" />
          <el-option label="受限" value="restricted" />
          <el-option label="已下架" value="delisted" />
        </el-select>
        <el-button size="small" :loading="loading" @click="load">刷新</el-button>
      </div>
    </header>

    <section class="mo-kpis" aria-label="市场审核指标">
      <article v-for="item in kpis" :key="item.key" class="admin-card mo-kpi" :class="`is-${item.key}`">
        <span class="mo-kpi__label">{{ item.label }}</span>
        <strong class="mo-kpi__value">{{ item.value }}</strong>
      </article>
    </section>

    <el-alert v-if="error" class="mo-error" type="error" show-icon :closable="false" :title="error" />

    <section class="admin-card mo-card" aria-label="商品审核列表">
      <div class="mo-table-wrap">
        <el-table v-if="loaded || loading" :data="items" height="100%" size="small" row-key="id" class="mo-table">
          <el-table-column label="员工 / 商品" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="mo-name">{{ row.name || '未命名' }}</span>
              <small class="mo-sub">{{ row.pkg_id }}</small>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="104">
            <template #default="{ row }"><el-tag size="small" effect="light" :type="artifactTagType(row.artifact)">{{ artifactLabel(row.artifact) }}</el-tag></template>
          </el-table-column>
          <el-table-column label="行业" width="96" show-overflow-tooltip>
            <template #default="{ row }">{{ row.industry || '通用' }}</template>
          </el-table-column>
          <el-table-column label="版本" width="88">
            <template #default="{ row }"><span class="mo-mono">{{ row.version || '—' }}</span></template>
          </el-table-column>
          <el-table-column label="作者" width="112" show-overflow-tooltip>
            <template #default="{ row }">{{ row.author_name || (row.author_id ? `用户 ${row.author_id}` : '平台') }}</template>
          </el-table-column>
          <el-table-column label="状态" width="104">
            <template #default="{ row }"><el-tag size="small" :type="row.badge.type" effect="light" :title="row.delist_reason">{{ row.badge.label }}</el-tag></template>
          </el-table-column>
          <el-table-column label="价格" width="92">
            <template #default="{ row }"><span class="mo-price">{{ row.priceLabel }}</span></template>
          </el-table-column>
          <el-table-column label="上架时间" width="150">
            <template #default="{ row }"><span class="mo-time">{{ row.createdAt }}</span></template>
          </el-table-column>
          <el-table-column label="操作" width="210" fixed="right">
            <template #default="{ row }">
              <div class="mo-actions">
                <el-button
                  v-for="action in actionsFor(row)"
                  :key="action.key"
                  size="small"
                  :type="action.type"
                  link
                  :disabled="busyId === row.id"
                  @click="review(row, action.key)"
                >{{ action.label }}</el-button>
              </div>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty :description="loading ? '正在读取' : '暂无商品'" :image-size="64" />
          </template>
        </el-table>
        <el-empty v-else description="暂无数据" :image-size="64" />
      </div>
      <footer class="mo-pager">
        <span>共 {{ total }} 项</span>
        <el-pagination
          small
          background
          layout="prev, pager, next"
          :total="total"
          :page-size="PAGE_SIZE"
          :current-page="page"
          :disabled="loading"
          @current-change="onPageChange"
        />
      </footer>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElAlert, ElButton, ElEmpty, ElInput, ElOption, ElPagination, ElSelect, ElTable, ElTableColumn, ElTag } from 'element-plus'
import 'element-plus/dist/index.css'
import { xcmaxMarketProxy } from '@/api/xcmaxMarketProxy'
import { appConfirm, appPrompt } from '@/utils/appDialog'
import { formatBeijingTime } from '../../utils/customerServiceTicketFormat'

const PAGE_SIZE = 50
type Row = Record<string, unknown>
type ReviewAction = 'approve' | 'restrict' | 'delist' | 'restore'

const loading = ref(false)
const loaded = ref(false)
const error = ref('')
const search = ref('')
const status = ref('')
const offset = ref(0)
const total = ref(0)
const busyId = ref<number | null>(null)
const counts = ref<Record<string, number>>({})
const items = ref<Row[]>([])
let generation = 0

const page = computed(() => Math.floor(offset.value / PAGE_SIZE) + 1)
const kpis = computed(() => [
  { key: 'total', label: '商品总数', value: metric(counts.value.total) },
  { key: 'pending', label: '待审核', value: metric(counts.value.pending) },
  { key: 'listed', label: '在架', value: metric(counts.value.listed) },
  { key: 'restricted', label: '受限', value: metric(counts.value.restricted) },
  { key: 'delisted', label: '已下架', value: metric(counts.value.delisted) },
])

function metric(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) ? String(value) : '—'
}

function statusBadge(row: Row): { label: string; type: 'success' | 'warning' | 'danger' | 'info' } {
  const state = String(row.compliance_status || 'approved')
  if (state === 'under_review') return { label: '待审核', type: 'warning' }
  if (state === 'restricted') return { label: '受限', type: 'danger' }
  if (state === 'delisted' || row.is_public !== true) return { label: '已下架', type: 'info' }
  return { label: '在架', type: 'success' }
}

function actionsFor(row: Row): Array<{ key: ReviewAction; label: string; type: 'primary' | 'warning' | 'danger' | 'success' }> {
  const state = String(row.compliance_status || 'approved')
  if (state === 'under_review') return [{ key: 'approve', label: '通过并上架', type: 'primary' }, { key: 'delist', label: '下架', type: 'danger' }]
  if (state === 'delisted' || row.is_public !== true) return [{ key: 'restore', label: '恢复上架', type: 'success' }]
  if (state === 'restricted') return [{ key: 'approve', label: '解除限制', type: 'primary' }, { key: 'delist', label: '下架', type: 'danger' }]
  return [{ key: 'restrict', label: '限制', type: 'warning' }, { key: 'delist', label: '下架', type: 'danger' }]
}

function artifactLabel(artifact: unknown): string {
  const key = String(artifact || '').toLowerCase()
  if (key === 'employee_pack') return 'AI 员工'
  if (key === 'mod') return '业务 Mod'
  if (key === 'eskill') return '技能包'
  return key || '其他'
}

function artifactTagType(artifact: unknown): 'success' | 'primary' | 'warning' | 'info' {
  const key = String(artifact || '').toLowerCase()
  if (key === 'employee_pack') return 'success'
  if (key === 'mod') return 'primary'
  if (key === 'eskill') return 'warning'
  return 'info'
}

function rowsOf(raw: Row[]): Row[] {
  return raw.map((row) => ({
    ...row,
    id: Number(row.id),
    badge: statusBadge(row),
    priceLabel: Number(row.price || 0) > 0 ? `¥${Number(row.price).toFixed(2)}` : '免费',
    createdAt: formatBeijingTime(row.created_at),
  }))
}

function messageOf(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause)
}

async function load() {
  const request = ++generation
  loading.value = true
  error.value = ''
  try {
    const result = await xcmaxMarketProxy.adminListCatalog(PAGE_SIZE, offset.value, status.value, search.value.trim())
    if (request !== generation) return
    items.value = rowsOf(Array.isArray(result?.items) ? result.items : [])
    total.value = Number.isInteger(result?.total) ? Number(result.total) : items.value.length
    counts.value = result?.counts && typeof result.counts === 'object' ? result.counts : {}
    loaded.value = true
  } catch (cause) {
    if (request !== generation) return
    items.value = []
    total.value = 0
    counts.value = {}
    error.value = messageOf(cause)
  } finally {
    if (request === generation) loading.value = false
  }
}

function applySearch() {
  offset.value = 0
  void load()
}

function onPageChange(next: number) {
  offset.value = (next - 1) * PAGE_SIZE
  void load()
}

async function review(row: Row, action: ReviewAction) {
  if (busyId.value !== null) return
  const name = String(row.name || row.pkg_id || row.id)
  let note = ''
  if (action === 'delist') {
    note = (await appPrompt('下架原因（至少 4 个字）', ''))?.trim() || ''
    if (note.length < 4) { error.value = '下架原因至少 4 个字'; return }
  } else if (action === 'restrict') {
    note = (await appPrompt('限制原因（可选）', ''))?.trim() || ''
  }
  const actionLabel = { approve: '通过并上架', restrict: '限制', delist: '下架', restore: '恢复上架' }[action]
  if (!await appConfirm(`确认${actionLabel}「${name}」？`, { title: '商品审核' })) return
  busyId.value = Number(row.id)
  error.value = ''
  try {
    await xcmaxMarketProxy.adminReviewCatalog(Number(row.id), action, note)
    await load()
  } catch (cause) {
    error.value = messageOf(cause)
  } finally {
    busyId.value = null
  }
}

onMounted(load)
defineExpose({ load })
</script>

<style scoped>
.market-overview-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}
.mo-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex: 0 0 auto;
}
.mo-head__title {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 4px 10px;
  min-width: 0;
}
.mo-head__title h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--admin-text, #172033);
}
.mo-head__meta {
  color: var(--admin-muted, #64748b);
  font-size: 12px;
}
.mo-head__actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.mo-search { width: 220px; }
.mo-status { width: 120px; }
.mo-kpis {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
  flex: 0 0 auto;
}
.mo-kpi {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  padding: 8px 14px;
}
.mo-kpi__label {
  color: var(--admin-muted, #64748b);
  font-size: 12px;
}
.mo-kpi__value {
  color: var(--admin-text, #172033);
  font-size: 20px;
  font-weight: 700;
  line-height: 1.25;
  font-variant-numeric: tabular-nums;
}
.mo-kpi.is-pending .mo-kpi__value { color: #b45309; }
.mo-kpi.is-restricted .mo-kpi__value { color: #b91c1c; }
.mo-kpi.is-listed .mo-kpi__value { color: #047857; }
.mo-card {
  display: flex;
  flex-direction: column;
  flex: 1 1 0;
  min-height: 0;
  padding: 0;
  overflow: hidden;
}
.mo-table-wrap {
  display: flex;
  flex: 1 1 0;
  flex-direction: column;
  min-height: 0;
  justify-content: center;
}
.mo-table { flex: 1 1 0; height: 100%; min-height: 0; }
.mo-table :deep(.el-table__inner-wrapper) { height: 100%; }
.mo-table :deep(th.el-table__cell) {
  height: 34px;
  padding: 0;
  background: #f7fafd;
  color: var(--admin-muted, #64748b);
  font-size: 12px;
  font-weight: 600;
}
.mo-table :deep(td.el-table__cell) { padding: 5px 0; font-size: 12.5px; }
.mo-table :deep(.cell) { padding: 0 10px; }
.mo-name {
  display: block;
  overflow: hidden;
  color: var(--admin-text, #172033);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mo-sub {
  display: block;
  color: #94a3b8;
  font-size: 11px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.mo-mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
}
.mo-time { color: var(--admin-muted, #64748b); font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.mo-price { font-variant-numeric: tabular-nums; }
.mo-actions { display: flex; align-items: center; gap: 2px; flex-wrap: wrap; }
.mo-pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex: 0 0 auto;
  padding: 6px 12px;
  border-top: 1px solid #eef2f7;
  color: var(--admin-muted, #64748b);
  font-size: 12px;
}
@media (max-width: 1279px) {
  .mo-kpis { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 1099px), (max-height: 619px) {
  .market-overview-panel { height: auto; min-height: 100%; overflow-y: auto; }
  .mo-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .mo-card { min-height: 320px; }
  .mo-head { align-items: flex-start; flex-direction: column; }
}
</style>
