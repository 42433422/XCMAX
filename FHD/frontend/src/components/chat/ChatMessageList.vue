<template>
  <div class="chat-messages-shell">
    <div class="chat-messages" id="chatMessages" ref="messagesHostRef">
      <template v-for="(msg, idx) in messages" :key="idx">
        <div
          v-if="shouldRenderChatMessageRow(msg, idx, messages, isStreamingReply)"
          :class="[
            'message',
            msg.role,
            {
              'message--typing': isAiTypingOnly(msg, idx, messages, isStreamingReply),
              'message--streaming': msg.role === 'ai' && isStreamingReply && idx === latestAiMessageIndex,
            },
          ]"
          :style="{ minHeight: messageHeights.get(idx) ? messageHeights.get(idx) + 'px' : 'auto' }"
        >
          <div class="message-bubble">
            <div
              v-if="msg.role === 'ai' && isStreamingReply && idx === latestAiMessageIndex && !isAiTypingOnly(msg, idx, messages, isStreamingReply)"
              class="message-head"
            >
              <span
                class="message-status"
              >
                <span class="message-status-dot" aria-hidden="true"></span>
                正在生成
              </span>
            </div>
            <ChatTypingIndicator
              v-if="isAiTypingOnly(msg, idx, messages, isStreamingReply)"
              label="正在思考"
            />
            <template v-else>
              <div
                class="message-html"
                v-html="
                  msg.role === 'ai'
                    ? sanitizeChatBubbleMarkdown(aiMarkdownSourceFromContent(msg.content))
                    : sanitizeChatBubbleHtml(msg.content)
                "
              ></div>
              <ChatOrchestrationActivity
                v-if="msg.role === 'ai' && msg.orchestrationTrace && msg.orchestrationTrace.length"
                :steps="msg.orchestrationTrace"
              />
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
            </template>
          </div>
        </div>
      </template>
      <div v-if="isLoading && !isStreamingReply" class="message ai message--typing message--loading">
        <div class="message-bubble">
          <ChatTypingIndicator :label="loadingProgressText || '正在处理'" />
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
import { isAiTypingOnly, shouldRenderChatMessageRow } from '@/utils/chatMessageRender'
import ChatApprovalInlineCard from '@/components/chat/ChatApprovalInlineCard.vue'
import ChatOrchestrationActivity from '@/components/chat/ChatOrchestrationActivity.vue'
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
</style>
