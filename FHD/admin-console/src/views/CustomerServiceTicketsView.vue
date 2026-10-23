<template>
  <main class="cs-view" id="view-customer-service-tickets">
    <header class="cs-page-head">
      <div>
        <h2>客服工单 · 客户反馈</h2>
        <p>来源：市场客服原单（当前登录市场账号的可见范围）。研发 Work Order 与客户交付单在各自入口查看。时间均为北京时间。</p>
      </div>
    </header>
    <form class="cs-card cs-toolbar" @submit.prevent="load(0, true)">
      <label class="cs-search">
        <span>搜索编号或原文</span>
        <input v-model="search" :disabled="loading" maxlength="200" placeholder="完整编号、尾号、内部 ID 或问题关键词" />
      </label>
      <label class="cs-filter">
        <span>问题分类</span>
        <select v-model="intentFilter" :disabled="loading">
          <option value="">全部分类</option>
          <option value="product_issue">产品问题</option>
          <option value="custom_delivery">定制交付</option>
          <option value="account_support">账号支持</option>
          <option value="refund">退款</option>
          <option value="general">一般咨询</option>
          <option value="catalog_complaint">商品投诉</option>
          <option value="catalog_review">商品评价</option>
          <option value="llm_extension">模型扩展</option>
          <option value="greeting">问候</option>
        </select>
      </label>
      <label class="cs-filter">
        <span>处理状态</span>
        <select v-model="statusFilter" :disabled="loading">
          <option value="">全部状态</option>
          <option value="expired">已过期不再处理</option>
          <option value="open">待处理</option>
          <option value="processing">处理中</option>
          <option value="awaiting_customer">待客户确认</option>
          <option value="reopened">已重新打开</option>
          <option value="resolved">已完成</option>
          <option value="closed">已关闭</option>
          <option value="rejected">已拒绝</option>
          <option value="cancelled">已取消</option>
        </select>
      </label>
      <label>
        <span>提交人身份</span>
        <select v-model="submitterType" :disabled="loading">
          <option value="">全部</option><option value="admin">管理员提交</option><option value="customer">客户提交</option><option value="unknown">提交人待确认</option>
        </select>
      </label>
      <button class="cs-btn cs-btn-primary" :disabled="loading">搜索 / 刷新</button>
    </form>
    <p v-if="loading" role="status" class="cs-card cs-state">正在读取客服工单…</p>
    <p v-else-if="error" role="alert" class="cs-banner-error">客服数据读取失败：{{ error }}。不能据此判断没有工单，请重试。</p>
    <section v-else-if="loaded" class="cs-card" aria-label="客服工单列表">
      <p v-if="!tickets.length" class="cs-state">当前授权范围与搜索条件下没有客服工单。</p>
      <div v-else class="cs-table-wrap">
        <table class="cs-table">
          <thead>
            <tr><th>工单编号</th><th>问题</th><th>问题分类 / 范围</th><th>提交人</th><th>客户</th><th>状态</th><th>最近更新</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.id" class="cs-row" tabindex="0" :aria-label="`打开工单 ${row.ticketNo}`"
              @click="open(row.id)" @keydown.enter="open(row.id)">
              <td>
                <button type="button" class="cs-link" @click.stop="open(row.id)">{{ row.ticketNo }}</button>
                <span class="cs-sub">内部 ID {{ row.id }}</span>
              </td>
              <td class="cs-title-cell">{{ row.title }}</td>
              <td><span class="cs-tag">{{ row.category }}</span><span v-if="row.domain" class="cs-sub">{{ row.domain }}</span></td>
              <td class="cs-nowrap"><span class="cs-tag">{{ row.submitterType }}</span></td>
              <td class="cs-nowrap">市场用户 {{ row.userId }}</td>
              <td><span class="cs-badge" :class="`is-${row.status.tone}`" :title="row.status.raw">{{ row.status.label }}</span></td>
              <td class="cs-time">{{ row.updatedAt }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <footer class="cs-pager">
        <span>共 {{ total }} 单 · 第 {{ page }} / {{ pages }} 页</span>
        <div>
          <button type="button" class="cs-btn" :disabled="offset === 0" @click="load(offset - PAGE_SIZE)">上一页</button>
          <button type="button" class="cs-btn" :disabled="offset + PAGE_SIZE >= total" @click="load(offset + PAGE_SIZE)">下一页</button>
        </div>
      </footer>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { xcmaxAdminApi } from '@/api/xcmaxAdmin'
import { formatBeijingTime, intentLabel, submitterTypeLabel, ticketStatusBadge, type Row } from '../utils/customerServiceTicketFormat'

const PAGE_SIZE = 50
const router = useRouter()
const search = ref(''), submitterType = ref(''), intentFilter = ref(''), statusFilter = ref(''), error = ref('')
const tickets = ref<Row[]>([])
const loading = ref(false), loaded = ref(false)
const offset = ref(0), total = ref(0)
let generation = 0
let appliedSearch = ''
let appliedSubmitterType = ''
let appliedIntent = ''
let appliedStatus = ''
const page = computed(() => Math.floor(offset.value / PAGE_SIZE) + 1)
const pages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
const rows = computed(() => tickets.value.map(t => ({
  id: Number(t.id), ticketNo: String(t.ticket_no || '未记录编号'), title: String(t.title || '（无标题）'),
  category: intentLabel(t.intent), domain: String(t.issue_domain_label || ''), userId: String(t.user_id ?? '—'),
  submitterType: submitterTypeLabel(t.submitter_type),
  status: ticketStatusBadge(t), updatedAt: formatBeijingTime(t.updated_at || t.created_at),
})))
const message = (cause: unknown) => cause instanceof Error ? cause.message : String(cause)

function open(id: number) {
  void router.push({ name: 'customer-service-ticket-detail', params: { ticketId: String(id) } })
}

async function load(nextOffset: number, applySearch = false) {
  if (loading.value) return
  const request = ++generation
  loading.value = true; error.value = ''; loaded.value = false
  try {
    const term = applySearch ? search.value.trim() : appliedSearch
    const kind = applySearch ? submitterType.value : appliedSubmitterType
    const intent = applySearch ? intentFilter.value : appliedIntent
    const status = applySearch ? statusFilter.value : appliedStatus
    const result = await xcmaxAdminApi.fetchCustomerTickets(term, nextOffset, kind, intent, status)
    if (request !== generation) return
    if (!Array.isArray(result.items) || !Number.isInteger(result.total) || result.total < 0) throw new Error('客服列表响应不完整')
    appliedSearch = term
    appliedSubmitterType = kind
    appliedIntent = intent
    appliedStatus = status
    tickets.value = result.items; total.value = result.total; offset.value = nextOffset; loaded.value = true
  } catch (cause) { if (request === generation) { tickets.value = []; error.value = message(cause) } }
  finally { if (request === generation) loading.value = false }
}
onMounted(() => { void load(0) })
onBeforeUnmount(() => { generation++ })
</script>

<style scoped src="./CustomerServiceTickets.css"></style>
