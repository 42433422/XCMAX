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
          v-if="msg.role === 'ai' && isStreamingShell(msg)"
          :label="msg.toolProgressLabel || '正在生成回复…'"
        />
        <div
          v-else
          class="message-html"
          v-html="
            msg.role === 'ai' ? sanitizeChatBubbleMarkdown(msg.content) : sanitizeChatBubbleHtml(msg.content)
          "
        ></div>
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
        <div v-if="msg.role === 'ai' && msg.contextSummary" class="context-summary">
          {{ msg.contextSummary }}
        </div>
        <details v-if="msg.role === 'ai' && msg.thinkingSteps" class="thinking-panel">
          <summary>{{ $t('chat.viewThinkingSteps') }}</summary>
          <pre>{{ msg.thinkingSteps }}</pre>
        </details>
        <div v-if="msg.role === 'ai' && msg.todoSteps && msg.todoSteps.length" class="todo-panel">
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
        <div v-if="msg.role === 'ai' && (msg.workflowAction || (msg.nodeResults && msg.nodeResults.length))" class="trace-panel">
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
            v-if="msg.role === 'ai' && isFailedMessage(msg) && !isLoading"
            class="message-retry-btn"
            title="重试"
            aria-label="重新生成回复"
            @click.stop="$emit('retry-message')"
          >
            <i class="fa fa-redo" aria-hidden="true"></i>
            重试
          </button>
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
        <div class="chat-loading-row" role="status" aria-live="polite">
          <i class="fa fa-spinner fa-spin chat-loading-spinner" aria-hidden="true"></i>
          <span class="status-dot online"></span>
          <span>{{ loadingProgressText || '正在思考…' }}</span>
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
import ChatApprovalInlineCard from '@/components/chat/ChatApprovalInlineCard.vue'
import ChatTypingIndicator from '@/components/chat/ChatTypingIndicator.vue'

useI18n()

/** 流式占位（首 token 前）：内容为空的 AI 气泡展示「正在生成」动效，而不是空白气泡 */
function isStreamingShell(msg: ChatMessage): boolean {
  if (!msg.streamingShell) return false
  const text = String(msg.content || '')
    .replace(/<br\s*\/?>/gi, '')
    .replace(/<[^>]*>/g, '')
    .replace(/&nbsp;/gi, ' ')
    .trim()
  return text.length === 0
}

/** 失败消息：AI 回复以「处理失败：」开头 → 展示「重试」入口，可自助恢复 */
function isFailedMessage(msg: ChatMessage): boolean {
  if (msg.role !== 'ai') return false
  const text = String(msg.content || '')
    .replace(/<br\s*\/?>/gi, '')
    .replace(/<[^>]*>/g, '')
    .replace(/&nbsp;/gi, ' ')
    .trim()
  return text.startsWith('处理失败：')
}

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
}>()

defineEmits<{
  'expand-message': [idx: number]
  'collapse-message': [idx: number]
  'toggle-message-tts': [idx: number, content: string]
  'shipment-download-click': []
  'approval-confirm': []
  'approval-cancel': []
  'retry-message': []
}>()

const messagesHostRef = ref<HTMLElement | null>(null)

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

.message-retry-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 1px solid var(--xc-color-border, #e2e8f0);
  border-radius: 6px;
  background: #fff;
  color: var(--xc-color-primary, #0d47a1);
  font-size: 12px;
  padding: 2px 8px;
  cursor: pointer;
}

.message-retry-btn:hover {
  background: #f1f5f9;
}
</style>
