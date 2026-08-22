<template>
  <div class="conv-panel">
    <div class="conv-panel-toolbar">
      <button type="button" class="btn btn-primary btn-sm" :disabled="loading" @click="$emit('new')">
        <i class="fa fa-plus" aria-hidden="true"></i> {{ $t('chat.newConversation') }}
      </button>
      <button
        type="button"
        class="btn btn-secondary btn-sm"
        :disabled="loading || sessions.length === 0"
        @click="$emit('clear')"
      >
        {{ $t('chat.clear') }}
      </button>
    </div>

    <div class="conv-panel-body">
      <div v-if="loading" class="conv-empty">{{ $t('chat.historyLoading') }}</div>
      <div v-else-if="error" class="conv-error">
        <span class="conv-error-text">{{ error }}</span>
        <button type="button" class="btn btn-secondary btn-sm" @click="$emit('refresh')">{{ $t('chat.retry') }}</button>
      </div>
      <div v-else-if="sessions.length === 0" class="conv-empty">
        {{ $t('chat.historyEmpty') }}
        <div class="conv-empty-tip">{{ $t('chat.historyEmptyTip') }}</div>
      </div>
      <template v-else>
        <div v-for="group in groupedSessions" :key="group.key" class="conv-group">
          <div class="conv-group-label">{{ group.label }}</div>
          <ul class="conv-list">
            <li
              v-for="session in group.items"
              :key="session.session_id"
              :class="['conv-item', { 'conv-item--active': session.session_id === currentSessionId }]"
            >
              <button
                type="button"
                class="conv-item-main"
                :title="session.title || $t('chat.newSession')"
                @click="$emit('load', session.session_id)"
              >
                <span class="conv-item-title">{{ session.title || $t('chat.newSession') }}</span>
                <span class="conv-item-meta">
                  <span>{{ $t('chat.messageCount', { count: session.message_count || 0 }) }}</span>
                  <span v-if="session.is_local_only" class="conv-item-local">{{ $t('chat.localOnly') }}</span>
                </span>
              </button>
              <span class="conv-item-actions">
                <button
                  type="button"
                  class="conv-action-btn"
                  :title="$t('chat.renameSession')"
                  @click.stop="startRename(session)"
                >
                  <i class="fa fa-pencil" aria-hidden="true"></i>
                </button>
                <button
                  type="button"
                  class="conv-action-btn conv-action-btn--danger"
                  :title="$t('chat.deleteSession')"
                  @click.stop="confirmDelete(session)"
                >
                  <i class="fa fa-trash-o" aria-hidden="true"></i>
                </button>
              </span>
            </li>
          </ul>
        </div>
      </template>
    </div>

    <div v-if="renamingSession" class="conv-rename-overlay">
      <div class="conv-rename-box">
        <input
          v-model="renameValue"
          type="text"
          class="form-control"
          maxlength="80"
          :placeholder="$t('chat.renamePlaceholder')"
          @keydown.enter="submitRename"
          @keydown.esc="cancelRename"
        >
        <div class="conv-rename-actions">
          <button type="button" class="btn btn-secondary btn-sm" @click="cancelRename">{{ $t('chat.cancel') }}</button>
          <button type="button" class="btn btn-primary btn-sm" :disabled="!renameValue.trim()" @click="submitRename">
            {{ $t('chat.renameConfirm') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { HistorySessionItem } from '@/composables/useChatSessionHistory'

useI18n()

const props = defineProps<{
  sessions: HistorySessionItem[]
  currentSessionId: string
  loading: boolean
  error: string
}>()

const emit = defineEmits<{
  new: []
  refresh: []
  clear: []
  load: [sessionId: string]
  rename: [sessionId: string, title: string]
  delete: [sessionId: string]
}>()

type Group = { key: string; label: string; items: HistorySessionItem[] }

const GROUP_LABELS: Array<{ key: string; label: string; match: (ts: number) => boolean }> = [
  { key: 'today', label: '今天', match: (ts) => isSameDay(ts, Date.now()) },
  { key: 'yesterday', label: '昨天', match: (ts) => isSameDay(ts, Date.now() - 86400000) },
  { key: 'week', label: '近 7 天', match: (ts) => ts >= Date.now() - 7 * 86400000 },
  { key: 'earlier', label: '更早', match: () => true },
]

function isSameDay(a: number, b: number): boolean {
  if (!a) return false
  const da = new Date(a)
  const db = new Date(b)
  return da.getFullYear() === db.getFullYear() && da.getMonth() === db.getMonth() && da.getDate() === db.getDate()
}

function toTs(raw: string | undefined): number {
  const ts = Date.parse(String(raw || '').trim())
  return Number.isFinite(ts) ? ts : 0
}

const groupedSessions = computed<Group[]>(() => {
  const groups = GROUP_LABELS.map((g) => ({ ...g, items: [] as HistorySessionItem[] }))
  for (const session of props.sessions) {
    const ts = toTs(session.last_message_at)
    const bucket = groups.find((g) => g.match(ts)) || groups[groups.length - 1]
    bucket.items.push(session)
  }
  return groups.filter((g) => g.items.length > 0)
})

const renamingSession = ref<HistorySessionItem | null>(null)
const renameValue = ref('')

function startRename(session: HistorySessionItem) {
  renamingSession.value = session
  renameValue.value = session.title || ''
}

function cancelRename() {
  renamingSession.value = null
  renameValue.value = ''
}

function submitRename() {
  const title = renameValue.value.trim()
  if (!renamingSession.value || !title) return
  emit('rename', renamingSession.value.session_id, title)
  renamingSession.value = null
  renameValue.value = ''
}

function confirmDelete(session: HistorySessionItem) {
  const ok = window.confirm(`确认删除会话「${session.title || '新会话'}」吗？此操作不可撤销。`)
  if (ok) emit('delete', session.session_id)
}
</script>

<style scoped>
.conv-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.conv-panel-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-bottom: 1px solid var(--app-border-subtle, #e5e7eb);
  flex: none;
}

.conv-panel-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 8px 10px;
}

.conv-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 24px 8px;
  color: var(--app-text-muted, #6b7280);
  text-align: center;
  font-size: 13px;
}

.conv-empty-tip {
  font-size: 12px;
  color: var(--app-text-caption, #9ca3af);
}

.conv-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px;
  border-radius: 8px;
  background: #fef2f2;
  border: 1px solid #fecaca;
}

.conv-error-text {
  color: #b91c1c;
  font-size: 13px;
}

.conv-group {
  margin-bottom: 14px;
}

.conv-group-label {
  padding: 4px 6px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.03em;
  text-transform: uppercase;
  color: var(--app-text-caption, #9ca3af);
}

.conv-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.conv-item {
  display: flex;
  align-items: center;
  gap: 4px;
  border-radius: 8px;
  transition: background 150ms ease;
}

.conv-item:hover {
  background: rgba(0, 0, 0, 0.035);
}

.conv-item--active {
  background: rgba(0, 82, 217, 0.08);
}

.conv-item-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  border: 0;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.conv-item-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--app-text-strong, #1f2329);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.conv-item-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--app-text-muted, #86909c);
}

.conv-item-local {
  color: #b45309;
  background: #fef3c7;
  border-radius: 4px;
  padding: 0 5px;
  font-size: 11px;
}

.conv-item-actions {
  display: flex;
  gap: 2px;
  padding-right: 6px;
  opacity: 0;
  transition: opacity 150ms ease;
}

.conv-item:hover .conv-item-actions,
.conv-item--active .conv-item-actions {
  opacity: 1;
}

.conv-action-btn {
  width: 26px;
  height: 26px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--app-text-muted, #86909c);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
}

.conv-action-btn:hover {
  background: rgba(0, 82, 217, 0.1);
  color: var(--app-interactive, #0052d9);
}

.conv-action-btn--danger:hover {
  background: #fef2f2;
  color: #dc2626;
}

.conv-rename-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(15, 23, 42, 0.3);
}

.conv-rename-box {
  width: 320px;
  max-width: calc(100vw - 40px);
  padding: 16px;
  border-radius: 12px;
  background: var(--card-bg, #fff);
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.18);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.conv-rename-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>