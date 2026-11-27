<template>
  <div v-if="show" class="modal active">
    <div class="modal-content history-modal-content">
      <div class="modal-header history-modal-header">
        <span>{{ $t('chat.historyTitle') }}</span>
        <div class="history-modal-actions">
          <button type="button" class="btn btn-secondary btn-sm history-modal-btn" :disabled="historyLoading" @click="$emit('refresh')">
            {{ $t('chat.refresh') }}
          </button>
          <button
            type="button"
            class="btn btn-secondary btn-sm history-modal-btn history-modal-btn-danger"
            :disabled="historyLoading || historySessions.length === 0 || historySessions.some(session => isChatConversationBusy(session.activity))"
            @click="$emit('clear')"
          >
            {{ $t('chat.clear') }}
          </button>
          <button
            type="button"
            class="close history-modal-close"
            :aria-label="$t('chat.closeHistory')"
            :title="$t('chat.closeHistory')"
            @click="$emit('close')"
          >
            ×
          </button>
        </div>
      </div>
      <div class="modal-body history-modal-body">
        <div v-if="historyLoading && !historySessions.length" class="empty-state">{{ $t('chat.historyLoading') }}</div>
        <div v-if="historyError" class="history-error-wrap">
          <div class="history-error-text">{{ historyError }}</div>
          <button type="button" class="btn btn-secondary btn-sm" @click="$emit('refresh')">
            {{ $t('chat.retry') }}
          </button>
        </div>
        <div v-if="!historyLoading && !historyError && historySessions.length === 0" class="empty-state">{{ $t('chat.historyEmpty') }}</div>
        <template v-if="historySessions.length">
          <button
            v-for="session in visibleSessions"
            :key="session.session_id"
            type="button"
            class="task-card history-session-item"
            :class="{ 'history-session-item-active': session.session_id === currentSessionId }"
            @click="$emit('load-session', session.session_id)"
          >
            <div class="task-header history-session-title">
              <span>{{ session.title || $t('chat.newSession') }}</span>
              <span v-if="session.session_id === currentSessionId" class="history-current-badge">{{ $t('chat.current') }}</span>
            </div>
            <div class="history-session-meta">
              <span>{{ $t('chat.messageCount', { count: session.message_count || 0 }) }}</span>
              <span v-if="session.activity" :data-status="session.activity" aria-live="polite">
                {{ $t(`chat.conversationStatus.${session.activity}`) }}
              </span>
              <span v-if="session.last_message_at">
                {{ formatHistoryTime(session.last_message_at) }}
              </span>
              <span v-if="session.is_local_only">{{ $t('chat.localOnly') }}</span>
            </div>
          </button>
          <nav v-if="sessionPageCount > 1" class="history-pagination" aria-label="已加载会话分页">
            <button type="button" :disabled="sessionPage === 0" @click="sessionPage--">上一页</button>
            <span aria-live="polite">{{ sessionPage + 1 }} / {{ sessionPageCount }} · {{ historySessions.length }} 条已加载会话</span>
            <button type="button" :disabled="sessionPage + 1 >= sessionPageCount" @click="sessionPage++">下一页</button>
          </nav>
          <button v-if="historyHasMore" type="button" class="btn btn-secondary btn-sm" :disabled="historyLoadingMore" @click="$emit('load-more')">{{ historyLoadingMore ? '正在加载…' : '加载更早的会话' }}</button>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { computed, ref, watch } from 'vue'
import { formatHistoryTime } from '@/utils/chatTaskLabels'
import type { HistorySessionItem } from '@/composables/useChatSessionHistory'
import { isChatConversationBusy } from '@/composables/useChatSessionActivity'

useI18n()

const props = defineProps<{
  show: boolean
  historySessions: HistorySessionItem[]
  historyLoading: boolean
  historyHasMore?: boolean
  historyLoadingMore?: boolean
  historyError: string
  currentSessionId: string
}>()

const SESSION_PAGE_SIZE = 60
const sessionPage = ref(0)
const sessionPageCount = computed(() => Math.max(1, Math.ceil(props.historySessions.length / SESSION_PAGE_SIZE)))
const visibleSessions = computed(() =>
  props.historySessions.slice(sessionPage.value * SESSION_PAGE_SIZE, (sessionPage.value + 1) * SESSION_PAGE_SIZE),
)
watch(sessionPageCount, count => { sessionPage.value = Math.min(sessionPage.value, count - 1) })
watch(() => props.show, show => { if (show) sessionPage.value = 0 })

defineEmits<{
  close: []
  refresh: []
  'load-more': []
  clear: []
  'load-session': [sessionId: string]
}>()
</script>

<style scoped>
.history-modal-content {
  max-width: 560px;
}

.history-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.history-modal-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.history-modal-btn {
  min-width: 54px;
}

.history-modal-btn-danger {
  border-color: #fecaca;
  color: #b91c1c;
  background: #fff5f5;
}

.history-modal-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: pointer;
}

.history-modal-close:focus-visible {
  outline: 2px solid #2563eb;
  outline-offset: 2px;
}

.history-modal-body {
  max-height: 420px;
  overflow-y: auto;
}

.history-error-wrap {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px;
  border-radius: 8px;
  background: #fef2f2;
  border: 1px solid #fecaca;
}

.history-error-text {
  color: #b91c1c;
  font-size: 13px;
}

.history-pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 8px;
  font-size: 12px;
}
.history-pagination button:disabled { opacity: .5; cursor: default; }

.history-session-item {
  width: 100%;
  border: 1px solid #e5e7eb;
  background: #fff;
  text-align: left;
  cursor: pointer;
  margin-bottom: 8px;
}

.history-session-item-active {
  border-color: #93c5fd;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.12);
}

.history-session-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.history-current-badge {
  font-size: 11px;
  color: #1d4ed8;
  background: #dbeafe;
  border-radius: 999px;
  padding: 2px 8px;
}

.history-session-meta {
  margin-top: 4px;
  color: #6b7280;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 10px;
}
</style>
