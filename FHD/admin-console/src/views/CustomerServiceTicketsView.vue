<template>
  <main class="cs-view page-content" id="view-customer-service-tickets">
    <header class="csx-head">
      <div class="csx-head__title">
        <h2>客服工单 · 客户反馈</h2>
        <span class="csx-head__meta">共 {{ total }} 单</span>
      </div>
      <el-button size="small" :loading="loading" @click="load(offset)">刷新</el-button>
    </header>

    <form class="csx-toolbar" role="search" @submit.prevent="load(0, true)">
      <el-input
        v-model="search"
        class="csx-toolbar__search"
        size="small"
        clearable
        :disabled="loading"
        maxlength="200"
        placeholder="搜索编号、尾号、内部 ID 或问题关键词"
        aria-label="搜索编号或原文"
        @keyup.enter="load(0, true)"
        @clear="load(0, true)"
      />
      <el-select v-model="typeFilter" class="csx-toolbar__select" size="small" placeholder="全部类型" aria-label="工单类型" :disabled="loading" @change="load(0, true)">
        <el-option label="全部类型" value="" />
        <el-option label="事故" value="incident" />
        <el-option label="缺陷" value="defect" />
        <el-option label="服务请求" value="request" />
        <el-option label="咨询" value="question" />
        <el-option label="投诉" value="complaint" />
        <el-option label="交付实施" value="delivery" />
        <el-option label="账号权益" value="account" />
      </el-select>
      <el-select v-model="domainFilter" class="csx-toolbar__select" size="small" placeholder="全部业务域" aria-label="业务域" :disabled="loading" @change="load(0, true)">
        <el-option label="全部业务域" value="" />
        <el-option label="平台" value="platform" />
        <el-option label="软件" value="software" />
        <el-option label="客户定制" value="custom" />
      </el-select>
      <el-select v-model="sourceFilter" class="csx-toolbar__select csx-toolbar__select--narrow" size="small" placeholder="全部来源" aria-label="来源" :disabled="loading" @change="load(0, true)">
        <el-option label="全部来源" value="" />
        <el-option label="客户对话" value="customer_chat" />
        <el-option label="管理员自建" value="admin_created" />
        <el-option label="GitHub 自愈" value="github_self_heal" />
      </el-select>
      <el-select v-model="statusFilter" class="csx-toolbar__select" size="small" placeholder="全部状态" aria-label="处理状态" :disabled="loading" @change="load(0, true)">
        <el-option label="全部状态" value="" />
        <el-option label="已过期不再处理" value="expired" />
        <el-option label="待处理" value="open" />
        <el-option label="处理中" value="processing" />
        <el-option label="待客户确认" value="awaiting_customer" />
        <el-option label="已重新打开" value="reopened" />
        <el-option label="已完成" value="resolved" />
        <el-option label="已关闭" value="closed" />
        <el-option label="已拒绝" value="rejected" />
        <el-option label="已取消" value="cancelled" />
      </el-select>
      <el-button type="primary" size="small" native-type="submit" :loading="loading">搜索</el-button>
    </form>

    <el-alert
      v-if="error"
      class="csx-alert"
      type="error"
      show-icon
      :closable="false"
      :title="error"
    />

    <section class="cs-card csx-card" aria-label="客服工单列表">
      <div class="csx-table-wrap">
        <el-table
          v-if="loaded || loading"
          class="csx-table"
          :data="rows"
          height="100%"
          size="small"
          row-key="id"
          highlight-current-row
          :row-class-name="() => 'csx-row'"
          @row-click="(row: TicketRow) => open(row.id)"
        >
          <el-table-column label="工单编号" width="168">
            <template #default="{ row }">
              <button type="button" class="csx-ticket-no" :aria-label="`打开工单 ${row.ticketNo}`" @click.stop="open(row.id)">{{ row.ticketNo }}</button>
              <span class="csx-sub">内部 ID {{ row.id }}</span>
            </template>
          </el-table-column>
          <el-table-column label="问题" min-width="220" show-overflow-tooltip>
            <template #default="{ row }"><span class="csx-title">{{ row.title }}</span></template>
          </el-table-column>
          <el-table-column label="类型" width="92">
            <template #default="{ row }"><span v-if="row.type" class="csx-tag">{{ row.type }}</span></template>
          </el-table-column>
          <el-table-column label="业务域" width="92">
            <template #default="{ row }"><span v-if="row.domain" class="csx-tag">{{ row.domain }}</span></template>
          </el-table-column>
          <el-table-column label="来源" width="104">
            <template #default="{ row }"><span v-if="row.source" class="csx-tag">{{ row.source }}</span></template>
          </el-table-column>
          <el-table-column label="客户" width="108">
            <template #default="{ row }"><span class="csx-sub csx-sub--inline">用户 {{ row.userId }}</span></template>
          </el-table-column>
          <el-table-column label="状态" width="108">
            <template #default="{ row }">
              <el-tag size="small" :type="row.status.epType" effect="light" :title="row.status.raw">{{ row.status.label }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="最近更新" width="150">
            <template #default="{ row }"><span class="csx-time">{{ row.updatedAt }}</span></template>
          </el-table-column>
          <template #empty>
            <el-empty :description="loading ? '正在读取' : '暂无工单'" :image-size="72" />
          </template>
        </el-table>
        <el-empty v-else description="暂无数据" :image-size="72" />
      </div>
      <footer class="csx-pager">
        <span>共 {{ total }} 单</span>
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
  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElAlert, ElButton, ElEmpty, ElInput, ElOption, ElPagination, ElSelect, ElTable, ElTableColumn, ElTag } from 'element-plus'
import 'element-plus/dist/index.css'
import { xcmaxAdminApi } from '@/api/xcmaxAdmin'
import { formatBeijingTime, ticketDomainLabel, ticketSourceLabel, ticketStatusBadge, ticketTypeLabel, type Row } from '../utils/customerServiceTicketFormat'

const PAGE_SIZE = 50
const router = useRouter()
const route = useRoute()
const search = ref(String(route.query?.q || '')), statusFilter = ref(''), typeFilter = ref(String(route.query?.type || '')), domainFilter = ref(''), sourceFilter = ref(''), error = ref('')
const tickets = ref<Row[]>([])
const loading = ref(false), loaded = ref(false)
const offset = ref(0), total = ref(0)
let generation = 0
let appliedSearch = ''
let appliedStatus = ''
let appliedType = ''
let appliedDomain = ''
let appliedSource = ''
const page = computed(() => Math.floor(offset.value / PAGE_SIZE) + 1)

type TicketRow = {
  id: number
  ticketNo: string
  title: string
  type: string
  domain: string
  source: string
  userId: string
  status: { label: string; tone: string; raw: string; epType: 'success' | 'info' | 'warning' | 'danger' | 'primary' }
  updatedAt: string
}

const EP_TAG_TYPE: Record<string, 'success' | 'info' | 'warning' | 'danger' | 'primary'> = {
  success: 'success',
  info: 'primary',
  warning: 'warning',
  danger: 'danger',
  neutral: 'info',
}

const rows = computed<TicketRow[]>(() => tickets.value.map((t) => {
  const status = ticketStatusBadge(t)
  return {
    id: Number(t.id),
    ticketNo: String(t.ticket_no || '未记录编号'),
    title: String(t.title || '（无标题）'),
    type: ticketTypeLabel(t),
    domain: ticketDomainLabel(t),
    source: ticketSourceLabel(t),
    userId: String(t.user_id ?? '—'),
    status: { ...status, epType: EP_TAG_TYPE[status.tone] || 'info' },
    updatedAt: formatBeijingTime(t.updated_at || t.created_at),
  }
}))
const message = (cause: unknown) => cause instanceof Error ? cause.message : String(cause)

function open(id: number) {
  void router.push({ name: 'customer-service-ticket-detail', params: { ticketId: String(id) } })
}

function onPageChange(next: number) {
  void load((next - 1) * PAGE_SIZE)
}

async function load(nextOffset: number, applySearch = false) {
  if (loading.value) return
  const request = ++generation
  loading.value = true; error.value = ''; loaded.value = false
  try {
    const term = applySearch ? search.value.trim() : appliedSearch
    const status = applySearch ? statusFilter.value : appliedStatus
    const type = applySearch ? typeFilter.value : appliedType
    const domain = applySearch ? domainFilter.value : appliedDomain
    const source = applySearch ? sourceFilter.value : appliedSource
    const result = await xcmaxAdminApi.fetchCustomerTickets(term, nextOffset, '', '', status, type, domain, source, String(route.query?.account_id || ''))
    if (request !== generation) return
    if (!Array.isArray(result.items) || !Number.isInteger(result.total) || result.total < 0) throw new Error('响应不完整')
    appliedSearch = term
    appliedStatus = status
    appliedType = type
    appliedDomain = domain
    appliedSource = source
    tickets.value = result.items; total.value = result.total; offset.value = nextOffset; loaded.value = true
  } catch (cause) { if (request === generation) { tickets.value = []; error.value = message(cause) } }
  finally { if (request === generation) loading.value = false }
}
onMounted(() => { void load(0, Boolean(route.query?.q || route.query?.type)) })
onBeforeUnmount(() => { generation++ })
</script>

<style scoped src="./CustomerServiceTickets.css"></style>
<style scoped>
/* 首屏不滚动：页头与工具栏固定，表格占满剩余高度并在内部滚动；窄屏回退为整页滚动。 */
#view-customer-service-tickets {
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100%;
  min-height: 0;
  padding: 14px 20px 12px;
  overflow: hidden;
  background: transparent;
}
.csx-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex: 0 0 auto;
}
.csx-head__title {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}
.csx-head__title h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--cs-text);
}
.csx-head__meta {
  color: var(--cs-muted);
  font-size: 12px;
  white-space: nowrap;
}
.csx-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  flex: 0 0 auto;
  padding: 8px 10px;
  border: 1px solid var(--cs-card-border);
  border-radius: 10px;
  background: #fff;
}
.csx-toolbar__search {
  flex: 1 1 240px;
  min-width: 180px;
}
.csx-toolbar__select {
  flex: 0 0 144px;
  width: 144px;
}
.csx-toolbar__select--narrow {
  flex-basis: 128px;
  width: 128px;
}
.csx-alert {
  flex: 0 0 auto;
}
.csx-card {
  display: flex;
  flex-direction: column;
  flex: 1 1 0;
  min-height: 0;
  margin: 0;
  padding: 0;
  overflow: hidden;
  border: 1px solid var(--cs-card-border);
  border-radius: 12px;
  background: #fff;
}
.csx-table-wrap {
  display: flex;
  flex: 1 1 0;
  flex-direction: column;
  min-height: 0;
  justify-content: center;
}
.csx-table {
  flex: 1 1 0;
  height: 100%;
  min-height: 0;
}
.csx-table :deep(.el-table__inner-wrapper) {
  height: 100%;
}
.csx-table :deep(th.el-table__cell) {
  height: 36px;
  padding: 0;
  background: #f7fafd;
  color: var(--cs-muted);
  font-size: 12px;
  font-weight: 600;
}
.csx-table :deep(td.el-table__cell) {
  padding: 5px 0;
}
.csx-table :deep(.cell) {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 10px;
  line-height: 1.45;
}
.csx-table :deep(.el-table__row) {
  cursor: pointer;
}
.csx-table :deep(.el-table__row:hover > td.el-table__cell) {
  background: #f3f8ff;
}
.csx-ticket-no {
  padding: 0;
  border: 0;
  background: none;
  color: var(--cs-accent);
  font: 600 12.5px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace;
  text-align: left;
  word-break: break-all;
  cursor: pointer;
}
.csx-title {
  overflow: hidden;
  color: var(--cs-text);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.csx-sub {
  display: block;
  color: var(--cs-muted);
  font-size: 11px;
  line-height: 1.3;
}
.csx-sub--inline {
  display: inline;
  font-size: 12px;
}
.csx-tag {
  flex: 0 0 auto;
  padding: 0 7px;
  border: 1px solid var(--cs-line);
  border-radius: 6px;
  background: #f8fafc;
  color: #475569;
  font-size: 11.5px;
  line-height: 19px;
  white-space: nowrap;
}
.csx-time {
  color: var(--cs-muted);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.csx-pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex: 0 0 auto;
  padding: 6px 12px;
  border-top: 1px solid var(--cs-line);
  color: var(--cs-muted);
  font-size: 12px;
}
@media (max-width: 899px), (max-height: 619px) {
  #view-customer-service-tickets {
    height: auto;
    min-height: 100%;
    overflow-y: auto;
  }
  .csx-card {
    min-height: 320px;
  }
  .csx-toolbar {
    flex-wrap: wrap;
  }
}
</style>
