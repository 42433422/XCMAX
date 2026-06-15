<template>
  <div v-if="show" class="modal active">
    <div class="modal-content history-modal-content">
      <div class="modal-header history-modal-header">
        <span>{{ $t('chat.historyTitle') }}</span>
        <div class="history-modal-actions">
          <button
            type="button"
            class="btn btn-secondary btn-sm history-modal-btn"
            :disabled="historyLoading"
            @click="$emit('refresh')"
          >
            {{ $t('chat.refresh') }}
          </button>
          <button
            type="button"
            class="btn btn-secondary btn-sm history-modal-btn history-modal-btn-danger"
            :disabled="historyLoading || historySessions.length === 0"
            @click="$emit('clear')"
          >
            {{ $t('chat.clear') }}
          </button>
          <span class="close" @click="$emit('close')">×</span>
        </div>
      </div>
      <div class="modal-body history-modal-body">
        <div v-if="historyLoading" class="empty-state">{{ $t('chat.historyLoading') }}</div>
        <div v-else-if="historyError" class="history-error-wrap">
          <div class="history-error-text">{{ historyError }}</div>
          <button
            type="button"
            class="btn btn-secondary btn-sm"
            @click="$emit('refresh')"
          >
            {{ $t('chat.retry') }}
          </button>
        </div>
        <div v-else-if="historySessions.length === 0" class="empty-state">
          {{ $t('chat.historyEmpty') }}
          <div class="history-empty-tip">{{ $t('chat.historyEmptyTip') }}</div>
        </div>
        <template v-else>
          <button
            v-for="session in historySessions"
            :key="session.session_id"
            type="button"
            class="task-card history-session-item"
            :class="{ 'history-session-item-active': session.session_id === currentSessionId }"
            :disabled="historyLoading"
            @click="$emit('load-session', session.session_id)"
          >
            <div class="task-header history-session-title">
              <span>{{ session.title || $t('chat.newSession') }}</span>
              <span v-if="session.session_id === currentSessionId" class="history-current-badge">{{ $t('chat.current') }}</span>
            </div>
            <div class="history-session-meta">
              <span>{{ $t('chat.messageCount', { count: session.message_count || 0 }) }}</span>
              <span v-if="session.last_message_at">
                {{ formatTaskTime(new Date(session.last_message_at).getTime()) }}
              </span>
              <span v-if="session.is_local_only">{{ $t('chat.localOnly') }}</span>
            </div>
          </button>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

useI18n()

defineProps<{
  show: boolean
  historySessions: Array<{
    session_id: string
    title?: string
    message_count?: number
    last_message_at?: string
    is_local_only?: boolean
  }>
  historyLoading: boolean
  historyError: string
  currentSessionId: string
  formatTaskTime: (ts: number) => string
}>()

defineEmits<{
  close: []
  refresh: []
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

.history-empty-tip {
  margin-top: 8px;
  font-size: 12px;
  color: #6b7280;
}

.history-session-item {
  width: 100%;
  border: 1px solid #e5e7eb;
  background: #fff;
  text-align: left;
  cursor: pointer;
  margin-bottom: 8px;
}

.history-session-item:disabled {
  opacity: 0.65;
  cursor: not-allowed;
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
