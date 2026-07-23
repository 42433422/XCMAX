<template>
  <div class="cs-page">
    <header class="cs-head">
      <div class="cs-head__main">
        <h1>AI 客服</h1>
        <p>先对话识别意图；退款/投诉等业务或你说「提交工单」时再自动建单</p>
      </div>
      <div class="cs-head__meta">
        <span class="cs-pill">意图识别</span>
        <span class="cs-pill cs-pill--soft">按需建单</span>
      </div>
    </header>

    <section class="cs-layout">
      <main class="cs-chat">
        <div class="cs-toolbar">
          <div class="cs-toolbar__left">
            <b>对话</b>
            <span v-if="activeSessionId">#{{ activeSessionId }}</span>
            <span v-else class="cs-muted">新会话</span>
          </div>
          <button type="button" class="cs-btn cs-btn--ghost" @click="newSession">新会话</button>
        </div>

        <div ref="messagesEl" class="cs-messages">
          <article v-for="msg in messages" :key="msg.id" :class="['cs-message', `cs-message--${msg.role}`]">
            <div class="cs-bubble">
              <p>{{ msg.content }}</p>
              <CustomerServiceActionCard
                v-for="(card, idx) in msg.cards || []"
                :key="`${msg.id}-${idx}`"
                :card="card"
              />
            </div>
          </article>

          <div v-if="messages.length === 0" class="cs-empty">
            <p class="cs-empty__title">先描述问题，AI 会识别意图；需要受理时再建工单</p>
            <div class="cs-chips">
              <button
                v-for="chip in quickPrompts"
                :key="chip"
                type="button"
                class="cs-chip"
                @click="usePrompt(chip)"
              >
                {{ chip }}
              </button>
            </div>
          </div>
        </div>

        <form class="cs-composer" @submit.prevent="send">
          <textarea
            v-model="draft"
            rows="2"
            placeholder="尽量带上订单号、商品 ID、证据或期望结果…"
            @keydown.meta.enter.prevent="send"
            @keydown.ctrl.enter.prevent="send"
          />
          <div class="cs-composer__footer">
            <span :class="{ 'cs-error': !!error }">{{ error || 'Enter 换行 · ⌘/Ctrl+Enter 发送' }}</span>
            <button type="submit" class="cs-btn" :disabled="loading || !draft.trim()">
              {{ loading ? '处理中…' : '发送' }}
            </button>
          </div>
        </form>
      </main>

      <aside class="cs-side">
        <section class="cs-side-card">
          <div class="cs-side-card__head">
            <h3>最近工单</h3>
            <button type="button" class="cs-link" @click="loadTickets">刷新</button>
          </div>
          <div v-if="tickets.length === 0" class="cs-side-empty">暂无工单；普通咨询不会自动建单</div>
          <div v-else class="cs-side-list">
            <button
              v-for="ticket in tickets"
              :key="ticket.id"
              type="button"
              class="cs-ticket"
              @click="openTicket(ticket)"
            >
              <b>{{ ticket.title || ticket.ticket_no }}</b>
              <span>{{ statusLabel(ticket.status) }} · {{ ticket.intent || 'general' }}</span>
            </button>
          </div>
        </section>

        <section class="cs-side-card cs-side-card--grow">
          <div class="cs-side-card__head">
            <h3>审核标准</h3>
            <span class="cs-muted">{{ standards.length }} 条</span>
          </div>
          <div v-if="standards.length === 0" class="cs-side-empty">尚未配置标准，管理员可在后台添加</div>
          <div v-else class="cs-side-list">
            <div v-for="standard in standards" :key="standard.id" class="cs-standard">
              <b>{{ standard.name }}</b>
              <span>{{ standard.scenario }} · {{ riskLabel(standard.risk_level) }}</span>
            </div>
          </div>
        </section>
      </aside>
    </section>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api'
import CustomerServiceActionCard from '../components/customer-service/CustomerServiceActionCard.vue'

type UiMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  cards?: Record<string, any>[]
}

const route = useRoute()
const draft = ref('')
const loading = ref(false)
const error = ref('')
const activeSessionId = ref<number | null>(null)
const messages = ref<UiMessage[]>([])
const tickets = ref<any[]>([])
const standards = ref<any[]>([])
const messagesEl = ref<HTMLElement | null>(null)

const quickPrompts = [
  '你好，想了解一下会员怎么买',
  '订单号 RF123456 想退款，原因是重复购买',
  '商品 ID 12 疑似抄袭，需要投诉',
  '账号权益未到账，请核查开通状态',
]

onMounted(() => {
  hydrateFromQuery()
  void Promise.all([loadTickets(), loadStandards()])
})

function hydrateFromQuery() {
  const q = route.query || {}
  const parts = []
  if (q.order_no) parts.push(`订单号：${q.order_no}`)
  if (q.catalog_id) parts.push(`商品 ID：${q.catalog_id}`)
  if (q.item_name) parts.push(`商品名称：${q.item_name}`)
  if (q.complaint_type) parts.push(`问题类型：${q.complaint_type}`)
  if (parts.length) draft.value = `${parts.join('\n')}\n请帮我自动受理并给出处理结果。`
}

function queryContext() {
  const q = route.query || {}
  return {
    channel: 'web',
    scene: q.scene || undefined,
    order_no: q.order_no || undefined,
    catalog_id: q.catalog_id ? Number(q.catalog_id) : undefined,
    pkg_id: q.pkg_id || undefined,
    item_name: q.item_name || undefined,
    complaint_type: q.complaint_type || undefined,
  }
}

function usePrompt(text: string) {
  draft.value = text
}

function statusLabel(status: unknown) {
  const s = String(status || '').toLowerCase()
  if (s === 'open' || s === 'pending') return '处理中'
  if (s === 'resolved' || s === 'done' || s === 'closed') return '已完成'
  if (s === 'rejected') return '已驳回'
  return status ? String(status) : '待处理'
}

function riskLabel(level: unknown) {
  const s = String(level || '').toLowerCase()
  if (s === 'high') return '高风险'
  if (s === 'medium' || s === 'mid') return '中风险'
  if (s === 'low') return '低风险'
  return level ? String(level) : '常规'
}

async function scrollMessagesToEnd() {
  await nextTick()
  const el = messagesEl.value
  if (el) el.scrollTop = el.scrollHeight
}

async function send() {
  const text = draft.value.trim()
  if (!text || loading.value) return
  error.value = ''
  loading.value = true
  const userMsg: UiMessage = { id: `u-${Date.now()}`, role: 'user', content: text }
  messages.value.push(userMsg)
  draft.value = ''
  await scrollMessagesToEnd()
  try {
    const res: any = await api.customerServiceChat({
      message: text,
      session_id: activeSessionId.value,
      context: queryContext(),
    })
    activeSessionId.value = Number(res?.session?.id || activeSessionId.value || 0) || null
    messages.value.push({
      id: `a-${Date.now()}`,
      role: 'assistant',
      content: String(res?.message?.content || '已处理。'),
      cards: Array.isArray(res?.cards) ? res.cards : [],
    })
    if (res?.ticket) {
      await loadTickets()
    }
    await scrollMessagesToEnd()
  } catch (e: any) {
    error.value = e?.message || 'AI 客服处理失败'
  } finally {
    loading.value = false
  }
}

function newSession() {
  activeSessionId.value = null
  messages.value = []
  error.value = ''
}

async function loadTickets() {
  try {
    const res: any = await api.customerServiceTickets()
    tickets.value = Array.isArray(res?.items) ? res.items : []
  } catch {
    tickets.value = []
  }
}

async function loadStandards() {
  try {
    const res: any = await api.customerServiceStandards()
    standards.value = Array.isArray(res?.items) ? res.items : []
  } catch {
    standards.value = []
  }
}

async function openTicket(ticket: any) {
  try {
    const res: any = await api.customerServiceTicketDetail(ticket.id)
    const cards = [
      { type: 'ticket', ...(res?.ticket || ticket) },
      ...(Array.isArray(res?.decisions) && res.decisions[0] ? [{ type: 'decision', ...res.decisions[0] }] : []),
      ...(Array.isArray(res?.actions) && res.actions.length ? [{ type: 'actions', items: res.actions }] : []),
    ]
    messages.value.push({
      id: `t-${Date.now()}`,
      role: 'assistant',
      content: `已打开工单 ${ticket.ticket_no || ticket.id} 的最新处理记录。`,
      cards,
    })
    await scrollMessagesToEnd()
  } catch (e: any) {
    error.value = e?.message || '打开工单失败'
  }
}
</script>

<style scoped>
.cs-page {
  --cs-border: color-mix(in srgb, var(--wb-text-primary, #1d1d1f) 10%, transparent);
  --cs-surface: var(--wb-surface-elevated, #fff);
  --cs-muted: var(--wb-text-secondary, #6e6e73);
  --cs-accent: var(--wb-accent-primary, #0071e3);
  --cs-bg: var(--wb-bg, #f5f5f7);
  box-sizing: border-box;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px 18px 18px;
  color: var(--wb-text-primary, #1d1d1f);
  background: var(--cs-bg);
}

.cs-head {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  max-width: 1280px;
  width: 100%;
  margin: 0 auto;
}

.cs-head__main h1 {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 750;
  letter-spacing: -0.02em;
  line-height: 1.2;
}

.cs-head__main p {
  margin: 4px 0 0;
  font-size: 0.84rem;
  color: var(--cs-muted);
  line-height: 1.35;
}

.cs-head__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: flex-end;
}

.cs-pill {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 700;
  background: color-mix(in srgb, var(--cs-accent) 14%, transparent);
  color: var(--cs-accent);
}

.cs-pill--soft {
  background: color-mix(in srgb, var(--wb-text-primary, #1d1d1f) 6%, transparent);
  color: var(--cs-muted);
}

.cs-layout {
  flex: 1 1 auto;
  min-height: 0;
  max-width: 1280px;
  width: 100%;
  margin: 0 auto;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(240px, 300px);
  gap: 14px;
}

.cs-chat,
.cs-side-card {
  border: 1px solid var(--cs-border);
  background: var(--cs-surface);
  border-radius: 14px;
}

.cs-chat {
  min-height: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  overflow: hidden;
}

.cs-toolbar,
.cs-composer__footer,
.cs-side-card__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}

.cs-toolbar {
  padding: 10px 14px;
  border-bottom: 1px solid var(--cs-border);
}

.cs-toolbar__left {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}

.cs-toolbar__left b {
  font-size: 0.95rem;
}

.cs-muted {
  color: var(--cs-muted);
  font-size: 0.78rem;
}

.cs-messages {
  min-height: 0;
  padding: 14px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.cs-message {
  display: flex;
}

.cs-message--user {
  justify-content: flex-end;
}

.cs-bubble {
  max-width: min(640px, 92%);
  padding: 10px 12px;
  border-radius: 14px;
  background: color-mix(in srgb, var(--wb-text-primary, #1d1d1f) 4%, transparent);
  border: 1px solid var(--cs-border);
}

.cs-bubble p {
  margin: 0;
  font-size: 0.92rem;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.cs-message--user .cs-bubble {
  background: color-mix(in srgb, var(--cs-accent) 10%, transparent);
  border-color: color-mix(in srgb, var(--cs-accent) 18%, transparent);
}

.cs-empty {
  margin: auto 0;
  padding: 8px 4px 18px;
}

.cs-empty__title {
  margin: 0 0 12px;
  font-size: 0.95rem;
  font-weight: 650;
  color: var(--wb-text-primary, #1d1d1f);
}

.cs-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.cs-chip {
  border: 1px solid var(--cs-border);
  background: color-mix(in srgb, var(--wb-text-primary, #1d1d1f) 3%, transparent);
  color: var(--wb-text-primary, #1d1d1f);
  border-radius: 999px;
  padding: 7px 12px;
  font-size: 0.8rem;
  line-height: 1.3;
  text-align: left;
  cursor: pointer;
  max-width: 100%;
}

.cs-chip:hover {
  border-color: color-mix(in srgb, var(--cs-accent) 40%, transparent);
  background: color-mix(in srgb, var(--cs-accent) 8%, transparent);
}

.cs-composer {
  padding: 12px 14px 14px;
  border-top: 1px solid var(--cs-border);
  background: color-mix(in srgb, var(--wb-text-primary, #1d1d1f) 2%, transparent);
}

.cs-composer textarea {
  width: 100%;
  min-height: 64px;
  max-height: 160px;
  resize: vertical;
  border: 1px solid var(--cs-border);
  border-radius: 12px;
  background: var(--cs-surface);
  color: var(--wb-text-primary, #1d1d1f);
  padding: 10px 12px;
  outline: none;
  font: inherit;
  line-height: 1.45;
}

.cs-composer textarea:focus {
  border-color: color-mix(in srgb, var(--cs-accent) 55%, transparent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--cs-accent) 16%, transparent);
}

.cs-composer__footer {
  margin-top: 8px;
}

.cs-composer__footer span {
  font-size: 0.76rem;
  color: var(--cs-muted);
}

.cs-error {
  color: #c9342d !important;
}

.cs-btn {
  border: 0;
  border-radius: 10px;
  padding: 8px 14px;
  background: var(--cs-accent);
  color: #fff;
  font-weight: 700;
  font-size: 0.86rem;
  cursor: pointer;
  white-space: nowrap;
}

.cs-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.cs-btn--ghost {
  background: transparent;
  color: var(--wb-text-primary, #1d1d1f);
  border: 1px solid var(--cs-border);
}

.cs-link {
  border: 0;
  background: transparent;
  color: var(--cs-accent);
  font-size: 0.78rem;
  font-weight: 650;
  cursor: pointer;
  padding: 0;
}

.cs-side {
  min-height: 0;
  display: grid;
  grid-template-rows: minmax(0, 1fr) minmax(0, 1fr);
  gap: 12px;
}

.cs-side-card {
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 12px;
  overflow: hidden;
}

.cs-side-card__head h3 {
  margin: 0;
  font-size: 0.9rem;
  font-weight: 700;
}

.cs-side-list {
  margin-top: 8px;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.cs-side-empty {
  margin-top: 10px;
  padding: 12px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--wb-text-primary, #1d1d1f) 3%, transparent);
  color: var(--cs-muted);
  font-size: 0.8rem;
  line-height: 1.4;
}

.cs-ticket,
.cs-standard {
  width: 100%;
  display: grid;
  gap: 3px;
  text-align: left;
  border: 1px solid var(--cs-border);
  border-radius: 10px;
  padding: 10px;
  background: color-mix(in srgb, var(--wb-text-primary, #1d1d1f) 2.5%, transparent);
  color: inherit;
}

.cs-ticket {
  cursor: pointer;
}

.cs-ticket:hover {
  border-color: color-mix(in srgb, var(--cs-accent) 35%, transparent);
}

.cs-ticket b,
.cs-standard b {
  font-size: 0.84rem;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cs-ticket span,
.cs-standard span {
  color: var(--cs-muted);
  font-size: 0.74rem;
}

@media (max-width: 980px) {
  .cs-page {
    height: auto;
    min-height: 100%;
  }

  .cs-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .cs-layout {
    grid-template-columns: 1fr;
  }

  .cs-chat {
    min-height: min(62vh, 560px);
  }

  .cs-side {
    grid-template-rows: auto;
  }

  .cs-side-card {
    max-height: 260px;
  }
}

/* 深色主题回落（未走 light token 时） */
html:not([data-workbench-theme='light']) .cs-page {
  --cs-bg: #0c0d12;
  --cs-surface: rgba(255, 255, 255, 0.05);
  --cs-border: rgba(255, 255, 255, 0.12);
  --cs-muted: rgba(255, 255, 255, 0.62);
  --cs-accent: #7aa7ff;
  color: #f2f2f7;
}

html:not([data-workbench-theme='light']) .cs-composer {
  background: rgba(0, 0, 0, 0.18);
}

html:not([data-workbench-theme='light']) .cs-composer textarea,
html:not([data-workbench-theme='light']) .cs-chip,
html:not([data-workbench-theme='light']) .cs-ticket,
html:not([data-workbench-theme='light']) .cs-standard,
html:not([data-workbench-theme='light']) .cs-side-empty {
  background: rgba(255, 255, 255, 0.04);
  color: #f2f2f7;
}

html:not([data-workbench-theme='light']) .cs-btn--ghost {
  color: #f2f2f7;
}
</style>
