<template>
  <div class="input-toolbar">
    <button class="toolbar-btn" id="newConversationBtn" :title="$t('chat.newConversationTitle')" @click="$emit('new-conversation')">
      <i class="fa fa-plus" aria-hidden="true"></i> {{ $t('shell.newChat') }}
    </button>
    <button class="toolbar-btn" id="historyPanelBtn" :title="$t('chat.historyTitleBtn')" @click="$emit('show-history')">
      <i class="fa fa-history" aria-hidden="true"></i> {{ $t('shell.history') }}
    </button>
    <button
      class="toolbar-btn"
      type="button"
      data-tutorial-id="toolbar-excel-analyze"
      :title="$t('chat.uploadTitle')"
      @click="triggerUpload"
      :disabled="excelAnalyzeUploading"
    >
      <i class="fa fa-upload" aria-hidden="true"></i>
      {{ excelAnalyzeUploading ? $t('shell.uploadAnalyzing') : $t('chat.uploadAttachment') }}
      {{ multimodalPendingCount ? `(${multimodalPendingCount})` : '' }}
    </button>
    <button
      class="toolbar-btn"
      type="button"
      data-tutorial-id="toolbar-office-docking"
      :title="$t('chat.officeDockingTitle')"
      @click="$emit('trigger-office-docking')"
      :disabled="officeDockingProcessing"
    >
      <i class="fa fa-file-text-o" aria-hidden="true"></i>
      {{ officeDockingProcessing ? $t('chat.officeDockingBusy') : $t('chat.officeDocking') }}
    </button>
    <input
      ref="fileInputRef"
      type="file"
      accept=".xlsx,.xlsm,image/jpeg,image/png,image/webp,image/gif,.pdf,application/pdf"
      multiple
      style="display:none"
      @change="onFileChange"
    >
    <label
      data-tutorial-id="star-auto-refresh-toggle"
      :title="$t('chat.starAutoRefreshTitle')"
      style="margin-left:auto;display:flex;align-items:center;gap:6px;font-size:var(--app-font-size-caption);color:var(--app-text-muted);cursor:pointer;user-select:none;"
    >
      <input
        type="checkbox"
        :checked="autoRefreshStarredWechat"
        @change="onAutoRefreshChange"
      >
      {{ $t('chat.starAutoRefresh') }}
    </label>
    <label
      :title="$t('chat.ttsTitle')"
      style="margin-left:12px;display:flex;align-items:center;gap:6px;font-size:var(--app-font-size-caption);color:var(--app-text-muted);cursor:pointer;user-select:none;"
    >
      <input
        type="checkbox"
        :checked="ttsEnabled"
        @change="$emit('toggle-tts', !ttsEnabled)"
      >
      <i class="fa fa-volume-up" aria-hidden="true"></i> {{ $t('chat.ttsToggle') }}
    </label>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'

useI18n()

const props = defineProps<{
  excelAnalyzeUploading: boolean
  multimodalPendingCount: number
  autoRefreshStarredWechat: boolean
  ttsEnabled: boolean
  officeDockingProcessing?: boolean
  excelAnalyzeInputRef?: Ref<HTMLInputElement | null>
}>()

const emit = defineEmits<{
  'new-conversation': []
  'show-history': []
  'trigger-office-docking': []
  'register-excel-input': [input: HTMLInputElement | null]
  'excel-file-change': [event: Event]
  'auto-refresh-change': [enabled: boolean]
  'toggle-tts': [enabled: boolean]
}>()

const fileInputRef = ref<HTMLInputElement | null>(null)

watch(fileInputRef, (el) => {
  if (props.excelAnalyzeInputRef) {
    // Parent-owned ref bridge for Excel upload input
    // eslint-disable-next-line vue/no-mutating-props -- intentional ref forwarding
    props.excelAnalyzeInputRef.value = el
  }
  emit('register-excel-input', el)
}, { immediate: true })

function triggerUpload() {
  fileInputRef.value?.click()
}

function onFileChange(event: Event) {
  emit('excel-file-change', event)
}

function onAutoRefreshChange(event: Event) {
  emit('auto-refresh-change', (event.target as HTMLInputElement).checked)
}
</script>

<style scoped>
.input-toolbar {
  align-items: center;
  flex-wrap: wrap;
}
</style>
