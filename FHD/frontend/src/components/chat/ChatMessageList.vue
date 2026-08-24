<template>
  <div class="chat-messages-shell">
    <div class="chat-messages" id="chatMessages" ref="messagesHostRef">
      <div
        v-for="(msg, idx) in messages"
        :key="idx"
        :class="['message', msg.role]"
        :style="{ minHeight: !isMessageCollapsed(msg, idx) && messageHeights.get(idx) ? messageHeights.get(idx) + 'px' : 'auto' }"
      >
        <CollapsedMessagePreview
          v-if="isMessageCollapsed(msg, idx)"
          :preview="getCollapsedPreview(msg.content)"
          expand-label="展开详情"
          @expand="$emit('expand-message', idx)"
        />
        <template v-else>
          <ChatTypingIndicator v-if="msg.role === 'ai' && msg.streamingShell" label="正在思考…" show-elapsed />
          <AgentRunTrace
            v-if="msg.role === 'ai' && hasOrchestrationTrace(msg)"
            :trace="orchestrationTraceFor(msg)"
            @auto-approve-tool="$emit('approval-confirm')"
          />
          <div v-if="msg.role === 'ai' && shouldCondenseOrchestrationBody(msg)" class="message-orchestration-intro">
            执行计划已整理为任务编排，展开卡片可查看工具、步骤和运行详情。
          </div>
          <div
            v-else
            class="message-html"
            v-html="
              msg.role === 'ai' ? sanitizeChatBubbleMarkdown(aiMarkdownSourceFromContent(msg.content)) : sanitizeChatBubbleHtml(msg.content)
            "
          ></div>
          <details
            v-if="msg.role === 'ai' && !hasOrchestrationTrace(msg) && (msg.toolProgressLabel || msg.executionProgress?.length)"
            class="execution-timeline"
            :open="!!msg.streamingShell"
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
          <ChatDecisionOptions
            v-if="msg.role === 'ai' && msg.decisionOptions?.length"
            :options="msg.decisionOptions"
            :disabled="decisionOptionsEnabled === false"
            @select="$emit('decision-option', $event, idx)"
          />
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
            @confirm="$emit('approval-confirm')"
            @cancel="$emit('approval-cancel')"
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
          <button
            v-if="msg.role === 'ai' && canSpeakMessage(msg)"
            class="message-tts-btn"
            :class="{ 'is-playing': playingMsgIdx === idx }"
            :title="playingMsgIdx === idx ? $t('chat.stopTts') : $t('chat.speakReply')"
            :aria-label="playingMsgIdx === idx ? $t('chat.stopTts') : $t('chat.speakReply')"
            @click.stop="$emit('toggle-message-tts', idx, msg.content)"
          >
            <i class="fa" :class="playingMsgIdx === idx ? 'fa-stop' : 'fa-volume-up'" aria-hidden="true"></i>
          </button>
        </div>
      </div>
      <OfficeDockingProgressCard v-if="officeDockingProgress" :progress="officeDockingProgress" @cancel="$emit('office-docking-cancel')" />
      <div v-if="isLoading && !isStreamingReply" class="message ai">
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
import { nextTick, ref, watch, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ChatMessage } from '@/composables/useChatMessages'
import { sanitizeChatBubbleHtml, sanitizeChatBubbleMarkdown } from '@/utils/sanitizeHtml'
import { aiMarkdownSourceFromContent } from '@/utils/chatBubbleDisplay'
import ChatApprovalInlineCard from '@/components/chat/ChatApprovalInlineCard.vue'
import ChatTypingIndicator from '@/components/chat/ChatTypingIndicator.vue'
import AgentRunTrace from '@/components/chat/AgentRunTrace.vue'
import CollapsedMessagePreview from '@/components/chat/CollapsedMessagePreview.vue'
import MessageCollapseLink from '@/components/chat/MessageCollapseLink.vue'
import { buildApprovalCardTrace } from '@/utils/chatOrchestrationTrace'
import type { AgentRunTraceData } from '@/utils/agentRunTraceModel'
import type { ChatDecisionOption } from '@/types/chat-ui'
import ChatDecisionOptions from '@/components/chat/ChatDecisionOptions.vue'
import OfficeDockingProgressCard from '@/components/chat/OfficeDockingProgressCard.vue'
import type { ChatOfficeDockingProgress } from '@/composables/useChatOfficeDocking'

useI18n()

const props = defineProps<{
  messages: ChatMessage[]
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
  decisionOptionsEnabled?: boolean
  officeDockingProgress?: ChatOfficeDockingProgress | null
}>()

defineEmits<{
  'expand-message': [idx: number]
  'collapse-message': [idx: number]
  'toggle-message-tts': [idx: number, content: string]
  'shipment-download-click': []
  'approval-confirm': []
  'approval-cancel': []
  'decision-option': [option: ChatDecisionOption, messageIndex: number]
  'office-docking-cancel': []
}>()

const messagesHostRef = ref<HTMLElement | null>(null)

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

watch(
  () => [props.officeDockingProgress?.phase, props.officeDockingProgress?.completed, props.officeDockingProgress?.currentFile],
  async () => {
    if (!props.officeDockingProgress) return
    await nextTick()
    const el = messagesHostRef.value
    if (el) el.scrollTop = el.scrollHeight
  },
)
</script>

<style scoped>
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
