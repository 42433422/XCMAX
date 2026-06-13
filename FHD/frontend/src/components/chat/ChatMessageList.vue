<template>
  <div class="chat-messages-shell">
    <div class="chat-messages" id="chatMessages" ref="messagesHostRef">
      <div
        v-for="(msg, idx) in messages"
        :key="idx"
        :class="['message', msg.role]"
        :style="{ minHeight: messageHeights.get(idx) ? messageHeights.get(idx) + 'px' : 'auto' }"
      >
        <template v-if="msg.role === 'ai' && isMessageCollapsed(msg, idx)">
          <div class="collapsed-message">
            <div class="collapsed-message-text">{{ getCollapsedPreview(msg.content) }}</div>
            <button class="btn btn-secondary btn-sm" @click="$emit('expand-message', idx)">{{ $t('chat.expand') }}</button>
          </div>
        </template>
        <template v-else>
          <div
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
          <button
            v-if="msg.role === 'ai' && idx < latestAiMessageIndex"
            class="btn btn-secondary btn-sm collapse-toggle"
            @click="$emit('collapse-message', idx)"
          >
            {{ $t('chat.collapse') }}
          </button>
        </template>
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
}>()

defineEmits<{
  'expand-message': [idx: number]
  'collapse-message': [idx: number]
  'toggle-message-tts': [idx: number, content: string]
  'shipment-download-click': []
}>()

const messagesHostRef = ref<HTMLElement | null>(null)

watch(messagesHostRef, (el) => {
  if (props.chatMessagesRef) {
    props.chatMessagesRef.value = el
  }
}, { immediate: true })
</script>

<style scoped>
.collapsed-message {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  border: 1px dashed #d1d5db;
  border-radius: 8px;
  padding: 8px;
  background: #f9fafb;
}

.collapsed-message-text {
  font-size: 13px;
  color: #4b5563;
  line-height: 1.4;
}

.collapse-toggle {
  margin-top: 8px;
}

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
