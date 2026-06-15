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
      @click="onUploadClick"
      :disabled="excelAnalyzeUploading"
    >
      <i class="fa fa-upload" aria-hidden="true"></i>
      {{ excelAnalyzeUploading ? $t('shell.uploadAnalyzing') : $t('shell.upload') }}
      {{ multimodalPendingCount ? `(${multimodalPendingCount})` : '' }}
    </button>
    <input
      ref="fileInputRef"
      type="file"
      accept=".xlsx,.xlsm,.xls,image/jpeg,image/png,image/webp,image/gif,.pdf,application/pdf"
      multiple
      style="display:none"
      @change="onFileChange"
    >
    <label
      v-if="clientModeTiersUiEnabled"
      class="intent-pro-toggle"
      data-tutorial-id="intent-pro-experience-toggle"
      :title="$t('chat.proIntentTitle')"
    >
      <input
        type="checkbox"
        :checked="proIntentExperienceEnabled"
        @change="onProIntentChange"
      >
      <span class="intent-pro-toggle-text">{{ $t('chat.proIntentToggle') }}</span>
    </label>
    <label
      data-tutorial-id="star-auto-refresh-toggle"
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
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

useI18n()

const props = defineProps<{
  excelAnalyzeUploading: boolean
  multimodalPendingCount: number
  clientModeTiersUiEnabled: boolean
  proIntentExperienceEnabled: boolean
  autoRefreshStarredWechat: boolean
  ttsEnabled: boolean
}>()

const emit = defineEmits<{
  'new-conversation': []
  'show-history': []
  'trigger-upload': []
  'register-excel-input': [el: HTMLInputElement | null]
  'excel-file-change': [event: Event]
  'pro-intent-change': [enabled: boolean]
  'auto-refresh-change': [enabled: boolean]
  'toggle-tts': [enabled: boolean]
}>()

const fileInputRef = ref<HTMLInputElement | null>(null)

watch(fileInputRef, (el) => {
  emit('register-excel-input', el)
}, { immediate: true })

function onUploadClick() {
  if (props.excelAnalyzeUploading) return
  fileInputRef.value?.click()
  emit('trigger-upload')
}

function onFileChange(event: Event) {
  emit('excel-file-change', event)
}

function onProIntentChange(event: Event) {
  emit('pro-intent-change', (event.target as HTMLInputElement).checked)
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
