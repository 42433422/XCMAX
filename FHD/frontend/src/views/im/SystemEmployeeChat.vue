<template>
  <main class="im-chat im-chat--system-employee">
    <MatureChat :key="activeSystemEntry.id" :room-id="String(activeSystemEntry.id)" :title="activeSystemEntry.display_name"
      :subtitle="systemEntryStatusLabel(activeSystemEntry)" :avatar="avatar"
      :rows="rows" :draft="isSuper ? codexDraft : dutyEmployeeDraft"
      :disabled="isSuper ? codexBusy : dutyEmployeeBusy || isPlannedDutyEmployee(activeSystemEntry)"
      :busy-label="isPlannedDutyEmployee(activeSystemEntry) ? '该员工尚未安装' : '正在处理…'"
      :placeholder="`向${activeSystemEntry.display_name}发送消息…`" @update:draft="updateDraft" @send="send">
      <template #actions>
        <select v-if="isSuper" class="im-tool-select" aria-label="切换开发员工" :value="activeSystemEntry.id"
          @change="emit('activate-pinned', superCliTools.find(t => String(t.id) === ($event.target as HTMLSelectElement).value)!)">
          <option v-for="tool in superCliTools" :key="tool.id" :value="tool.id">{{ superCliToolLabel(tool) }}</option>
        </select>
        <button class="im-profile-button" :aria-expanded="showProfile" @click="showProfile = !showProfile">员工资料</button>
      </template>
    </MatureChat>
    <aside v-if="showProfile" class="im-employee-profile" aria-label="员工资料">
      <header><strong>{{ activeSystemEntry.display_name }}</strong><button class="im-profile-button" @click="showProfile = false">关闭</button></header>
      <dl>
        <dt>身份</dt><dd>{{ systemEntryIdentity(activeSystemEntry) }}</dd>
        <template v-if="isDutyEmployeeEntry(activeSystemEntry)"><dt>职责</dt><dd>{{ activeSystemEntry.description }}</dd></template>
        <dt>调度</dt><dd>{{ systemEntryDispatch(activeSystemEntry) }}</dd>
        <dt>状态</dt><dd>{{ systemEntryRuntimeStatus(activeSystemEntry) }}</dd>
        <dt>最近任务</dt><dd>{{ systemEntryLastStatus(activeSystemEntry) }}</dd>
      </dl>
    </aside>
  </main>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, type Ref } from 'vue'
import MatureChat from '@/components/im/MatureChat.vue'
import {
  type CodexDisplayMessage,
  type DutyEmployeeChatMessage,
  type SystemEmployeeEntry,
} from '@/composables/messenger/useMessengerEntries'
import './SystemEmployeeChat.css'

const props = defineProps<{
  activeSystemEntry: SystemEmployeeEntry
  activeAvatarSrc?: string | null
  superCliTools: SystemEmployeeEntry[]
  superCliToolLabel: (entry: SystemEmployeeEntry) => string
  systemEntryStatusLabel: (entry: SystemEmployeeEntry) => string
  systemEntryIdentity: (entry: SystemEmployeeEntry) => string
  systemEntryDispatch: (entry: SystemEmployeeEntry) => string
  systemEntryRuntimeStatus: (entry: SystemEmployeeEntry) => string
  systemEntryLastStatus: (entry: SystemEmployeeEntry) => string
  superEmployeeAvatarKey: (entry: SystemEmployeeEntry) => string | null
  superEmployeeAvatarSrc: (entry: SystemEmployeeEntry) => string | null
  pinnedAvatarText: (entry: SystemEmployeeEntry) => string
  isDutyEmployeeEntry: (entry: SystemEmployeeEntry | null) => boolean
  isSuperEmployeeEntry: (entry: SystemEmployeeEntry | null) => boolean
  codexMessageRoleLabel: (m: CodexDisplayMessage) => string
  isCodexStreamingMessage: (m: CodexDisplayMessage) => boolean
  formatTime: (iso: string | null) => string
  codexVisibleMessages: CodexDisplayMessage[]
  activeDutyEmployeeMessages: DutyEmployeeChatMessage[]
  codexDraft: string
  codexBusy: boolean
  dutyEmployeeDraft: string
  dutyEmployeeBusy: boolean
  codexScrollEl: Ref<HTMLElement | null>
  dutyEmployeeScrollEl: Ref<HTMLElement | null>
  codexInputEl: Ref<HTMLInputElement | null>
}>()

const emit = defineEmits<{
  (e: 'activate-pinned', entry: SystemEmployeeEntry): void
  (e: 'codex-send'): void
  (e: 'duty-employee-send'): void
  (e: 'update:codexDraft', value: string): void
  (e: 'update:dutyEmployeeDraft', value: string): void
}>()

const showProfile = ref(false)
const isSuper = computed(() => props.isSuperEmployeeEntry(props.activeSystemEntry))
const avatar = computed(() => props.superEmployeeAvatarSrc(props.activeSystemEntry) || props.activeAvatarSrc)
const rows = computed(() => (isSuper.value ? props.codexVisibleMessages : props.activeDutyEmployeeMessages).map(m => ({
  id: m.id, body: m.body, mine: m.role === 'user', sender: m.role === 'user' ? '我' : props.activeSystemEntry.display_name,
  label: isSuper.value && props.isCodexStreamingMessage(m as CodexDisplayMessage) ? '正在回复' : '',
  avatar: m.role === 'user' ? '' : avatar.value, at: m.created_at,
})))
function updateDraft(value: string) {
  if (isSuper.value) emit('update:codexDraft', value)
  else emit('update:dutyEmployeeDraft', value)
}
async function send(value: string) {
  updateDraft(value)
  await nextTick()
  if (isSuper.value) emit('codex-send')
  else emit('duty-employee-send')
}

function isPlannedDutyEmployee(entry: SystemEmployeeEntry): boolean {
  return 'is_duty_employee_entry' in entry && entry.status === 'planned'
}
</script>
