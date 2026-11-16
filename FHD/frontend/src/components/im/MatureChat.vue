<template>
  <section class="mature-chat" :aria-label="title">
    <p v-if="loadError || validationError" class="mature-chat__notice" role="alert">{{ loadError || validationError }}</p>
    <component v-if="ready" :is="'vue-advanced-chat'" :key="roomId"
      height="100%" current-user-id="self" :room-id="roomId" :rooms="JSON.stringify(rooms)"
      :messages="JSON.stringify(chatMessages)" :single-room="true" :rooms-loaded="true"
      :messages-loaded="historyReady && !hasMore" :show-footer="!disabled" :show-files="false" :show-audio="false"
      :show-emojis="false" :show-reaction-emojis="false" :show-new-messages-divider="false" :user-tags-enabled="false"
      :emojis-suggestion-enabled="false" :message-actions="'[]'" :message-selection-actions="'[]'"
      :room-message="composerDraft" :text-messages="JSON.stringify(labels)" :styles="JSON.stringify(theme)"
      :username-options="'{&quot;minUsers&quot;:1,&quot;currentUser&quot;:false}'"
      :link-options="'{&quot;disabled&quot;:false,&quot;target&quot;:&quot;_blank&quot;,&quot;rel&quot;:&quot;noopener noreferrer&quot;}'"
      @send-message="send" @typing-message="typing" @fetch-messages="fetchHistory">
      <div slot="room-header-info" class="mature-chat__identity"><strong>{{ title }}</strong><small>{{ subtitle }}</small></div>
      <div slot="room-options" class="mature-chat__actions"><slot name="actions" /></div>
      <div v-if="$slots.avatar" slot="room-header-avatar" class="mature-chat__avatar"><slot name="avatar" /></div>
      <div slot="messages-empty" class="mature-chat__empty">暂无消息</div>
    </component>
    <p v-else class="mature-chat__notice">正在加载聊天…</p>
    <div v-if="disabled" class="mature-chat__notice" role="status">{{ busyLabel || '暂不可发送' }}</div>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
export type ChatRow = { id: string | number; body: string; mine: boolean; sender: string; avatar?: string | null; at?: string | null; label?: string }
const props = withDefaults(defineProps<{ roomId: string; title: string; subtitle?: string; avatar?: string | null;
  rows: ChatRow[]; draft?: string; disabled?: boolean; busyLabel?: string; hasMore?: boolean; placeholder?: string }>(), { draft: '', placeholder: '输入消息…' })
const emit = defineEmits<{ (event: 'update:draft', value: string): void; (event: 'send', value: string): void; (event: 'load-older'): void }>()
const ready = ref(false)
const historyReady = ref(false)
const loadError = ref('')
const validationError = ref('')
const composerDraft = ref(props.draft)
watch(() => props.draft, value => { composerDraft.value = value })
onMounted(async () => {
  try { const { register } = await import('vue-advanced-chat'); if (!customElements.get('vue-advanced-chat')) register(); ready.value = true }
  catch { loadError.value = '聊天组件加载失败，请刷新重试' }
})
const rooms = computed(() => [{ roomId: props.roomId, roomName: props.title, avatar: props.avatar || '',
  users: [{ _id: 'self', username: '我' }, { _id: 'peer', username: props.title }] }])
const chatMessages = computed(() => (historyReady.value ? props.rows : []).map(row => {
  const date = row.at ? new Date(row.at) : undefined
  const valid = date && !Number.isNaN(date.getTime())
  return { _id: String(row.id), content: row.body, senderId: row.mine ? 'self' : 'peer',
    username: [row.sender, row.label].filter(Boolean).join(' · '), avatar: row.avatar || '',
    date: valid ? date.toLocaleDateString('zh-CN') : '', timestamp: valid ? date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : '',
    disableActions: true, disableReactions: true }
}))
const labels = computed(() => ({ ROOMS_EMPTY: '暂无会话', ROOM_EMPTY: '选择会话', NEW_MESSAGES: '新消息',
  MESSAGES_EMPTY: '暂无消息', CONVERSATION_STARTED: '', TYPE_MESSAGE: props.placeholder,
  SEARCH: '搜索会话', IS_ONLINE: '在线', LAST_SEEN: '最近在线', IS_TYPING: '正在输入…', CANCEL_SELECT_MESSAGE: '取消' }))
const theme = { general: { color: '#1f2937', background: '#f6f7f9', borderStyle: 'none' },
  container: { borderRadius: '0' }, header: { background: '#ffffff' }, footer: { background: '#ffffff', borderStyle: '1px solid #edf0f4' },
  message: { background: '#ffffff', backgroundMe: '#e6efff', color: '#1f2937', colorMe: '#1f2937' } }
function payload(event: Event) { const detail = (event as CustomEvent).detail; return Array.isArray(detail) ? detail[0] : detail }
function typing(event: Event) { const value = payload(event)?.message; if (typeof value === 'string') emit('update:draft', value) }
async function send(event: Event) {
  const value = String(payload(event)?.content || '').trim()
  if (props.disabled || !value) return
  if (value.length > 4000) {
    validationError.value = '消息不能超过 4000 字'
    composerDraft.value = ''
    await nextTick()
    composerDraft.value = value
    emit('update:draft', value)
    return
  }
  validationError.value = ''
  emit('update:draft', value)
  emit('send', value)
}
async function fetchHistory(event: Event) {
  if (payload(event)?.options?.reset) { historyReady.value = false; await nextTick(); historyReady.value = true }
  else if (props.hasMore) emit('load-older')
}
watch(ready, async value => { if (value) { await nextTick(); historyReady.value = true } })
</script>

<style scoped>
.mature-chat { display:flex; flex:1; flex-direction:column; min-width:0; min-height:0; overflow:hidden; }
vue-advanced-chat { display:block; flex:1; min-height:0; height:100%; width:100%; }
.mature-chat__identity { display:flex; flex-direction:column; gap:5px; min-width:0; }
.mature-chat__identity strong { font-size:15px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.mature-chat__identity small { color:#8a94a3; font-size:12px; }
.mature-chat__avatar { flex:none; margin-right:12px; }
.mature-chat__actions { flex-shrink:0; white-space:nowrap; display:flex; align-items:center; gap:8px; }
.mature-chat__empty { color:#a4aab5; font-size:13px; padding:24px; }
.mature-chat__notice { margin:0; padding:10px 18px; font-size:12px; color:#6b7280; background:#f8fafc; }
</style>
