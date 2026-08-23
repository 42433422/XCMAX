<template>
  <div class="input-toolbar">
    <button class="toolbar-btn" id="newConversationBtn" :title="$t('chat.newConversationTitle')" @click="$emit('new-conversation')">
      <i class="fa fa-plus" aria-hidden="true"></i> {{ $t('shell.newChat') }}
    </button>
    <div class="approval-mode" data-testid="approval-mode-toggle">
      <button
        class="toolbar-btn approval-mode__toggle"
        id="approvalModeBtn"
        type="button"
        :title="$t('chat.approvalModeTitle')"
        :aria-pressed="approvalMode.state.enabled"
        :class="{ 'is-active': approvalMode.state.enabled }"
        @click="toggleApproval"
      >
        <i class="fa fa-shield" aria-hidden="true"></i> {{ $t('chat.approvalMode') }}
      </button>
      <div
        v-if="approvalMode.state.enabled"
        class="approval-mode__choices"
        role="radiogroup"
        :aria-label="$t('chat.approvalMode')"
      >
        <button
          type="button"
          class="approval-mode__choice"
          :class="{ 'is-active': approvalMode.state.mode === 'manual' }"
          :aria-pressed="approvalMode.state.mode === 'manual'"
          @click="approvalMode.setMode('manual')"
        >
          {{ $t('chat.approvalManual') }}
        </button>
        <button
          type="button"
          class="approval-mode__choice"
          :class="{ 'is-active': approvalMode.state.mode === 'auto' }"
          :aria-pressed="approvalMode.state.mode === 'auto'"
          @click="approvalMode.setMode('auto')"
        >
          {{ $t('chat.approvalAuto') }}
        </button>
      </div>
    </div>
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
      style="display: none"
      @change="onFileChange"
    />
    <label
      data-tutorial-id="star-auto-refresh-toggle"
      :title="$t('chat.starAutoRefreshTitle')"
      style="
        margin-left: auto;
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: var(--app-font-size-caption);
        color: var(--app-text-muted);
        cursor: pointer;
        user-select: none;
      "
    >
      <input type="checkbox" :checked="autoRefreshStarredWechat" @change="onAutoRefreshChange" />
      {{ $t('chat.starAutoRefresh') }}
    </label>
    <label
      :title="$t('chat.ttsTitle')"
      style="
        margin-left: 12px;
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: var(--app-font-size-caption);
        color: var(--app-text-muted);
        cursor: pointer;
        user-select: none;
      "
    >
      <input type="checkbox" :checked="ttsEnabled" @change="$emit('toggle-tts', !ttsEnabled)" />
      <i class="fa fa-volume-up" aria-hidden="true"></i> {{ $t('chat.ttsToggle') }}
    </label>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApprovalMode } from '@/composables/useApprovalMode'

useI18n()

const approvalMode = useApprovalMode()

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
  'trigger-office-docking': []
  'register-excel-input': [input: HTMLInputElement | null]
  'excel-file-change': [event: Event]
  'auto-refresh-change': [enabled: boolean]
  'toggle-tts': [enabled: boolean]
}>()

const fileInputRef = ref<HTMLInputElement | null>(null)

function toggleApproval() {
  approvalMode.setEnabled(!approvalMode.state.enabled)
}

watch(
  fileInputRef,
  (el) => {
    if (props.excelAnalyzeInputRef) {
      // Parent-owned ref bridge for Excel upload input
      // eslint-disable-next-line vue/no-mutating-props -- intentional ref forwarding
      props.excelAnalyzeInputRef.value = el
    }
    emit('register-excel-input', el)
  },
  { immediate: true },
)

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

.approval-mode {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.approval-mode__toggle.is-active {
  color: var(--xc-color-primary, #0d47a1);
  border-color: var(--xc-color-primary, #0d47a1);
}

.approval-mode__choices {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding-left: 2px;
  border-left: 2px solid var(--xc-color-primary, #0d47a1);
}

.approval-mode__choice {
  background: transparent;
  border: none;
  padding: 2px 8px;
  font-size: var(--app-font-size-caption, 12px);
  color: var(--app-text-muted, #667085);
  cursor: pointer;
  border-radius: 2px;
}

.approval-mode__choice.is-active {
  color: var(--xc-color-primary, #0d47a1);
  background: rgba(13, 71, 161, 0.08);
}
</style>
