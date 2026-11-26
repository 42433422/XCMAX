<template>
  <div class="chat-messages-shell">
    <Teleport :to="historyNavTarget || '#chat-history-nav-slot'" :disabled="!historyNavTarget">
      <nav v-if="hasEarlier || messages.length > CHAT_HISTORY_WINDOW" :class="['chat-history-navigation', { 'is-header': historyNavTarget }]" aria-label="聊天历史分页">
        <button type="button" :disabled="loadingEarlier || (windowStart === 0 && !hasEarlier)" @click="showEarlier">{{ loadingEarlier ? '正在加载…' : '更早消息' }}</button>
        <span role="status">第 {{ windowStart + 1 }}–{{ windowEnd }} 条，已载入 {{ messages.length }} 条</span>
        <button type="button" :disabled="windowEnd === messages.length" @click="moveWindow(1)">较新消息</button>
        <button type="button" @click="showLatest">最新消息</button>
      </nav>
    </Teleport>
    <p v-if="earlierError" role="alert">{{ earlierError }}</p>
    <div class="chat-messages" id="chatMessages" ref="messagesHostRef" role="list" aria-label="聊天消息"
      @scroll.passive="onScroll" @xcagi-reveal-chat-message="revealMessage">
      <div
        v-for="{ msg, idx } in visibleMessages"
        :key="presentation(msg).key"
        :data-message-index="idx"
        :data-message-key="presentation(msg).key"
        role="listitem"
        :aria-posinset="idx + 1"
        :aria-setsize="messages.length"
        :class="['message', msg.role]"
        :style="{ minHeight: !isMessageCollapsed(msg, idx) && messageHeights.get(idx) ? messageHeights.get(idx) + 'px' : 'auto' }"
      >
        <MessageFold
          v-if="isMessageCollapsed(msg, idx)"
          @expand="$emit('expand-message', idx)"
        >
          <div
            v-if="msg.role === 'ai' && shouldCondenseOrchestrationBody(msg)"
            class="message-html"
          >{{ receiptSummary(msg) }}</div>
          <div
            v-else-if="shouldDeferMarkdownWhileStreaming(msg.content, isMessageStreaming(msg))"
            class="message-html message-html--streaming-long"
          >{{ streamingPreviewText(msg.content) }}</div>
          <div v-else class="message-html" v-html="messageHtml(msg)"></div>
        </MessageFold>
        <template v-else>
          <Trace v-if="msg.role === 'ai' && hasTaskTrace(msg)" class="message-task-trace" data-testid="chat-task-trace">
            <TraceLine class="message-task-trace__heading">
              <TraceIcon><i class="fa fa-sitemap"></i></TraceIcon>
              <TraceTitle>执行链</TraceTitle>
            </TraceLine>
            <ChatTypingIndicator v-if="isMessageStreaming(msg)" :label="activeStageLabel(msg)" :started-at="msg.streamStartedAt" />
            <ChatTurnTrace v-if="msg.trace?.length" :items="msg.trace" />
            <TraceCollapsible
              v-if="msg.thinkingSteps && !stepChainFor(msg).length && !(hasOrchestrationTrace(msg) && orchestrationTraceFor(msg).phases.length)"
              class="message-task-trace__activity"
              :default-open="isMessageStreaming(msg)"
            >
              <TraceCollapsibleTrigger class="message-task-trace__trigger">
                <TraceLine>
                  <TraceIcon><i class="fa fa-list-ul"></i></TraceIcon>
                  <TraceTitle>过程记录</TraceTitle>
                </TraceLine>
              </TraceCollapsibleTrigger>
              <TraceCollapsibleContent><pre>{{ msg.thinkingSteps }}</pre></TraceCollapsibleContent>
            </TraceCollapsible>
            <AgentRunTrace
              v-if="hasOrchestrationTrace(msg) && !prefersToolSteps(msg)"
              :trace="orchestrationTraceFor(msg)"
              @auto-approve-tool="approveMessage(msg)"
            />
            <AgentStepChain
              v-else-if="stepChainFor(msg).length"
              :steps="stepChainFor(msg)"
            />
            <div v-if="waitingRunId(msg)" class="run-approve-row">
              <button type="button" class="run-approve-btn" data-testid="chat-run-approve" @click="$emit('approve-run', waitingRunId(msg))">
                确认执行
              </button>
            </div>
            <TraceCollapsible v-if="hasReceiptDetails(msg)" class="message-receipt">
              <TraceCollapsibleTrigger class="message-receipt__summary">
                <TraceLine class="message-receipt__line">
                  <TraceIcon><i class="fa fa-bolt"></i></TraceIcon>
                  <span class="message-receipt__status" :class="`is-${receiptStatus(msg)}`">{{ receiptStatusLabel(msg) }}</span>
                  <TraceTitle class="execution-timeline__current" data-testid="chat-business-result">{{ receiptSummary(msg) }}</TraceTitle>
                </TraceLine>
              </TraceCollapsibleTrigger>
              <TraceCollapsibleContent class="message-receipt__body">
                <ol v-if="receiptProgress(msg).length" class="execution-timeline__list">
                  <li v-for="(item, progressIndex) in receiptProgress(msg)" :key="`${item.at}-${progressIndex}`" :class="`is-${item.status}`">
                    <span class="execution-timeline__marker">{{ executionMarker(item.status) }}</span>
                    <span>{{ item.label }}</span>
                  </li>
                </ol>
                <div v-if="!hasOrchestrationTrace(msg) && msg.todoSteps && msg.todoSteps.length" class="todo-panel">
                  <ul>
                    <li v-for="(step, tIdx) in msg.todoSteps" :key="tIdx">{{ step }}</li>
                  </ul>
                </div>
                <div
                  v-if="showDiagnosticMetadata && (msg.workflowAction || (msg.nodeResults && msg.nodeResults.length))"
                  class="trace-panel"
                >
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
                      <span v-if="nr.recovery_hint" class="trace-node-hint"> {{ nr.recovery_hint }} </span>
                    </li>
                  </ul>
                </div>
                <div v-if="showDiagnosticMetadata && msg.contextSummary" class="context-summary">
                  {{ msg.contextSummary }}
                </div>
              </TraceCollapsibleContent>
            </TraceCollapsible>
            <TraceLine v-else-if="receiptSummary(msg)" class="message-receipt message-receipt--plain">
              <TraceIcon><i class="fa fa-bolt"></i></TraceIcon>
              <span class="message-receipt__status" :class="`is-${receiptStatus(msg)}`">{{ receiptStatusLabel(msg) }}</span>
              <TraceTitle class="execution-timeline__current" data-testid="chat-business-result">{{ receiptSummary(msg) }}</TraceTitle>
            </TraceLine>
          </Trace>
          <div
            v-if="(msg.role !== 'ai' || !shouldCondenseOrchestrationBody(msg)) && shouldDeferMarkdownWhileStreaming(msg.content, isMessageStreaming(msg))"
            class="message-html message-html--streaming-long"
          >{{ streamingPreviewText(msg.content) }}</div>
          <div
            v-else-if="msg.role !== 'ai' || !shouldCondenseOrchestrationBody(msg)"
            class="message-html"
            v-html="messageHtml(msg)"
          ></div>
          <div v-if="msg.role === 'ai' && msg.shipmentDownloadUrl" class="message-shipment-actions">
            <a class="btn btn-primary btn-sm" :href="msg.shipmentDownloadUrl" download @click="$emit('shipment-download-click')">
              {{ $t('chat.downloadShipment') }}
            </a>
          </div>
          <ChatApprovalInlineCard
            v-if="msg.role === 'ai' && msg.approvalCard && msg.approvalCard.status === 'pending'"
            :card="msg.approvalCard"
            :busy="isLoading || msg.approvalCard.submitting"
            @confirm="$emit('approval-confirm', approvalCardId(msg.approvalCard))"
            @cancel="$emit('approval-cancel', approvalCardId(msg.approvalCard))"
          />
          <MessageCollapseLink
            v-if="msg.role === 'ai' && idx < latestAiMessageIndex && canCollapseMessageOf(msg)"
            label=""
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
          <button
            v-if="msg.role === 'user' && !msg.streamingShell"
            type="button"
            class="message-recall-btn"
            data-testid="chat-recall-edit"
            title="撤回编辑"
            aria-label="撤回编辑"
            @click.stop="$emit('recall-edit', idx)"
          >
            <i class="fa fa-undo" aria-hidden="true"></i>
          </button>
          <button
            v-if="msg.role === 'ai' && !msg.streamingShell && receiptStatus(msg) === 'failed' && isFailedChatReply(msg) && originalRequest(idx)"
            type="button"
            class="message-recovery-btn"
            data-testid="chat-retry-model"
            title="重试本轮（不重复写入）"
            aria-label="重试本轮（不重复写入）"
            :disabled="isLoading"
            @click.stop="retryModel(idx)"
          >
            <i class="fa fa-refresh" aria-hidden="true"></i>
          </button>
          <button
            v-if="msg.recoveryTaskId"
            type="button"
            class="message-recovery-btn"
            data-testid="chat-open-original-task"
            title="查看原任务"
            aria-label="查看原任务"
            @click.stop="$emit('open-original-task', msg.recoveryTaskId)"
          >
            <i class="fa fa-sitemap" aria-hidden="true"></i>
          </button>
          <button
            v-if="msg.role === 'ai' && !msg.streamingShell && msg.turnId && (isFailedChatReply(msg) || receiptStatus(msg) === 'unknown')"
            type="button"
            class="message-recovery-btn"
            data-testid="chat-reconcile-turn"
            title="核对状态"
            aria-label="核对状态"
            :disabled="isLoading"
            @click.stop="$emit('reconcile-turn', idx)"
          >
            <i class="fa fa-check-circle-o" aria-hidden="true"></i>
          </button>
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
        <div v-if="msg.role === 'ai' && !msg.streamingShell && ['unknown', 'blocked'].includes(msg.workflowAction || '')" class="message-recovery" data-testid="chat-unknown-recovery">
          <p class="message-recovery__text">本轮结果未知，请先核对。</p>
        </div>
        <div v-else-if="msg.role === 'ai' && !isMessageStreaming(msg) && !msg.streamingShell && isFailedChatReply(msg) && !hasIncompleteToolReceipt(msg)" class="message-recovery" data-testid="chat-error-recovery">
          <p class="message-recovery__text">{{ recoveryText(msg) }}</p>
        </div>
        <div v-else-if="msg.role === 'ai' && !msg.streamingShell && canConfirmPreview(msg)" class="message-recovery" data-testid="chat-destructive-preview">
          <p class="message-recovery__text">尚未写入，确认后生效。</p>
          <button type="button" class="message-recovery__action is-primary" :disabled="isLoading" @click="confirmPreview(idx)">
            <i class="fa fa-trash-o" aria-hidden="true"></i>确认删除该范围
          </button>
        </div>
        <div
          v-else-if="!isMessageCollapsed(msg, idx) && suggestionsFor(msg).length"
          class="proactive-suggestions"
          data-testid="proactive-suggestions"
          :data-reply-id="proactiveReplyMessageId(msg)"
          aria-label="这条回复的下一步建议"
        >
          <button v-for="item in suggestionsFor(msg)" :key="item.id" type="button"
            class="proactive-suggestions__chip" @click="$emit('pick-proactive-suggestion', item)">
            {{ item.text }}
          </button>
        </div>
        <ChatTypingIndicator v-if="msg === pendingUserMessage" label="正在生成回复…" data-testid="chat-turn-pending" />
        <div v-if="msg === stoppedTurnMessage" class="message-recovery" role="status" data-testid="chat-turn-stopped">
          <p class="message-recovery__text">已停止接收本轮回复。已执行的工具不会撤销；后台任务请到任务工作区核对，勿重复提交。</p>
        </div>
      </div>
      <div v-if="windowEnd === messages.length && isLoading && !isStreamingReply && !pendingUserMessage" class="message ai">
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
import { computed, onMounted, ref, watch, type ComputedRef, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ChatMessage } from '@/composables/useChatMessages'
import { sanitizeChatBubbleHtml, sanitizeChatBubbleMarkdown, plainTextFromChatHtml } from '@/utils/sanitizeHtml'
import { aiMarkdownSourceFromContent, stripPlannerDisplayMarkers, stripToolInvocationLeaks } from '@/utils/chatBubbleDisplay'
import ChatApprovalInlineCard from '@/components/chat/ChatApprovalInlineCard.vue'
import ChatTypingIndicator from '@/components/chat/ChatTypingIndicator.vue'
import ChatTurnTrace from '@/components/chat/ChatTurnTrace.vue'
import AgentRunTrace from '@/components/chat/AgentRunTrace.vue'
import AgentStepChain from '@/components/chat/AgentStepChain.vue'
import { chainState, stepsFromNodeResults, type AgentStepView } from '@/utils/agentStepChain'
import { Trace, TraceCollapsible, TraceCollapsibleContent, TraceCollapsibleTrigger, TraceIcon, TraceLine, TraceTitle } from '@/components/ui/trace'
import MessageFold from '@/components/chat/MessageFold.vue'
import MessageCollapseLink from '@/components/chat/MessageCollapseLink.vue'
import { buildApprovalCardTrace } from '@/utils/chatOrchestrationTrace'
import { approvalCardId } from '@/utils/chatApprovalCard'
import { formatBusinessResultSummary } from '@/utils/businessResultSummary'
import type { AgentRunTraceData } from '@/utils/agentRunTraceModel'
import { chatMessageKey } from '@/utils/chatMessageIdentity'
import { shouldDeferMarkdownWhileStreaming } from '@/utils/chatMarkdownStreaming'
import { CHAT_HISTORY_WINDOW, useChatHistoryWindow } from '@/composables/useChatHistoryWindow'
import { isFailedChatReply, proactiveReplyMessageId, type ProactiveReplySuggestion } from '@/composables/useProactiveReplySuggestions'
import { chatFailureRecoveryText } from '@/components/chat/chatFailureRecovery'

useI18n()

const saveLabels = { local: '本机副本 · 服务端未核实', saving: '正在保存…', saved: '已保存到服务端', failed: '保存未确认' }

const props = defineProps<{
  messages: ChatMessage[]
  sessionKey?: string
  hasEarlier?: boolean
  loadingEarlier?: boolean
  earlierError?: string
  loadEarlier?: () => Promise<void>
  proactiveSuggestions?: ReadonlyMap<string, readonly ProactiveReplySuggestion[]>
  isLoading: boolean
  isStreamingReply: boolean
  pendingTurnId?: string
  stoppedTurnId?: string
  loadingProgressText: string
  messageHeights: Map<number, number>
  latestAiMessageIndex: number
  playingMsgIdx: number
  isMessageCollapsed: (msg: ChatMessage, idx: number) => boolean
  /** 该消息是否允许折叠（超长正文才允许）；缺省视为不可折叠。 */
  canCollapseMessage?: (msg: ChatMessage) => boolean
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
  'recall-edit': [idx: number]
  'reconcile-turn': [idx: number]
  'open-original-task': [taskId: string]
  'pick-proactive-suggestion': [item: ProactiveReplySuggestion]
  'retry-model': [payload: { text: string; turnId: string }]
  'confirm-destructive': [payload: { text: string; idempotencyKey: string }]
}>()

const pendingUserMessage = computed(() => {
  const turnId = props.pendingTurnId
  if (!props.isLoading || !turnId || props.messages.some(msg => msg.role === 'ai' && msg.turnId === turnId)) return undefined
  return props.messages.find(msg => msg.role === 'user' && msg.turnId === turnId)
})

const stoppedTurnMessage = computed(() => {
  const latest = props.messages.at(-1)
  return !props.isLoading && props.stoppedTurnId && latest?.turnId === props.stoppedTurnId ? latest : undefined
})

function businessResultText(message: ChatMessage): string {
  return formatBusinessResultSummary(message.businessResult)
}

function hasTaskTrace(message: ChatMessage): boolean {
  return Boolean(isMessageStreaming(message) || message.trace?.length || message.thinkingSteps
    || hasOrchestrationTrace(message) || stepChainFor(message).length
    || hasReceiptDetails(message) || receiptSummary(message))
}

function activeStageLabel(message: ChatMessage): string {
  const planning = message.agentRunTrace?.phases.find(phase => phase.kind === 'planner' && phase.status === 'running')
  if (planning && !message.liveSteps?.length) return planning.title || '正在生成执行计划'
  return message.toolProgressLabel || message.waitingHint
    || (message.executionProgress?.length ? latestExecutionLabel(message) : '正在处理请求…')
}

function hasReceiptDetails(message: ChatMessage): boolean {
  if (message.role !== 'ai' || isBulkScopeReply(message)) return false
  if (receiptProgress(message).length) return true
  if (!hasOrchestrationTrace(message) && message.todoSteps?.length) return true
  if (!props.showDiagnosticMetadata) return false
  return Boolean(
    message.workflowAction
    || message.nodeResults?.length
    || message.contextSummary
    || message.thinkingSteps,
  )
}

function isMessageStreaming(message: ChatMessage): boolean {
  if (message.workflowAction === 'running' || message.workflowAction === 'queued') return true
  return message.streamStatus ? message.streamStatus === 'submitted' || message.streamStatus === 'streaming' : Boolean(message.streamingShell)
}

function hasUnreceiptedTools(message: ChatMessage): boolean {
  if (!message.streamStatus || isMessageStreaming(message)
    || message.workflowAction === 'waiting_auth'
    || message.approvalCard?.status === 'pending' || message.agentRunTrace?.status === 'waiting') return false
  const receipts = new Set(message.nodeResults?.map(row => row.node_id))
  return Boolean(message.liveSteps?.some(step => step.state === 'running' && !receipts.has(step.id)))
}

type ReceiptStatus = 'running' | 'waiting' | 'authorization' | 'paused' | 'done' | 'deferred' | 'partial' | 'unknown' | 'failed' | 'cancelled' | 'interrupted' | 'rejected' | 'not_started'

const RECEIPT_STATUS_LABEL: Record<ReceiptStatus, string> = {
  running: '进行中',
  waiting: '待确认',
  authorization: '等待授权',
  paused: '已暂停',
  done: '已完成',
  deferred: '待处理',
  partial: '部分完成',
  unknown: '待核对',
  failed: '失败',
  cancelled: '已取消',
  interrupted: '已中断',
  rejected: '未批准',
  not_started: '未开始',
}

function receiptStatus(message: ChatMessage): ReceiptStatus {
  const state = String(message.workflowAction || '')
  const outcome = String(message.execution?.outcome || '')
  const businessState = String(message.businessResult?.status || '')
  if (outcome === 'unknown' || message.execution?.effect === 'unknown'
    || ['unknown', 'blocked'].includes(state) || businessState === 'unknown') return 'unknown'
  if (isMessageStreaming(message)) return 'running'
  if (state === 'paused') return 'paused'
  if (state === 'cancelled' || state === 'interrupted' || state === 'rejected' || state === 'not_started') return state
  if (state === 'waiting_auth') return 'authorization'
  if (message.workflowAction === 'waiting_approval' || message.approvalCard?.status === 'pending' || message.agentRunTrace?.status === 'waiting') return 'waiting'
  if (hasUnreceiptedTools(message)) return 'unknown'
  if (outcome === 'partial' || message.execution?.effect === 'partial') return 'partial'
  const toolState = chainState(stepChainFor(message))
  if (toolState === 'unknown' || toolState === 'partial' || toolState === 'deferred') return toolState
  if (toolState === 'failed' || isFailedChatReply(message)) return 'failed'
  if ((message.executionProgress || []).some(item => item.status === 'failed')) return 'partial'
  if (state && !['completed', 'succeeded', 'success'].includes(state)) return 'unknown'
  if (['completed', 'succeeded', 'success'].includes(state) || outcome === 'succeeded'
    || businessState === 'completed' || message.agentRunTrace?.terminal && message.agentRunTrace.status === 'success') return 'done'
  return 'unknown'
}

function receiptStatusLabel(message: ChatMessage): string {
  return RECEIPT_STATUS_LABEL[receiptStatus(message)]
}

/** 回执摘要只留一句：业务结果优先，其次当前执行步骤；都没有就不占用标题行。 */
function receiptSummary(message: ChatMessage): string {
  if (isBulkScopeReply(message)) return ''
  if (businessResultText(message)) return businessResultText(message)
  if (message.toolProgressLabel && !message.liveSteps?.length
    && (isMessageStreaming(message) || !isGenericStartLabel(message.toolProgressLabel))) return message.toolProgressLabel
  return receiptProgress(message).at(-1)?.label || ''
}

function receiptProgress(message: ChatMessage) {
  const progress = message.executionProgress || []
  return isMessageStreaming(message)
    ? progress
    : progress.filter(item => !isGenericStartLabel(item.label))
}

function isGenericStartLabel(label: string): boolean {
  return /^正在处理任务[.…]*$/.test(label.trim())
}

function originalRequest(index: number): string {
  const reply = props.messages[index]
  const user = props.messages.slice(0, index).reverse().find(message => message.role === 'user'
    && (!reply?.turnId || reply.turnId === message.turnId))
  return user ? plainTextFromChatHtml(user.content) : ''
}

function recoveryText(message: ChatMessage): string {
  return chatFailureRecoveryText(receiptStatus(message) === 'unknown' ? undefined : message.execution)
}

function retryModel(index: number) {
  const text = originalRequest(index)
  const turnId = String(props.messages[index]?.turnId || '').trim()
  if (text && turnId) emit('retry-model', { text, turnId })
}

function confirmPreview(index: number) {
  if (!canConfirmPreview(props.messages[index])) return
  const text = originalRequest(index)
  const idempotencyKey = String(props.messages[index]?.execution?.idempotencyKey || props.messages[index]?.turnId || '').trim()
  if (text && idempotencyKey) emit('confirm-destructive', { text, idempotencyKey })
}

function canConfirmPreview(message?: ChatMessage): boolean {
  const execution = message?.execution
  return execution?.effect === 'preview' && execution.confirmable === true && !execution.committed
}

function isBulkScopeReply(message: ChatMessage): boolean {
  const execution = message.execution
  return execution?.intent === 'bulk_destructive' && ['none', 'preview'].includes(execution.effect)
}

function suggestionsFor(message: ChatMessage): readonly ProactiveReplySuggestion[] {
  if (message.role !== 'ai' || isMessageStreaming(message) || isFailedChatReply(message) || message.workflowAction === 'blocked') return []
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
/** 顶部快捷按钮行里的分页挂载点；独立挂载（如测试）时回退到消息区顶部。 */
// The sibling header is not in document during the initial parent render.
// Change `to` to its mounted element as well as enabling Teleport: toggling
// disabled alone would reuse the initial null target and interrupt rendering.
const historyNavTarget = ref<HTMLElement | null>(null)
onMounted(() => {
  historyNavTarget.value = document.getElementById('chat-history-nav-slot')
})
const copyLabels = ref(new Map<ChatMessage, string>())
const { start: windowStart, end: windowEnd, visibleMessages, moveWindow, showLatest, onScroll, revealMessage, scrollToLatestIfFollowing } =
  useChatHistoryWindow(() => props.messages, messagesHostRef, () => props.sessionKey)
async function showEarlier() {
  if (windowStart.value > 0 || !props.loadEarlier) { await moveWindow(-1); return }
  const count = props.messages.length
  await props.loadEarlier()
  await moveWindow(-1, Math.max(0, props.messages.length - count - 60))
}

watch([() => props.proactiveSuggestions?.size, stoppedTurnMessage], scrollToLatestIfFollowing, { flush: 'post' })
type Presentation = { key: string; content: string; role: ChatMessage['role']; html?: string; canSpeak?: boolean; foldable?: boolean }
let presentations = new WeakMap<ChatMessage, Presentation>()
function presentation(message: ChatMessage): Presentation {
  const key = chatMessageKey(message)
  let entry = presentations.get(message)
  if (!entry || entry.key !== key || entry.content !== message.content || entry.role !== message.role) {
    entry = { key, content: message.content, role: message.role }
    presentations.set(message, entry)
  }
  return entry
}
function messageHtml(message: ChatMessage): string {
  return presentation(message).html ??= message.role === 'ai'
    ? sanitizeChatBubbleMarkdown(aiMarkdownSourceFromContent(message.content)) : sanitizeChatBubbleHtml(message.content)
}
function messageCanSpeak(message: ChatMessage): boolean {
  // Speech preparation parses the full Markdown document. Do it after the
  // terminal receipt, not once per streamed token/frame.
  if (isMessageStreaming(message)) return false
  return presentation(message).canSpeak ??= props.canSpeakMessage(message)
}
function canCollapseMessageOf(message: ChatMessage): boolean {
  // 逐条缓存：是否折叠要看正文长度，不能每帧重算整段纯文本。
  const entry = presentation(message)
  if (entry.foldable === undefined) {
    entry.foldable = props.canCollapseMessage ? props.canCollapseMessage(message) : false
  }
  return entry.foldable
}
watch(
  [() => props.sessionKey, () => props.canSpeakMessage, () => props.canCollapseMessage],
  () => {
    presentations = new WeakMap()
    copyLabels.value.clear()
  },
  { flush: 'sync' },
)
watch(visibleMessages, (rows, previousRows) => {
  const visible = new Set(rows.map(({ msg }) => msg))
  for (const message of copyLabels.value.keys()) if (!visible.has(message)) copyLabels.value.delete(message)
  // Message objects are retained by history even when offscreen. WeakMap alone
  // therefore does not bound the derived HTML or computed trace cache.
  for (const { msg } of previousRows || []) {
    if (visible.has(msg)) continue
    presentations.delete(msg)
    stepChainCache.delete(msg)
  }
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
  let body = container.querySelector<HTMLElement>('.message-html')
  if (!body) body = container.querySelector<HTMLElement>('.message-receipt')
  let temporary: HTMLElement | undefined
  if (!body) {
    // Render the sanitized collapsed body offscreen in its message context.
    temporary = document.createElement('div')
    temporary.className = 'message-html'
    temporary.style.position = 'fixed'
    temporary.style.left = '-10000px'
    if (message.role === 'ai' && shouldCondenseOrchestrationBody(message)) {
      temporary.textContent = receiptSummary(message)
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
  const body = isMessageStreaming(message)
    ? streamingPreviewText(message.content)
    : aiMarkdownSourceFromContent(message.content)
  return /(动态工作流计划|工作编排|工具探测概览|执行编排|节点图|风险判断|需要审批后执行|requires human risk approval)/i.test(body)
}

function streamingPreviewText(content: string): string {
  return stripPlannerDisplayMarkers(stripToolInvocationLeaks(content))
}

function approvalTraceFor(message: ChatMessage): AgentRunTraceData | null {
  return buildApprovalCardTrace(message.approvalCard)
}

function hasOrchestrationTrace(message: ChatMessage): boolean {
  if (hasUnreceiptedTools(message)) return false
  return Boolean(message.agentRunTrace || approvalTraceFor(message))
}

function isExplicitIncompleteStep(step: AgentStepView): boolean {
  return step.state === 'deferred' || step.state === 'partial' || step.state === 'unknown'
}

function prefersToolSteps(message: ChatMessage): boolean {
  if (!message.liveSteps?.length) return false
  if (isMessageStreaming(message)) return true
  return receiptStatus(message) !== 'waiting' && message.liveSteps.some(isExplicitIncompleteStep)
}

function hasIncompleteToolReceipt(message: ChatMessage): boolean {
  if (!message.liveSteps?.some(isExplicitIncompleteStep)) return false
  const status = receiptStatus(message)
  return status === 'deferred' || status === 'partial' || status === 'unknown'
}

const EMPTY_STEPS: AgentStepView[] = []
const stepChainCache = new WeakMap<ChatMessage, ComputedRef<AgentStepView[]>>()

/** Vue tracks every field read; progress on an earlier parallel node cannot stale the view. */
function stepChainFor(message: ChatMessage): AgentStepView[] {
  if (message.role !== 'ai') return EMPTY_STEPS
  let entry = stepChainCache.get(message)
  if (!entry) {
    entry = computed(() => {
      const active = isMessageStreaming(message)
      const finalSteps = stepsFromNodeResults(message.nodeResults)
      const receipts = new Map(finalSteps.map(step => [step.id, step]))
      const live = message.liveSteps || EMPTY_STEPS
      const base = active && message.liveSteps?.length ? message.liveSteps
        : [...live.map(step => isExplicitIncompleteStep(step) ? step : receipts.get(step.id) || step),
          ...finalSteps.filter(step => !live.some(item => item.id === step.id))]
      if (!active) return base.map(step => step.state === 'running'
        ? { ...step, state: 'unknown' as const, hint: '执行结果待核对' } : step)
      return base
    })
    stepChainCache.set(message, entry)
  }
  return entry.value
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
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 160px), 1fr));
  gap: 8px;
  padding-top: 8px;
}
.proactive-suggestions__chip {
  min-width: 0;
  min-height: 44px;
  text-align: left;
  overflow-wrap: anywhere;
  padding: 8px 10px;
  border: 1px solid var(--app-border-default, #cbd5e1);
  border-radius: 8px;
  background: var(--app-surface, #fff);
  color: var(--xc-color-primary, #0d47a1);
  font-size: var(--app-font-size-caption, 12px);
  line-height: 1.5;
  cursor: pointer;
}
.proactive-suggestions__chip:hover {
  background: var(--xc-color-primary-surface, #eff6ff);
  border-color: currentColor;
}
.proactive-suggestions__chip:focus-visible {
  outline: 2px solid currentColor;
  outline-offset: 2px;
}
.message-recovery {
  padding-top: 8px;
}
.message-recovery__text {
  margin: 0 0 6px;
  color: #4b5563;
  font-size: 12px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.message-recovery-btn {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #6b7280;
  font-size: 12px;
  line-height: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  opacity: 0.72;
  transition: opacity 0.15s ease, background 0.15s ease, color 0.15s ease;
}
.message:hover .message-recovery-btn {
  opacity: 0.9;
}
.message-recovery-btn:hover {
  background: #eef2f7;
  color: #2d7bd6;
}
.message-recovery-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.message-recovery__action {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--xc-color-primary, #0d47a1);
  font-size: 12px;
  line-height: 1.5;
  cursor: pointer;
}
.message-recovery__action i {
  font-size: 11px;
}
.message-recovery__action:hover {
  text-decoration: underline;
}
.message-recovery__action:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.message-recovery__action.is-primary {
  color: #b42318;
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
  gap: 2px;
  width: fit-content;
  max-width: calc(100% - 16px);
  margin: 6px auto;
  padding: 3px 6px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--app-text-muted, #64748b);
  background: var(--app-surface-muted, rgba(248, 250, 252, 0.96));
  border: 1px solid var(--app-border-subtle, rgba(226, 232, 240, 0.82));
  border-radius: 999px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.chat-history-navigation.is-header {
  /* 顶置到快捷按钮行时不再需要自身外边距 */
  margin: 0;
  max-width: none;
}

.chat-history-navigation span[role='status'] {
  padding: 0 6px;
  color: var(--app-text-muted, #64748b);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.chat-history-navigation button {
  appearance: none;
  border: 1px solid transparent;
  background: transparent;
  color: var(--xc-color-primary, #0d47a1);
  font-size: 12px;
  line-height: 1.6;
  padding: 1px 8px;
  border-radius: 999px;
  cursor: pointer;
  white-space: nowrap;
  transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}

.chat-history-navigation button:hover:not(:disabled) {
  background: var(--xc-color-primary-soft, #e3eaf8);
  border-color: var(--app-border-default, rgba(203, 213, 225, 0.8));
}

.chat-history-navigation button:disabled {
  color: var(--app-text-muted, #64748b);
  opacity: 0.45;
  cursor: not-allowed;
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

.message-task-trace {
  gap: 6px;
  margin: 4px 0 10px;
}

.message-task-trace__heading {
  color: var(--trace-foreground);
  font-weight: 500;
}

.message-task-trace :deep(.chat-turn-trace),
.message-task-trace :deep(.asc-chain),
.message-task-trace :deep(.art-trace) {
  margin: 0;
}

.message-task-trace__trigger,
.message-receipt__summary,
.message-receipt__line {
  width: 100%;
}

.message-task-trace__trigger :deep(.xc-trace-chevron) {
  margin-left: auto;
}

.message-task-trace__activity pre {
  margin: 4px 0 0;
  padding-left: 20px;
  font: inherit;
  white-space: pre-wrap;
}

.message-receipt__status {
  flex-shrink: 0;
  color: #4b5563;
  font-size: 12px;
}

.message-receipt__status.is-done {
  color: #6b7280;
}

.message-receipt__status.is-partial,
.message-receipt__status.is-deferred,
.message-receipt__status.is-unknown {
  color: #b45309;
}

.message-receipt__status.is-failed {
  color: #dc2626;
}

.message-receipt__status.is-running {
  color: var(--xc-color-primary, #0d47a1);
}

.message-receipt__body {
  margin: 4px 0 6px 20px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11.5px;
  color: #4b5563;
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

.execution-timeline__current {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #6b7280;
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
