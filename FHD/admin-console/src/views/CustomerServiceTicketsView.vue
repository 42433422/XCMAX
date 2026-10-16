<template>
  <main class="approval-hub-view" id="view-customer-service-tickets">
    <header class="page-header"><div><h2>客服工单 · 客户反馈</h2><p>来源：市场客服原单（当前登录市场账号的可见范围）。研发 Work Order 与客户交付单在各自入口查看。</p></div></header>
    <form class="header-actions" @submit.prevent="load(0, true)">
      <label>搜索编号或原文 <input v-model="search" :disabled="loading" maxlength="200" placeholder="完整编号、尾号、内部 ID 或问题关键词" /></label>
      <button class="btn btn-secondary" :disabled="loading">搜索 / 刷新</button>
    </form>
    <p v-if="loading" role="status">正在读取客服工单…</p>
    <p v-else-if="error" role="alert" class="banner-error">客服数据读取失败：{{ error }}。不能据此判断没有工单，请重试。</p>
    <template v-else-if="loaded">
      <p v-if="!tickets.length" class="panel empty">当前授权范围与搜索条件下没有客服工单。</p>
      <section v-for="ticket in tickets" :key="Number(ticket.id)" class="panel">
        <button class="btn btn-secondary" @click="showTicket(Number(ticket.id))">{{ ticket.ticket_no }} · 内部 ID {{ ticket.id }} · {{ ticket.title }}</button>
        <p>市场用户 ID {{ ticket.user_id }} · 状态 {{ ticket.lifecycle_label || ticket.status }}（{{ ticket.status }}）</p>
      </section>
      <div class="header-actions">
        <button class="btn btn-secondary" :disabled="offset === 0" @click="load(offset - 50)">上一页</button>
        <span>共 {{ total }} 单 · 第 {{ Math.floor(offset / 50) + 1 }} 页</span>
        <button class="btn btn-secondary" :disabled="offset + 50 >= total" @click="load(offset + 50)">下一页</button>
      </div>
    </template>
    <section v-if="selectedId" class="panel" aria-label="客服原单详情">
      <h3>客服原单详情 · 内部 ID {{ selectedId }}</h3>
      <p v-if="detailLoading" role="status">正在读取原单证据…</p>
      <p v-else-if="detailError" role="alert" class="banner-error">{{ detailError }} <button @click="showTicket(selectedId)">重试详情</button></p>
      <template v-else-if="detail">
        <dl class="facts">
          <dt>完整客服编号</dt><dd>{{ detail.ticket.ticket_no }}</dd>
          <dt>市场用户 ID</dt><dd>{{ detail.ticket.user_id }}</dd>
          <dt>状态</dt><dd>{{ detail.ticket.lifecycle_label || detail.ticket.status }}（{{ detail.ticket.status }}）</dd>
          <dt>指派管理员 ID</dt><dd>{{ detail.ticket.assigned_admin_id || '暂无管理员指派记录' }}</dd>
          <dt>创建 / 最近更新</dt><dd>{{ detail.ticket.created_at }} / {{ detail.ticket.updated_at }}</dd>
        </dl>
        <h4>客户问题原文</h4><pre class="payload">{{ detail.ticket.summary || '原单未记录正文' }}</pre>
        <p class="muted">处理状态本身不代表员工已领取或执行；以以下真实进度和审计记录为准。</p>
        <h4>客户证据、领取与处理进度</h4><p class="muted">包含原单 resolution、附件索引、跟进与员工回写；不展开支持包二进制内容。</p><pre class="payload">{{ JSON.stringify(evidence, null, 2) }}</pre>
        <h4>决策记录</h4><pre class="payload">{{ format(detail.decisions) }}</pre>
        <h4>执行动作</h4><pre class="payload">{{ format(detail.actions) }}</pre>
        <h4>审计记录</h4><pre class="payload">{{ format(detail.audit_logs) }}</pre>
      </template>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { xcmaxAdminApi } from '@/api/xcmaxAdmin'

type Row = Record<string, unknown>
type Detail = { ticket: Row; decisions: Row[]; actions: Row[]; audit_logs: Row[] }
const search = ref(''), error = ref(''), detailError = ref('')
const tickets = ref<Row[]>([]), detail = ref<Detail | null>(null)
const loading = ref(false), loaded = ref(false), detailLoading = ref(false)
const offset = ref(0), total = ref(0), selectedId = ref(0)
let generation = 0
let appliedSearch = ''
const evidence = computed(() => Object.fromEntries(Object.entries(
  (detail.value?.ticket.evidence || {}) as Row,
).filter(([key]) => key !== 'support_bundle_base64')))
const format = (rows: unknown[]) => rows.length ? JSON.stringify(rows, null, 2) : '暂无记录'
const message = (cause: unknown) => cause instanceof Error ? cause.message : String(cause)

async function load(nextOffset: number, applySearch = false) {
  if (loading.value) return
  loading.value = true; error.value = ''; loaded.value = false
  selectedId.value = 0; detail.value = null; generation++
  try {
    const term = applySearch ? search.value.trim() : appliedSearch
    const result = await xcmaxAdminApi.fetchCustomerTickets(term, nextOffset)
    if (!Array.isArray(result.items) || !Number.isInteger(result.total) || result.total < 0) throw new Error('客服列表响应不完整')
    appliedSearch = term
    tickets.value = result.items; total.value = result.total; offset.value = nextOffset; loaded.value = true
  } catch (cause) { tickets.value = []; error.value = message(cause) }
  finally { loading.value = false }
}

async function showTicket(id: number) {
  const request = ++generation
  selectedId.value = id; detail.value = null; detailError.value = ''; detailLoading.value = true
  try {
    const result = await xcmaxAdminApi.fetchCustomerTicket(id)
    if (request !== generation) return
    if (Number(result.ticket?.id) !== id || !Array.isArray(result.decisions) || !Array.isArray(result.actions) || !Array.isArray(result.audit_logs)) throw new Error('客服详情响应不完整')
    detail.value = result as Detail
  } catch (cause) { if (request === generation) detailError.value = message(cause) }
  finally { if (request === generation) detailLoading.value = false }
}
onMounted(() => { void load(0) })
onBeforeUnmount(() => { generation++ })
</script>

<style scoped src="./ApprovalHubView.css"></style>
