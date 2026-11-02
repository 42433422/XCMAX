<template>
  <div class="chat-messages-shell">
    <nav v-if="messages.length > CHAT_HISTORY_WINDOW" class="chat-history-navigation" aria-label="聊天历史分页">
      <button type="button" :disabled="windowStart === 0" @click="moveWindow(-1)">更早消息</button>
      <span role="status">第 {{ windowStart + 1 }}–{{ windowEnd }} 条，共 {{ messages.length }} 条</span>
      <button type="button" :disabled="windowEnd === messages.length" @click="moveWindow(1)">较新消息</button>
      <button type="button" @click="showLatest">最新消息</button>
    </nav>
    <div class="chat-messages" id="chatMessages" ref="messagesHostRef" role="list" aria-label="聊天消息"
      @scroll.passive="onScroll" @xcagi-reveal-chat-message="revealMessage">
      <div v-if="!messages.length && !isLoading" class="message ai chat-welcome" role="listitem">
        <h2>开始新的对话</h2>
        <p>{{ emptyIntro || '你可以描述问题、查询资料，或说明需要协助的业务任务。' }}</p>
        <p>可用能力以当前配置为准。点击示例只填入输入框，请检查后发送。</p>
        <button type="button" class="btn btn-secondary" @click="$emit('fill-example', '请用一句话介绍你能做什么。仅回答，不执行操作。')">试试：介绍你能做什么</button>
      </div>
      <div
        v-for="{ msg, idx } in visibleMessages"
        :key="presentation(msg).key"
        :data-message-index="idx"
        role="listitem"
        :aria-posinset="idx + 1"
        :aria-setsize="messages.length"
        :class="['message', msg.role]"
        :style="{ minHeight: !isMessageCollapsed(msg, idx) && messageHeights.get(idx) ? messageHeights.get(idx) + 'px' : 'auto' }"
      >
        <CollapsedMessagePreview
          v-if="isMessageCollapsed(msg, idx)"
          :preview="messagePreview(msg)"
          expand-label="展开详情"
          @expand="$emit('expand-message', idx)"
        />
        <template v-else>
          <ChatTypingIndicator v-if="msg.role === 'ai' && msg.streamingShell" label="正在思考…" show-elapsed />
          <AgentRunTrace
            v-if="msg.role === 'ai' && hasOrchestrationTrace(msg)"
            :trace="orchestrationTraceFor(msg)"
            @auto-approve-tool="approveMessage(msg)"
          />
          <div v-if="waitingRunId(msg)" class="run-approve-row">
            <button type="button" class="run-approve-btn" data-testid="chat-run-approve" @click="$emit('approve-run', waitingRunId(msg))">
              确认执行
            </button>
          </div>
          <div v-if="msg.role === 'ai' && shouldCondenseOrchestrationBody(msg)" class="message-orchestration-intro">
            执行计划已整理为任务编排，展开卡片可查看工具、步骤和运行详情。
          </div>
          <div
            v-else
            class="message-html"
            v-html="messageHtml(msg)"
          ></div>
          <details
            v-if="msg.role === 'ai' && !hasOrchestrationTrace(msg) && (msg.toolProgressLabel || msg.executionProgress?.length)"
            class="execution-timeline"
          >
            <summary>
              <i v-if="msg.streamingShell" class="fa fa-spinner fa-spin execution-timeline__spinner" aria-hidden="true"></i>
              <span class="execution-timeline__current">
                {{ msg.toolProgressLabel || latestExecutionLabel(msg) }}
              </span>
              <span v-if="msg.executionProgress?.length" class="execution-timeline__count"> {{ msg.executionProgress.length }} 步 </span>
            </summary>
            <ol v-if="msg.executionProgress?.length" class="execution-timeline__list">
              <li v-for="(item, progressIndex) in msg.executionProgress" :key="`${item.at}-${progressIndex}`" :class="`is-${item.status}`">
                <span class="execution-timeline__marker">{{ executionMarker(item.status) }}</span>
                <span>{{ item.label }}</span>
              </li>
            </ol>
          </details>
          <div v-if="msg.role === 'ai' && msg.shipmentDownloadUrl" class="message-shipment-actions">
            <a class="btn btn-primary btn-sm" :href="msg.shipmentDownloadUrl" download @click="$emit('shipment-download-click')">
              {{ $t('chat.downloadShipment') }}
            </a>
          </div>
          <div v-if="showDiagnosticMetadata && msg.role === 'ai' && msg.contextSummary" class="context-summary">
            {{ msg.contextSummary }}
          </div>
          <details v-if="showDiagnosticMetadata && msg.role === 'ai' && msg.thinkingSteps" class="thinking-panel">
            <summary>{{ $t('chat.viewThinkingSteps') }}</summary>
            <pre>{{ msg.thinkingSteps }}</pre>
          </details>
          <div v-if="msg.role === 'ai' && !hasOrchestrationTrace(msg) && msg.todoSteps && msg.todoSteps.length" class="todo-panel">
            <div class="todo-title">{{ $t('chat.executeTodo') }}</div>
            <ul>
              <li v-for="(step, tIdx) in msg.todoSteps" :key="tIdx">{{ step }}</li>
            </ul>
          </div>
          <ChatApprovalInlineCard
            v-if="msg.role === 'ai' && msg.approvalCard && msg.approvalCard.status === 'pending'"
            :card="msg.approvalCard"
            :busy="isLoading || msg.approvalCard.submitting"
            @confirm="$emit('approval-confirm', approvalCardId(msg.approvalCard))"
            @cancel="$emit('approval-cancel', approvalCardId(msg.approvalCard))"
          />
          <div
            v-if="showDiagnosticMetadata && msg.role === 'ai' && (msg.workflowAction || (msg.nodeResults && msg.nodeResults.length))"
            class="trace-panel"
          >
            <div class="trace-title">{{ $t('chat.traceTitle') }}</div>
            <div class="trace-stages">
              <span class="trace-chip">{{ $t('chat.traceThinking') }}</span>
              <span class="trace-chip">{{ $t('chat.tracePlan') }}</span>
              <span class="trace-chip">{{ $t('chat.traceExecute') }}</span>
            </div>
            <div class="trace-action" v-if="msg.workflowAction">
              {{ $t('chat.statusLabel', { status: msg.workflowAction }) }}
            </div>
            <ul v-if="msg.nodeResults && msg.nodeResults.length" class="trace-list">
              <li v-for="(nr, nIdx) in msg.nodeResults" :key="nIdx">
                <span :class="['trace-status', nr.success ? 'ok' : 'fail']">{{ nr.success ? $t('chat.success') : $t('chat.failed') }}</span>
                <span>{{ nr.node_id }} · {{ nr.tool_id }}.{{ nr.action }}</span>
                <span v-if="nr.retries || nr.duration_ms" class="trace-node-meta">
                  <template v-if="nr.retries">重试 {{ nr.retries }} 次</template>
                  <template v-if="nr.retries && nr.duration_ms"> · </template>
                  <template v-if="nr.duration_ms">{{ nr.duration_ms }}ms</template>
                </span>
                <span v-if="nr.error || nr.message" class="trace-node-error">
                  {{ nr.error || nr.message }}
                </span>
                <span v-if="nr.recovery_hint" class="trace-node-hint"> 恢复建议：{{ nr.recovery_hint }} </span>
              </li>
            </ul>
          </div>
          <MessageCollapseLink
            v-if="msg.role === 'ai' && idx < latestAiMessageIndex"
            label="收起详情"
            @collapse="$emit('collapse-message', idx)"
          />
        </template>
        <div :class="msg.role === 'ai' ? 'message-footer' : 'message-footer message-footer--user'">
          <div class="time">{{ msg.time }}</div>
          <span v-if="msg.persistence && (msg.persistence.status === 'saving' || msg.persistence.status === 'failed' || msg.persistence.error || msg.persistence.localSaved === false)" class="message-save-status" role="status">
            {{ saveLabels[msg.persistence.status] }}{{ msg.persistence.localSaved === false ? ' · 本机副本保存失败' : '' }}
            <span v-if="msg.persistence.error" class="message-save-error">{{ msg.persistence.error }}</span>
          </span>
          <button v-if="msg.persistence?.request && ['failed', 'local'].includes(msg.persistence.status)" type="button" class="btn btn-secondary btn-sm" @click="$emit('retry-save', msg.persistence.id)">仅重试保存</button>
          <button v-if="!msg.streamingShell && msg.content" type="button" class="message-copy-btn" :title="copyLabels.get(msg) || '复制正文'" :aria-label="copyLabels.get(msg) || '复制正文'" @click.stop="copyMessage(msg, $event)">
            <i class="fa fa-copy" aria-hidden="true"></i>
          </button>
          <span v-if="copyLabels.get(msg)" class="message-copy-status" role="status">{{ copyLabels.get(msg) }}</span>
          <button
            v-if="msg.role === 'ai' && messageCanSpeak(msg)"
            class="message-tts-btn"
            :class="{ 'is-playing': playingMsgIdx === idx }"
            :title="playingMsgIdx === idx ? $t('chat.stopTts') : $t('chat.speakReply')"
            :aria-label="playingMsgIdx === idx ? $t('chat.stopTts') : $t('chat.speakReply')"
            @click.stop="$emit('toggle-message-tts', idx, msg.content)"
          >
            <i class="fa" :class="playingMsgIdx === idx ? 'fa-stop' : 'fa-volume-up'" aria-hidden="true"></i>
          </button>
        </div>
        <div v-if="msg.role === 'ai' && !msg.streamingShell && isFailedChatReply(msg)" class="proactive-suggestions" data-testid="chat-error-recovery">
          <p>请先检查模型状态。重试会发起新请求，已执行的业务操作不会撤销。</p>
          <details v-if="originalRequest(idx)"><summary>查看本次原始输入</summary><p>{{ originalRequest(idx) }}</p></details>
          <button v-if="originalRequest(idx)" type="button" class="btn btn-secondary btn-sm" :disabled="isLoading" @click="$emit('fill-example', originalRequest(idx))">重试本次请求（填入原文）</button>
        </div>
        <div
          v-else-if="!isMessageCollapsed(msg, idx) && suggestionsFor(msg).length"
          class="proactive-suggestions"
          data-testid="proactive-suggestions"
          :data-reply-id="proactiveReplyMessageId(msg)"
          aria-label="这条回复的下一步建议"
        >
          <div class="proactive-suggestions__chips">
            <button v-for="item in suggestionsFor(msg)" :key="item.id" type="button"
              class="proactive-suggestions__chip" @click="$emit('pick-proactive-suggestion', item)">
              {{ item.text }}
            </button>
          </div>
        </div>
      </div>
      <div v-if="windowEnd === messages.length && isLoading && !isStreamingReply" class="message ai">
        <div class="chat-loading-row">
          <i class="fa fa-spinner fa-spin chat-loading-spinner" aria-hidden="true"></i>
          <span class="status-dot online"></span>
          <span>{{ loadingProgressText }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ChatMessage } from '@/composables/useChatMessages'
import { sanitizeChatBubbleHtml, sanitizeChatBubbleMarkdown, plainTextFromChatHtml } from '@/utils/sanitizeHtml'
import { aiMarkdownSourceFromContent } from '@/utils/chatBubbleDisplay'
import ChatApprovalInlineCard from '@/components/chat/ChatApprovalInlineCard.vue'
import ChatTypingIndicator from '@/components/chat/ChatTypingIndicator.vue'
import AgentRunTrace from '@/components/chat/AgentRunTrace.vue'
import CollapsedMessagePreview from '@/components/chat/CollapsedMessagePreview.vue'
import MessageCollapseLink from '@/components/chat/MessageCollapseLink.vue'
import { buildApprovalCardTrace } from '@/utils/chatOrchestrationTrace'
import { approvalCardId } from '@/utils/chatApprovalCard'
import type { AgentRunTraceData } from '@/utils/agentRunTraceModel'
import { CHAT_HISTORY_WINDOW, useChatHistoryWindow } from '@/composables/useChatHistoryWindow'
import { isFailedChatReply, proactiveReplyMessageId, type ProactiveReplySuggestion } from '@/composables/useProactiveReplySuggestions'

useI18n()

const saveLabels = { local: '本机副本 · 服务端未核实', saving: '正在保存…', saved: '已保存到服务端', failed: '保存未确认' }

const props = defineProps<{
  messages: ChatMessage[]
  emptyIntro?: string
  sessionKey?: string
  proactiveSuggestions?: ReadonlyMap<string, readonly ProactiveReplySuggestion[]>
  isLoading: boolean
  isStreamingReply: boolean
  loadingProgressText: string
  messageHeights: Map<number, number>
  latestAiMessageIndex: number
  playingMsgIdx: number
  isMessageCollapsed: (msg: ChatMessage, idx: number) => boolean
  getCollapsedPreview: (htmlText: string) => string
  canSpeakMessage: (msg: ChatMessage) => boolean
  chatMessagesRef?: Ref<HTMLElement | null>
  /** 默认不向普通用户暴露内部上下文计数；诊断界面可显式开启。 */
  showDiagnosticMetadata?: boolean
}>()

const emit = defineEmits<{
  'expand-message': [idx: number]
  'collapse-message': [idx: number]
  'toggle-message-tts': [idx: number, content: string]
  'shipment-download-click': []
  'approval-confirm': [cardId: string]
  'approval-cancel': [cardId: string]
  'retry-save': [id: string]
  'approve-run': [runId: string]
  'pick-proactive-suggestion': [item: ProactiveReplySuggestion]
  'fill-example': [text: string]
}>()

function originalRequest(index: number): string {
  const reply = props.messages[index]
  const user = props.messages.slice(0, index).reverse().find(message => message.role === 'user'
    && (!reply?.turnId || reply.turnId === message.turnId))
  return user ? plainTextFromChatHtml(user.content) : ''
}

function suggestionsFor(message: ChatMessage): readonly ProactiveReplySuggestion[] {
  if (message.role !== 'ai' || message.streamingShell || isFailedChatReply(message)) return []
  const messageId = proactiveReplyMessageId(message)
  return (props.proactiveSuggestions?.get(messageId) || [])
    .filter(item => item.scopeKey === (props.sessionKey || '') && item.messageId === messageId)
}

/** 运行停在待确认步骤且没有待处理的计划卡片时，保留对话内的「确认执行」入口（#2289）。 */
function waitingRunId(message: ChatMessage): string {
  const trace = message.role === 'ai' ? message.agentRunTrace : undefined
  if (!trace || trace.terminal || trace.status !== 'waiting' || message.approvalCard?.status === 'pending') return ''
  return String(trace.run_id || '')
}

function approveMessage(message: ChatMessage) {
  if (message.approvalCard?.status === 'pending') {
    emit('approval-confirm', approvalCardId(message.approvalCard))
  } else {
    const runId = waitingRunId(message)
    if (runId) emit('approve-run', runId)
  }
}

const messagesHostRef = ref<HTMLElement | null>(null)
const copyLabels = ref(new Map<ChatMessage, string>())
const { start: windowStart, end: windowEnd, visibleMessages, moveWindow, showLatest, onScroll, revealMessage, scrollToLatestIfFollowing } =
  useChatHistoryWindow(() => props.messages, messagesHostRef, () => props.sessionKey)
watch(() => props.proactiveSuggestions?.size, scrollToLatestIfFollowing, { flush: 'post' })
type Presentation = { key: number; content: string; role: ChatMessage['role']; html?: string; preview?: string; canSpeak?: boolean }
let presentations = new WeakMap<ChatMessage, Presentation>()
let nextKey = 0
function presentation(message: ChatMessage): Presentation {
  let entry = presentations.get(message)
  if (!entry || entry.content !== message.content || entry.role !== message.role) {
    entry = { key: entry?.key ?? nextKey++, content: message.content, role: message.role }
    presentations.set(message, entry)
  }
  return entry
}
function messageHtml(message: ChatMessage): string {
  return presentation(message).html ??= message.role === 'ai'
    ? sanitizeChatBubbleMarkdown(aiMarkdownSourceFromContent(message.content)) : sanitizeChatBubbleHtml(message.content)
}
function messagePreview(message: ChatMessage): string {
  return presentation(message).preview ??= props.getCollapsedPreview(message.content)
}
function messageCanSpeak(message: ChatMessage): boolean {
  return presentation(message).canSpeak ??= props.canSpeakMessage(message)
}
watch([() => props.sessionKey, () => props.messages, () => props.getCollapsedPreview, () => props.canSpeakMessage], () => {
  presentations = new WeakMap()
  copyLabels.value.clear()
}, { flush: 'sync' })
watch(visibleMessages, (rows) => {
  const visible = new Set(rows.map(({ msg }) => msg))
  for (const message of copyLabels.value.keys()) if (!visible.has(message)) copyLabels.value.delete(message)
})
function visibleBodyText(root: HTMLElement): string {
  const blocks = new Set(['P', 'DIV', 'LI', 'PRE', 'BLOCKQUOTE', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'TR'])
  let text = ''
  function visit(node: Node) {
    if (node.nodeType === Node.TEXT_NODE) {
      const parent = node.parentElement
      if (parent && getComputedStyle(parent).visibility !== 'hidden' && getComputedStyle(parent).visibility !== 'collapse') text += node.textContent || ''
      return
    }
    if (!(node instanceof HTMLElement)) return
    const style = getComputedStyle(node)
    if (style.display === 'none' || style.contentVisibility === 'hidden' || (style.opacity !== '' && Number(style.opacity) === 0) || node.hidden || node.getAttribute('aria-hidden') === 'true' || node.matches('button, .md-code__head')) return
    if (node.tagName === 'BR') { if (style.visibility !== 'hidden' && style.visibility !== 'collapse') text += '\n'; return }
    node.childNodes.forEach(visit)
    if (blocks.has(node.tagName) && text && !text.endsWith('\n')) text += '\n'
  }
  visit(root)
  return text.replace(/\u00a0/g, ' ').replace(/\n{3,}/g, '\n\n').trim()
}
async function copyMessage(message: ChatMessage, event: MouseEvent) {
  const container = (event.currentTarget as HTMLElement).closest('.message')
  if (!container || message.streamingShell) return
  let body = container.querySelector<HTMLElement>('.message-html, .message-orchestration-intro')
  let temporary: HTMLElement | undefined
  if (!body) {
    // Render the sanitized collapsed body offscreen in its message context.
    temporary = document.createElement('div')
    temporary.className = 'message-html'
    temporary.style.position = 'fixed'
    temporary.style.left = '-10000px'
    if (message.role === 'ai' && shouldCondenseOrchestrationBody(message)) {
      temporary.textContent = '执行计划已整理为任务编排，展开卡片可查看工具、步骤和运行详情。'
    } else {
      const html = messageHtml(message)
      temporary.append(...new DOMParser().parseFromString(html, 'text/html').body.childNodes)
    }
    container.appendChild(temporary)
    body = temporary
  }
  const text = visibleBodyText(body)
  temporary?.remove()
  if (!text) { copyLabels.value.set(message, '没有可复制的正文'); return }
  try {
    if (window.xcagiDesktop?.clipboardWriteText) {
      const result = await window.xcagiDesktop.clipboardWriteText(text)
      if (!result?.ok) throw new Error('clipboard write failed')
    } else {
      await navigator.clipboard.writeText(text)
    }
    copyLabels.value.set(message, '已复制')
  } catch {
    copyLabels.value.set(message, '复制失败，请重试')
  }
}

function latestExecutionLabel(message: ChatMessage): string {
  const list = message.executionProgress || []
  return list[list.length - 1]?.label || '查看执行过程'
}

function executionMarker(status: string): string {
  if (status === 'success') return '✓'
  if (status === 'failed') return '×'
  if (status === 'cancelled') return '■'
  if (status === 'waiting') return 'Ⅱ'
  if (status === 'retrying') return '↻'
  return '●'
}

function shouldCondenseOrchestrationBody(message: ChatMessage): boolean {
  if (!hasOrchestrationTrace(message)) return false
  const body = aiMarkdownSourceFromContent(message.content)
  return /(动态工作流计划|工作编排|工具探测概览|执行编排|节点图|风险判断|需要审批后执行|requires human risk approval)/i.test(body)
}

function approvalTraceFor(message: ChatMessage): AgentRunTraceData | null {
  return buildApprovalCardTrace(message.approvalCard)
}

function hasOrchestrationTrace(message: ChatMessage): boolean {
  return Boolean(message.agentRunTrace || approvalTraceFor(message))
}

function orchestrationTraceFor(message: ChatMessage): AgentRunTraceData {
  return (
    message.agentRunTrace ||
    approvalTraceFor(message) || {
      run_id: 'pending',
      intent: '',
      status: 'running',
      phases: [],
      terminal: false,
    }
  )
}

watch(
  messagesHostRef,
  (el) => {
    const bag = props.chatMessagesRef
    if (!bag) return
    bag.value = el
  },
  { immediate: true },
)
</script>

<style scoped>
.proactive-suggestions {
  padding-top: 8px;
}
.proactive-suggestions__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.proactive-suggestions__chip {
  max-width: 100%;
  text-align: left;
  padding: 6px 10px;
  border-radius: 999px;
  border: 1px solid var(--app-border, #d0d5dd);
  background: var(--app-surface, #fff);
  color: var(--app-text, #1d2939);
  font-size: var(--app-font-size-caption, 12px);
  line-height: 1.35;
  cursor: pointer;
}
.proactive-suggestions__chip:hover,
.proactive-suggestions__chip:focus-visible {
  border-color: var(--xc-color-primary, #0d47a1);
  color: var(--xc-color-primary, #0d47a1);
}
.chat-messages-shell {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.chat-messages {
  flex: 1;
  min-height: 0;
  height: auto;
}

.chat-history-navigation {
  flex: none;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 6px;
  font-size: 12px;
}
.message-save-status { font-size: 12px; }
.message-save-error { display: block; color: var(--app-text-danger, #b42318); }

.run-approve-row {
  margin-top: 6px;
}

.run-approve-btn {
  padding: 2px 10px;
  border: 1px solid #3b82f6;
  border-radius: 4px;
  background: #3b82f6;
  color: #fff;
  font-size: 12px;
  cursor: pointer;
}

.message-shipment-actions {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.message-orchestration-intro {
  margin: 8px 0 2px;
  color: #6b7280;
  font-size: 12px;
  line-height: 1.55;
}

.chat-loading-row {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.chat-loading-spinner {
  color: var(--xc-color-primary, #0d47a1);
  font-size: 14px;
}

.execution-timeline {
  margin-top: 10px;
  border-top: 1px dashed #d1d5db;
  padding-top: 8px;
  font-size: 13px;
  color: #374151;
}

.execution-timeline summary {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  list-style: none;
  user-select: none;
}

.execution-timeline summary::-webkit-details-marker {
  display: none;
}

.execution-timeline__spinner {
  color: var(--xc-color-primary, #0d47a1);
  font-size: 12px;
}

.execution-timeline__current {
  font-weight: 500;
  flex: 1;
  min-width: 0;
}

.execution-timeline__count {
  flex-shrink: 0;
  font-size: 12px;
  color: #6b7280;
  background: #f3f4f6;
  border-radius: 999px;
  padding: 1px 8px;
}

.execution-timeline__list {
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 220px;
  overflow-y: auto;
}

.execution-timeline__list li {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  line-height: 1.5;
}

.execution-timeline__marker {
  flex-shrink: 0;
  width: 16px;
  text-align: center;
  font-weight: 700;
}

.execution-timeline__list li.is-success .execution-timeline__marker {
  color: #16a34a;
}

.execution-timeline__list li.is-failed .execution-timeline__marker {
  color: #dc2626;
}

.execution-timeline__list li.is-cancelled .execution-timeline__marker {
  color: #6b7280;
}

.execution-timeline__list li.is-waiting .execution-timeline__marker {
  color: #d97706;
}

.execution-timeline__list li.is-retrying .execution-timeline__marker {
  color: #d97706;
}

.execution-timeline__list li.is-running .execution-timeline__marker {
  color: var(--xc-color-primary, #0d47a1);
}
</style>
