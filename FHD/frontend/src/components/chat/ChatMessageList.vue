<template>
  <div class="chat-messages-shell">
    <div class="chat-messages" id="chatMessages" ref="messagesHostRef">
      <div
        v-for="(msg, idx) in messages"
        :key="idx"
        :class="['message', msg.role]"
        :style="{ minHeight: messageHeights.get(idx) ? messageHeights.get(idx) + 'px' : 'auto' }"
      >
        <ChatTypingIndicator
          v-if="msg.role === 'ai' && msg.streamingShell"
          label="正在思考…"
        />
        <div
          v-else
          class="message-html"
          v-html="
            msg.role === 'ai'
              ? sanitizeChatBubbleMarkdown(aiMarkdownSourceFromContent(msg.content))
              : sanitizeChatBubbleHtml(msg.content)
          "
        ></div>
        <details
          v-if="msg.role === 'ai' && (msg.toolProgressLabel || msg.executionProgress?.length)"
          class="execution-timeline"
          :open="!!msg.streamingShell"
        >
          <summary>
            <i
              v-if="msg.streamingShell"
              class="fa fa-spinner fa-spin execution-timeline__spinner"
              aria-hidden="true"
            ></i>
            <span class="execution-timeline__current">
              {{ msg.toolProgressLabel || latestExecutionLabel(msg) }}
            </span>
            <span v-if="msg.executionProgress?.length" class="execution-timeline__count">
              {{ msg.executionProgress.length }} 步
            </span>
          </summary>
          <ol v-if="msg.executionProgress?.length" class="execution-timeline__list">
            <li
              v-for="(item, progressIndex) in msg.executionProgress"
              :key="`${item.at}-${progressIndex}`"
              :class="`is-${item.status}`"
            >
              <span class="execution-timeline__marker">{{ executionMarker(item.status) }}</span>
              <span>{{ item.label }}</span>
            </li>
          </ol>
        </details>
        <div
          v-if="msg.role === 'ai' && msg.shipmentDownloadUrl"
          class="message-shipment-actions"
        >
          <a
            class="btn btn-primary btn-sm"
            :href="msg.shipmentDownloadUrl"
            download
            @click="$emit('shipment-download-click')"
          >
            {{ $t('chat.downloadShipment') }}
          </a>
        </div>
        <div
          v-if="showDiagnosticMetadata && msg.role === 'ai' && msg.contextSummary"
          class="context-summary"
        >
          {{ msg.contextSummary }}
        </div>
        <details
          v-if="showDiagnosticMetadata && msg.role === 'ai' && msg.thinkingSteps"
          class="thinking-panel"
        >
          <summary>{{ $t('chat.viewThinkingSteps') }}</summary>
          <pre>{{ msg.thinkingSteps }}</pre>
        </details>
        <div v-if="msg.role === 'ai' && msg.todoSteps && msg.todoSteps.length" class="todo-panel">
          <div class="todo-title">{{ $t('chat.executeTodo') }}</div>
          <ul>
            <li v-for="(step, tIdx) in msg.todoSteps" :key="tIdx">{{ step }}</li>
          </ul>
        </div>
        <AgentRunTrace
          v-if="msg.role === 'ai' && msg.agentRunTrace && !isTrivialChatTrace(msg.agentRunTrace)"
          :trace="msg.agentRunTrace"
        />
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
          <div class="trace-action" v-if="msg.workflowAction">{{ $t('chat.statusLabel', { status: msg.workflowAction }) }}</div>
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
              <span v-if="nr.recovery_hint" class="trace-node-hint">
                恢复建议：{{ nr.recovery_hint }}
              </span>
            </li>
          </ul>
        </div>
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
            <i
              class="fa"
              :class="playingMsgIdx === idx ? 'fa-stop' : 'fa-volume-up'"
              aria-hidden="true"
            ></i>
          </button>
        </div>
      </div>
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
import { ref, watch, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ChatMessage } from '@/composables/useChatMessages'
import { sanitizeChatBubbleHtml, sanitizeChatBubbleMarkdown } from '@/utils/sanitizeHtml'
import { aiMarkdownSourceFromContent } from '@/utils/chatBubbleDisplay'
import ChatApprovalInlineCard from '@/components/chat/ChatApprovalInlineCard.vue'
import AgentRunTrace from '@/components/chat/AgentRunTrace.vue'
import { isTrivialChatTrace } from '@/utils/agentRunTraceModel'
import ChatTypingIndicator from '@/components/chat/ChatTypingIndicator.vue'

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
}>()

defineEmits<{
  'expand-message': [idx: number]
  'collapse-message': [idx: number]
  'toggle-message-tts': [idx: number, content: string]
  'shipment-download-click': []
  'approval-confirm': []
  'approval-cancel': []
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

watch(messagesHostRef, (el) => {
  const bag = props.chatMessagesRef
  if (!bag) return
  bag.value = el
}, { immediate: true })
</script>

<style scoped>
.message-shipment-actions {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
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
  margin: 8px 0 2px;
  border-left: 2px solid #3b82f6;
  padding-left: 10px;
  color: #475569;
  font-size: 12px;
}

.execution-timeline > summary {
  display: flex;
  align-items: center;
  gap: 7px;
  min-height: 24px;
  cursor: pointer;
  list-style: none;
}

.execution-timeline > summary::-webkit-details-marker { display: none; }

.execution-timeline__spinner { color: #2563eb; }

.execution-timeline__current {
  min-width: 0;
  overflow: hidden;
  color: #334155;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.execution-timeline__count {
  margin-left: auto;
  color: #94a3b8;
  font-size: 10px;
}

.execution-timeline__list {
  display: grid;
  gap: 4px;
  margin: 4px 0 3px;
  padding: 0;
  list-style: none;
}

.execution-timeline__list li {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  color: #64748b;
}

.execution-timeline__marker {
  width: 12px;
  flex: 0 0 12px;
  color: #3b82f6;
  text-align: center;
}

.execution-timeline__list .is-success .execution-timeline__marker { color: #059669; }
.execution-timeline__list .is-failed .execution-timeline__marker { color: #dc2626; }
.execution-timeline__list .is-retrying .execution-timeline__marker,
.execution-timeline__list .is-waiting .execution-timeline__marker { color: #d97706; }
.execution-timeline__list .is-cancelled .execution-timeline__marker { color: #64748b; }
</style>
