<template>
  <div class="cs-page">
    <section class="cs-hero">
      <div>
        <p class="cs-kicker">XC AGI 独立 AI 客服平台</p>
        <h1>自动受理、审核、执行与追踪</h1>
        <p class="cs-subtitle">
          面向投诉申诉、订单退款、上架合规、账号权益和后续网页 API 对接。每一次自动处理都会生成工单、审核标准和审计记录。
        </p>
      </div>
      <div class="cs-hero__panel">
        <b>全自动能力</b>
        <span>低风险事项自动执行，高风险动作按审核标准和策略留痕处理。</span>
      </div>
    </section>

    <section class="cs-layout">
      <main class="cs-chat">
        <div class="cs-toolbar">
          <div>
            <b>客服对话</b>
            <span v-if="activeSessionId">会话 #{{ activeSessionId }}</span>
          </div>
          <button class="cs-btn cs-btn--ghost" @click="newSession">新会话</button>
        </div>

        <div class="cs-messages">
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
          <article v-if="messages.length === 0" class="cs-empty">
            <h3>可以直接描述问题</h3>
            <p>例如：“订单号 RF123456 想退款，原因是重复购买”，或“商品 ID 12 疑似抄袭，需要投诉”。</p>
          </article>
        </div>

        <form class="cs-composer" @submit.prevent="send">
          <textarea v-model="draft" placeholder="请输入你要处理的客服问题，尽量包含订单号、商品 ID、证据或期望结果。" />
          <div class="cs-composer__footer">
            <span>{{ error || 'AI 客服会自动识别场景并生成工单' }}</span>
            <button class="cs-btn" :disabled="loading || !draft.trim()">{{ loading ? '处理中...' : '发送给 AI 客服' }}</button>
          </div>
        </form>
      </main>

      <aside class="cs-side">
        <section class="cs-side-card">
          <h3>最近工单</h3>
          <button class="cs-btn cs-btn--ghost cs-btn--wide" @click="loadTickets">刷新</button>
          <div v-if="tickets.length === 0" class="cs-muted">暂无工单</div>
          <button
            v-for="ticket in tickets"
            :key="ticket.id"
            class="cs-ticket"
            @click="openTicket(ticket)"
          >
            <b>{{ ticket.title || ticket.ticket_no }}</b>
            <span>{{ ticket.status }} · {{ ticket.intent }}</span>
          </button>
        </section>

        <section class="cs-side-card">
          <h3>审核标准</h3>
          <div v-for="standard in standards" :key="standard.id" class="cs-standard">
            <b>{{ standard.name }}</b>
            <span>{{ standard.scenario }} · {{ standard.risk_level }}</span>
          </div>
        </section>
      </aside>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
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
    order_no: q.order_no || undefined,
    catalog_id: q.catalog_id ? Number(q.catalog_id) : undefined,
    pkg_id: q.pkg_id || undefined,
    item_name: q.item_name || undefined,
    complaint_type: q.complaint_type || undefined,
  }
}

async function send() {
  const text = draft.value.trim()
  if (!text || loading.value) return
  error.value = ''
  loading.value = true
  const userMsg: UiMessage = { id: `u-${Date.now()}`, role: 'user', content: text }
  messages.value.push(userMsg)
  draft.value = ''
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
    await loadTickets()
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
  } catch (e: any) {
    error.value = e?.message || '打开工单失败'
  }
}
</script>

<style scoped>
.cs-page {
  min-height: calc(100vh - var(--nav-h, 64px));
  padding: clamp(18px, 3vw, 42px);
  color: #fff;
  background:
    radial-gradient(circle at 10% 10%, rgba(255, 198, 92, 0.2), transparent 32%),
    radial-gradient(circle at 88% 18%, rgba(90, 170, 255, 0.18), transparent 36%),
    #080a0f;
}

.cs-hero,
.cs-layout {
  max-width: 1400px;
  margin: 0 auto;
}

.cs-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 24px;
  align-items: end;
  margin-bottom: 24px;
}

.cs-kicker {
  color: #f6c86d;
  font-weight: 800;
  letter-spacing: 0.12em;
}

.cs-hero h1 {
  font-size: clamp(34px, 6vw, 74px);
  line-height: 0.95;
  margin: 10px 0;
}

.cs-subtitle,
.cs-hero__panel span,
.cs-muted,
.cs-toolbar span,
.cs-standard span,
.cs-ticket span,
.cs-composer__footer span {
  color: rgba(255, 255, 255, 0.68);
}

.cs-hero__panel,
.cs-chat,
.cs-side-card {
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.06);
  border-radius: 28px;
  box-shadow: 0 24px 70px rgba(0, 0, 0, 0.28);
}

.cs-hero__panel {
  padding: 22px;
  display: grid;
  gap: 8px;
}

.cs-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 22px;
}

.cs-chat {
  min-height: 640px;
  display: grid;
  grid-template-rows: auto 1fr auto;
  overflow: hidden;
}

.cs-toolbar,
.cs-composer__footer {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.cs-toolbar {
  padding: 18px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.cs-messages {
  padding: 20px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.cs-message {
  display: flex;
}

.cs-message--user {
  justify-content: flex-end;
}

.cs-bubble,
.cs-empty {
  max-width: min(760px, 92%);
  padding: 16px;
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.12);
}

.cs-message--user .cs-bubble {
  background: linear-gradient(135deg, rgba(246, 200, 109, 0.28), rgba(86, 153, 255, 0.18));
}

.cs-composer {
  padding: 18px;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.cs-composer textarea {
  width: 100%;
  min-height: 112px;
  resize: vertical;
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 18px;
  background: rgba(0, 0, 0, 0.26);
  color: #fff;
  padding: 14px;
  outline: none;
}

.cs-composer__footer {
  margin-top: 12px;
}

.cs-btn {
  border: 0;
  border-radius: 999px;
  padding: 10px 16px;
  background: #f6c86d;
  color: #17130a;
  font-weight: 800;
  cursor: pointer;
}

.cs-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.cs-btn--ghost {
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
  border: 1px solid rgba(255, 255, 255, 0.12);
}

.cs-btn--wide {
  width: 100%;
  margin: 10px 0;
}

.cs-side {
  display: grid;
  gap: 16px;
  align-content: start;
}

.cs-side-card {
  padding: 18px;
}

.cs-ticket,
.cs-standard {
  width: 100%;
  display: grid;
  gap: 4px;
  text-align: left;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 16px;
  padding: 12px;
  margin-top: 10px;
  background: rgba(255, 255, 255, 0.06);
  color: #fff;
}

.cs-ticket {
  cursor: pointer;
}

@media (max-width: 980px) {
  .cs-hero,
  .cs-layout {
    grid-template-columns: 1fr;
  }
}

html[data-workbench-theme='light'] .cs-page {
  color: #1d1d1f;
  background: #f5f5f7;
}

html[data-workbench-theme='light'] .cs-kicker {
  color: #0071e3;
}

html[data-workbench-theme='light'] .cs-subtitle,
html[data-workbench-theme='light'] .cs-hero__panel span,
html[data-workbench-theme='light'] .cs-muted,
html[data-workbench-theme='light'] .cs-toolbar span,
html[data-workbench-theme='light'] .cs-standard span,
html[data-workbench-theme='light'] .cs-ticket span,
html[data-workbench-theme='light'] .cs-composer__footer span {
  color: #86868b;
}

html[data-workbench-theme='light'] .cs-hero__panel,
html[data-workbench-theme='light'] .cs-chat,
html[data-workbench-theme='light'] .cs-side-card {
  border-color: rgba(0, 0, 0, 0.08);
  background: #ffffff;
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.06);
}

html[data-workbench-theme='light'] .cs-toolbar {
  border-bottom-color: rgba(0, 0, 0, 0.08);
}

html[data-workbench-theme='light'] .cs-bubble,
html[data-workbench-theme='light'] .cs-empty {
  background: #ffffff;
  border-color: rgba(0, 0, 0, 0.08);
}

html[data-workbench-theme='light'] .cs-message--user .cs-bubble {
  background: rgba(0, 113, 227, 0.08);
  border-color: rgba(0, 113, 227, 0.12);
}

html[data-workbench-theme='light'] .cs-composer {
  border-top-color: rgba(0, 0, 0, 0.08);
}

html[data-workbench-theme='light'] .cs-composer textarea {
  border-color: rgba(0, 0, 0, 0.1);
  background: #ffffff;
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .cs-composer textarea::placeholder {
  color: #86868b;
}

html[data-workbench-theme='light'] .cs-btn {
  background: #0071e3;
  color: #fff;
}

html[data-workbench-theme='light'] .cs-btn--ghost {
  background: rgba(0, 0, 0, 0.04);
  color: #1d1d1f;
  border-color: rgba(0, 0, 0, 0.1);
}

html[data-workbench-theme='light'] .cs-ticket,
html[data-workbench-theme='light'] .cs-standard {
  border-color: rgba(0, 0, 0, 0.08);
  background: rgba(0, 0, 0, 0.02);
  color: #1d1d1f;
}
</style>
