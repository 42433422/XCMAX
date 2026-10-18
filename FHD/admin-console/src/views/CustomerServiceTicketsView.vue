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
      <button class="cs-btn cs-btn-primary" :disabled="loading">搜索 / 刷新</button>
    </form>
    <p v-if="loading" role="status" class="cs-card cs-state">正在读取客服工单…</p>
    <p v-else-if="error" role="alert" class="cs-banner-error">客服数据读取失败：{{ error }}。不能据此判断没有工单，请重试。</p>
    <section v-else-if="loaded" class="cs-card" aria-label="客服工单列表">
      <p v-if="!tickets.length" class="cs-state">当前授权范围与搜索条件下没有客服工单。</p>
      <div v-else class="cs-table-wrap">
        <table class="cs-table">
          <thead>
            <tr><th>工单编号</th><th>问题</th><th>分类</th><th>客户</th><th>状态</th><th>最近更新</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.id" class="cs-row" tabindex="0" :aria-label="`打开工单 ${row.ticketNo}`"
              @click="open(row.id)" @keydown.enter="open(row.id)">
              <td>
                <button type="button" class="cs-link" @click.stop="open(row.id)">{{ row.ticketNo }}</button>
                <span class="cs-sub">内部 ID {{ row.id }}</span>
              </td>
              <td class="cs-title-cell">{{ row.title }}</td>
              <td><span class="cs-tag">{{ row.domain }}</span></td>
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
import { formatBeijingTime, intentLabel, ticketStatusBadge, type Row } from '../utils/customerServiceTicketFormat'

const PAGE_SIZE = 50
const router = useRouter()
const search = ref(''), error = ref('')
const tickets = ref<Row[]>([])
const loading = ref(false), loaded = ref(false)
const offset = ref(0), total = ref(0)
let generation = 0
let appliedSearch = ''
const page = computed(() => Math.floor(offset.value / PAGE_SIZE) + 1)
const pages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
const rows = computed(() => tickets.value.map(t => ({
  id: Number(t.id), ticketNo: String(t.ticket_no || '未记录编号'), title: String(t.title || '（无标题）'),
  domain: String(t.issue_domain_label || '') || intentLabel(t.intent), userId: String(t.user_id ?? '—'),
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
    const result = await xcmaxAdminApi.fetchCustomerTickets(term, nextOffset)
    if (request !== generation) return
    if (!Array.isArray(result.items) || !Number.isInteger(result.total) || result.total < 0) throw new Error('客服列表响应不完整')
    appliedSearch = term
    tickets.value = result.items; total.value = result.total; offset.value = nextOffset; loaded.value = true
  } catch (cause) { if (request === generation) { tickets.value = []; error.value = message(cause) } }
  finally { if (request === generation) loading.value = false }
}
onMounted(() => { void load(0) })
onBeforeUnmount(() => { generation++ })
</script>

<style scoped src="./CustomerServiceTickets.css"></style>
