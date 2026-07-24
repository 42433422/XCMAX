<template>
  <div class="cs-page">
    <header class="cs-head">
      <div class="cs-head__main">
        <h1>AI 客服</h1>
        <p>直接说问题就行；需要跟进时会帮你建工单，并在右侧显示进度</p>
      </div>
    </header>

    <section class="cs-layout">
      <main class="cs-chat">
        <div class="cs-toolbar">
          <div class="cs-toolbar__left">
            <b>对话</b>
            <span class="cs-muted">{{ activeSessionId ? '进行中' : '新会话' }}</span>
          </div>
          <button type="button" class="cs-btn cs-btn--ghost" @click="newSession">新会话</button>
        </div>

        <div ref="messagesEl" class="cs-messages">
          <article v-for="msg in messages" :key="msg.id" :class="['cs-message', `cs-message--${msg.role}`]">
            <div class="cs-bubble">
              <p
                v-if="msg.content && msg.content !== '[用户补充了图片资料]'"
                class="cs-bubble__text"
                v-html="renderCsBubbleHtml(msg.content)"
                @click="onBubbleClick($event, msg)"
              />
              <p v-else-if="msg.imageDataUrl" class="cs-bubble__text">已附上图片</p>
              <img
                v-if="msg.imageDataUrl"
                :src="msg.imageDataUrl"
                alt="补充图片"
                class="cs-bubble__img"
              />
            </div>
          </article>

          <div v-if="messages.length === 0" class="cs-empty">
            <p class="cs-empty__title">先说说你遇到的问题，也可以点下面的示例开始</p>
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
          <input
            ref="imageInputRef"
            type="file"
            accept="image/*"
            class="cs-image-input"
            @change="onImagePicked"
          />
          <div v-if="pendingImageDataUrl" class="cs-attach">
            <img :src="pendingImageDataUrl" alt="待发送图片预览" class="cs-attach__preview" />
            <button type="button" class="cs-link" @click="clearPendingImage">移除图片</button>
          </div>
          <p v-if="imagePickError" class="cs-error cs-attach-error">{{ imagePickError }}</p>
          <textarea
            v-model="draft"
            rows="2"
            placeholder="尽量带上订单号、说明；也可点「图片」上传截图补充材料…"
            @keydown.meta.enter.prevent="send"
            @keydown.ctrl.enter.prevent="send"
          />
          <div class="cs-composer__footer">
            <div class="cs-composer__left">
              <button
                type="button"
                class="cs-btn cs-btn--ghost"
                :disabled="loading || imagePicking"
                @click="openImagePicker"
              >
                {{ imagePicking ? '处理中…' : '图片' }}
              </button>
              <span :class="{ 'cs-error': !!error }">{{ error || 'Enter 换行 · ⌘/Ctrl+Enter 发送' }}</span>
            </div>
            <button
              type="submit"
              class="cs-btn"
              :disabled="loading || imagePicking || (!draft.trim() && !pendingImageDataUrl)"
            >
              {{ loading ? '处理中…' : '发送' }}
            </button>
          </div>
        </form>
      </main>

      <aside class="cs-side">
        <section class="cs-side-card cs-side-card--tickets">
          <div class="cs-side-card__head">
            <h3>我的工单 <small v-if="tickets.length">{{ tickets.length }}</small></h3>
            <div class="cs-side-card__actions">
              <button
                v-if="tickets.length"
                type="button"
                class="cs-link"
                @click="toggleAllTickets"
              >
                {{ allTicketsExpanded ? '全部收起' : '全部展开' }}
              </button>
              <button type="button" class="cs-link" @click="loadTickets">刷新</button>
            </div>
          </div>
          <p class="cs-side-lead">默认收起；点箭头看进度，点标题在对话里继续</p>
          <div v-if="tickets.length === 0" class="cs-side-empty">
            还没有工单。普通聊天不会建单；材料齐可自动受理，或点「提交工单」后会出现在这里。
          </div>
          <div v-else class="cs-side-list">
            <article
              v-for="ticket in tickets"
              :key="ticket.id"
              :class="['cs-ticket', { 'cs-ticket--open': isTicketExpanded(ticket.id) }]"
            >
              <div class="cs-ticket__row">
                <button
                  type="button"
                  class="cs-ticket__main"
                  @click="openTicket(ticket)"
                >
                  <b>{{ friendlyTicketTitle(ticket) }}</b>
                  <span
                    v-if="issueDomainLabel(ticket)"
                    class="cs-ticket__domain"
                  >{{ issueDomainLabel(ticket) }}</span>
                  <span class="cs-ticket__stage">{{ ticketLifecycleLabel(ticket) }}</span>
                </button>
                <button
                  type="button"
                  class="cs-ticket__toggle"
                  :aria-expanded="isTicketExpanded(ticket.id)"
                  :aria-label="isTicketExpanded(ticket.id) ? '收起进度' : '展开进度'"
                  @click.stop="toggleTicket(ticket.id)"
                >
                  {{ isTicketExpanded(ticket.id) ? '▴' : '▾' }}
                </button>
              </div>
              <div v-if="isTicketExpanded(ticket.id)" class="cs-ticket__body">
                <span class="cs-ticket__meta">{{ shortTicketRef(ticket) }}</span>
                <p class="cs-ticket__hint">{{ ticketLifecycleHint(ticket) }}</p>
                <ol class="cs-life" aria-label="工单进度">
                  <li
                    v-for="step in ticketLifecycleSteps(ticket)"
                    :key="step.stage"
                    :class="['cs-life__item', `cs-life__item--${step.state}`]"
                    :title="step.label"
                  >
                    <i class="cs-life__dot" />
                    <em>{{ shortLifeLabel(step.label) }}</em>
                  </li>
                </ol>
              </div>
            </article>
          </div>
        </section>
      </aside>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api'
import { renderCsBubbleHtml } from '../utils/csBubbleText'
import {
  issueDomainLabel,
  shortTicketRef,
  ticketIntentLabel,
  ticketLifecycleHint,
  ticketLifecycleLabel,
  ticketLifecycleSteps,
} from '../utils/csTicketLifecycle'
import { composeTicketUserMessage, toUserFacingCards } from '../utils/csTicketSummary'
import { compressImageFileToDataUrl, isImageFileForVision } from '../utils/visionMultimodal'

type UiMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  cards?: Record<string, any>[]
  imageDataUrl?: string | null
}

const route = useRoute()
const draft = ref('')
const loading = ref(false)
const error = ref('')
const activeSessionId = ref<number | null>(null)
const messages = ref<UiMessage[]>([])
const tickets = ref<any[]>([])
const expandedTicketIds = ref<Set<number>>(new Set())
const messagesEl = ref<HTMLElement | null>(null)
const pendingImageDataUrl = ref<string | null>(null)
const imagePickError = ref('')
const imagePicking = ref(false)
const imageInputRef = ref<HTMLInputElement | null>(null)

const allTicketsExpanded = computed(
  () => tickets.value.length > 0 && expandedTicketIds.value.size >= tickets.value.length,
)

const quickPrompts = [
  '你好，想了解一下会员怎么买',
  '退款一般需要提供哪些信息？',
  '商品有问题想先了解怎么投诉',
  '账号权益没到账是怎么回事',
]

onMounted(() => {
  hydrateFromQuery()
  void loadTickets()
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
    // 账号定制线（宿主入门第三步）：定制功能 Mod / 定制员工
    artifact: q.artifact || undefined,
    account_custom: q.account_custom || undefined,
  }
}

function usePrompt(text: string) {
  draft.value = text
}

function shortLifeLabel(label: string) {
  const map: Record<string, string> = {
    已收到: '收到',
    处理中: '处理',
    有结果: '结果',
    待补充: '补充',
    已完成: '完成',
    工单排队: '收到',
    工单处理: '处理',
    结果汇报: '结果',
    继续提交: '补充',
    结果回访: '完成',
  }
  return map[label] || label
}

function friendlyTicketTitle(ticket: any) {
  const intent = ticketIntentLabel(ticket?.intent)
  const title = String(ticket?.title || '').trim()
  if (title && !title.includes('CS') && title.length <= 18) return title
  return intent === '咨询' ? '咨询跟进' : `${intent}跟进`
}

function isTicketExpanded(id: unknown) {
  return expandedTicketIds.value.has(Number(id))
}

function toggleTicket(id: unknown) {
  const n = Number(id)
  if (!n) return
  const next = new Set(expandedTicketIds.value)
  if (next.has(n)) next.delete(n)
  else next.add(n)
  expandedTicketIds.value = next
}

function toggleAllTickets() {
  if (allTicketsExpanded.value) {
    expandedTicketIds.value = new Set()
    return
  }
  expandedTicketIds.value = new Set(
    tickets.value.map((t) => Number(t.id)).filter((n) => n > 0),
  )
}

function preferExpandWaitingTickets(items: any[]) {
  const waiting = items
    .filter((t) => ticketLifecycleLabel(t) === '待补充')
    .map((t) => Number(t.id))
    .filter((n) => n > 0)
  // 默认全收起；仅自动展开一条「待补充」，避免刷屏
  expandedTicketIds.value = new Set(waiting.slice(0, 1))
}

async function scrollMessagesToEnd() {
  await nextTick()
  const el = messagesEl.value
  if (el) el.scrollTop = el.scrollHeight
}

function onBubbleClick(ev: MouseEvent, msg: UiMessage) {
  if (msg.role !== 'assistant') return
  const target = ev.target as HTMLElement | null
  const link = target?.closest?.('[data-cs-action]') as HTMLElement | null
  if (!link) return
  ev.preventDefault()
  const action = String(link.getAttribute('data-cs-action') || '')
  if (action === 'submit-ticket') {
    const lastUser = [...messages.value]
      .reverse()
      .find((m) => m.role === 'user' && String(m.content || '').trim() && m.content !== '提交工单')
    void sendText('提交工单', {
      reason: String(lastUser?.content || '').trim() || undefined,
    })
  }
}

function openImagePicker() {
  imagePickError.value = ''
  const input = imageInputRef.value
  if (!input) return
  input.value = ''
  input.click()
}

function clearPendingImage() {
  pendingImageDataUrl.value = null
  imagePickError.value = ''
  if (imageInputRef.value) imageInputRef.value.value = ''
}

async function onImagePicked(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  imagePickError.value = ''
  if (!isImageFileForVision(file)) {
    imagePickError.value = '请选择图片文件（png/jpg/webp 等）'
    input.value = ''
    return
  }
  imagePicking.value = true
  try {
    pendingImageDataUrl.value = await compressImageFileToDataUrl(file, {
      maxEdge: 1600,
      maxBytes: 2.5 * 1024 * 1024,
    })
  } catch (e: unknown) {
    pendingImageDataUrl.value = null
    imagePickError.value = e instanceof Error ? e.message : '图片处理失败'
  } finally {
    imagePicking.value = false
    input.value = ''
  }
}

async function send() {
  await sendText(draft.value.trim())
}

async function sendText(raw: string, extras?: { reason?: string }) {
  const text = String(raw || '').trim()
  const imageDataUrl = pendingImageDataUrl.value
  if ((!text && !imageDataUrl) || loading.value || imagePicking.value) return
  error.value = ''
  loading.value = true
  const userMsg: UiMessage = {
    id: `u-${Date.now()}`,
    role: 'user',
    content: text || '[用户补充了图片资料]',
    imageDataUrl: imageDataUrl || null,
  }
  messages.value.push(userMsg)
  draft.value = ''
  clearPendingImage()
  await scrollMessagesToEnd()
  try {
    const ctx = {
      ...queryContext(),
      ...(extras?.reason ? { reason: extras.reason } : {}),
    }
    const res: any = await api.customerServiceChat({
      message: text,
      session_id: activeSessionId.value,
      context: ctx,
      image_data_url: imageDataUrl || undefined,
    })
    activeSessionId.value = Number(res?.session?.id || activeSessionId.value || 0) || null
    // 对话里只用白话正文；不再堆「进度/下一步/已办理」多卡
    let content = String(res?.message?.content || '已处理。')
    if (res?.ticket) {
      const fromCards = Array.isArray(res?.cards) ? res.cards : []
      const decisionCard = fromCards.find((c: any) => c?.type === 'decision')
      const actionsCard = fromCards.find((c: any) => c?.type === 'actions')
      const composed = composeTicketUserMessage({
        ticket: res.ticket,
        decision: decisionCard || res.decision || null,
        actions: Array.isArray(actionsCard?.items)
          ? actionsCard.items
          : Array.isArray(res?.actions)
            ? res.actions
            : [],
      })
      const st = String(res.ticket?.status || '').toLowerCase()
      // 已结案用侧栏口径摘要；跟进中优先后端话术（含问题复述），避免盖成「已处理完成」
      if (['resolved', 'closed', 'done', 'rejected'].includes(st)) {
        content = composed
      } else if (!content || content === '已处理。') {
        content = composed
      }
    }
    messages.value.push({
      id: `a-${Date.now()}`,
      role: 'assistant',
      content,
      cards: [],
    })
    // 先结束「处理中」，侧栏刷新失败/慢不得挡住对话
    loading.value = false
    if (res?.ticket) {
      void loadTickets()
    }
    await scrollMessagesToEnd()
  } catch (e: any) {
    error.value = e?.message || 'AI 客服处理失败'
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
    preferExpandWaitingTickets(tickets.value)
  } catch {
    tickets.value = []
    expandedTicketIds.value = new Set()
  }
}

function visibleCards(msg: UiMessage) {
  return toUserFacingCards(Array.isArray(msg.cards) ? msg.cards : [])
}

async function openTicket(ticket: any) {
  const tid = Number(ticket?.id || 0)
  if (tid) {
    const next = new Set(expandedTicketIds.value)
    next.add(tid)
    expandedTicketIds.value = next
  }
  try {
    const res: any = await api.customerServiceTicketDetail(ticket.id)
    const t = res?.ticket || ticket
    const decision = Array.isArray(res?.decisions) && res.decisions[0] ? res.decisions[0] : null
    const actions = Array.isArray(res?.actions) ? res.actions : []
    messages.value.push({
      id: `t-${Date.now()}`,
      role: 'assistant',
      content: composeTicketUserMessage({ ticket: t, decision, actions }),
      cards: [],
    })
    await scrollMessagesToEnd()
  } catch (e: any) {
    error.value = e?.message || '打开进度失败'
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
  grid-template-columns: minmax(0, 1fr) minmax(260px, 320px);
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

.cs-bubble p,
.cs-bubble__text {
  margin: 0;
  font-size: 0.92rem;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.cs-action-link {
  color: var(--cs-accent, #2563eb);
  font-weight: 650;
  text-decoration: underline;
  text-underline-offset: 2px;
  cursor: pointer;
}

.cs-action-link:hover {
  filter: brightness(0.92);
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

.cs-composer__left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex: 1 1 auto;
}

.cs-composer__footer span {
  font-size: 0.76rem;
  color: var(--cs-muted);
}

.cs-image-input {
  display: none;
}

.cs-attach {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.cs-attach__preview,
.cs-bubble__img {
  display: block;
  max-width: min(220px, 70%);
  max-height: 160px;
  border-radius: 10px;
  border: 1px solid var(--cs-border);
  object-fit: cover;
  background: color-mix(in srgb, var(--wb-text-primary, #1d1d1f) 4%, transparent);
}

.cs-bubble__img {
  margin-top: 8px;
}

.cs-attach-error {
  margin: 0 0 8px;
  font-size: 0.76rem;
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
  display: flex;
  flex-direction: column;
}

.cs-side-card {
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 12px;
  overflow: hidden;
}

.cs-side-card--tickets {
  flex: 1 1 auto;
}

.cs-side-card__head h3 {
  margin: 0;
  font-size: 0.9rem;
  font-weight: 700;
}

.cs-side-card__head h3 small {
  margin-left: 4px;
  font-size: 0.72rem;
  font-weight: 650;
  color: var(--cs-muted);
}

.cs-side-card__actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.cs-side-lead {
  margin: 6px 0 0;
  color: var(--cs-muted);
  font-size: 0.76rem;
  line-height: 1.4;
}

.cs-side-list {
  margin-top: 10px;
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
  line-height: 1.45;
}

.cs-ticket {
  width: 100%;
  display: grid;
  gap: 0;
  text-align: left;
  border: 1px solid var(--cs-border);
  border-radius: 10px;
  padding: 0;
  background: color-mix(in srgb, var(--wb-text-primary, #1d1d1f) 2.5%, transparent);
  color: inherit;
  overflow: hidden;
}

.cs-ticket:hover,
.cs-ticket--open {
  border-color: color-mix(in srgb, var(--cs-accent) 35%, transparent);
}

.cs-ticket__row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 32px;
  align-items: stretch;
}

.cs-ticket__main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
  padding: 9px 10px;
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
  text-align: left;
  font: inherit;
}

.cs-ticket__main:hover {
  background: color-mix(in srgb, var(--cs-accent) 6%, transparent);
}

.cs-ticket__toggle {
  border: 0;
  border-left: 1px solid var(--cs-border);
  background: transparent;
  color: var(--cs-muted);
  cursor: pointer;
  font-size: 0.78rem;
  line-height: 1;
}

.cs-ticket__toggle:hover {
  color: var(--cs-accent);
  background: color-mix(in srgb, var(--cs-accent) 6%, transparent);
}

.cs-ticket b {
  font-size: 0.84rem;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cs-ticket__domain {
  flex: 0 0 auto;
  padding: 2px 7px;
  border-radius: 999px;
  font-size: 0.68rem;
  font-weight: 700;
  font-style: normal;
  color: var(--cs-ink-soft, #5b6472);
  background: color-mix(in srgb, var(--cs-ink-soft, #5b6472) 10%, transparent);
}

.cs-ticket__stage {
  flex: 0 0 auto;
  padding: 2px 7px;
  border-radius: 999px;
  font-size: 0.68rem;
  font-weight: 700;
  font-style: normal;
  color: var(--cs-accent);
  background: color-mix(in srgb, var(--cs-accent) 12%, transparent);
}

.cs-ticket__body {
  display: grid;
  gap: 6px;
  padding: 0 10px 10px;
  border-top: 1px solid var(--cs-border);
  padding-top: 8px;
}

.cs-ticket__meta {
  color: var(--cs-muted);
  font-size: 0.74rem;
}

.cs-ticket__hint {
  margin: 0;
  font-size: 0.74rem;
  line-height: 1.35;
  color: color-mix(in srgb, var(--wb-text-primary, #1d1d1f) 78%, transparent);
}

.cs-life {
  list-style: none;
  margin: 2px 0 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 2px;
}

.cs-life__item {
  display: grid;
  justify-items: center;
  gap: 3px;
  min-width: 0;
  position: relative;
}

.cs-life__item:not(:last-child)::after {
  content: '';
  position: absolute;
  top: 4px;
  left: calc(50% + 5px);
  right: calc(-50% + 5px);
  height: 1px;
  background: color-mix(in srgb, var(--wb-text-primary, #1d1d1f) 12%, transparent);
}

.cs-life__item--done:not(:last-child)::after,
.cs-life__item--current:not(:last-child)::after {
  background: color-mix(in srgb, var(--cs-accent) 55%, transparent);
}

.cs-life__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: color-mix(in srgb, var(--wb-text-primary, #1d1d1f) 18%, transparent);
  position: relative;
  z-index: 1;
}

.cs-life__item--done .cs-life__dot {
  background: var(--cs-accent);
}

.cs-life__item--current .cs-life__dot {
  background: var(--cs-accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--cs-accent) 22%, transparent);
}

.cs-life__item em {
  font-style: normal;
  font-size: 0.62rem;
  line-height: 1.1;
  color: var(--cs-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.cs-life__item--current em {
  color: var(--cs-accent);
  font-weight: 700;
}

.cs-life__item--done em {
  color: color-mix(in srgb, var(--wb-text-primary, #1d1d1f) 72%, transparent);
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

  .cs-side-card--tickets {
    max-height: 320px;
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
html:not([data-workbench-theme='light']) .cs-side-empty {
  background: rgba(255, 255, 255, 0.04);
  color: #f2f2f7;
}

html:not([data-workbench-theme='light']) .cs-btn--ghost {
  color: #f2f2f7;
}
</style>
